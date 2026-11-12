"""Orders placed on a shop's website arriving by webhook: signature checks, Shopify / WooCommerce / Dakbox-format payloads, once-only creation,
paid and cancelled follow-ups, stock mirroring, customer matching, currency. Payloads follow the platforms' public documentation and have
never been checked against a real shop."""
import base64
import hashlib
import hmac
import json

import httpx
import pytest

from app import couriers, db, sms, store
from app.main import app
from app.secrets_store import seal
from tests.test_auth import H, member_token, setup_owner

SECRET = "whsec-test-secret-1234"
HOST = "shop.test"


@pytest.fixture
async def http():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
def fired(monkeypatch):
    calls = []
    monkeypatch.setattr(sms, "fire", lambda number, event, **kw: calls.append((number, event)))
    return calls


def make_source(kind="shopify", secret=SECRET, currency=None, sms_on=1, sid="cs_test1"):
    db.run("DELETE FROM catalog_sources")
    db.run("DELETE FROM products WHERE source IS NOT NULL")
    db.run("INSERT INTO catalog_sources(id,host,url,kind,default_stock,currency,created_at,order_secret,order_sms) VALUES(?,?,?,?,?,?,?,?,?)",
           [sid, HOST, f"https://{HOST}/", kind, 10, currency, db.now(), seal(secret) if secret else None, sms_on])
    for sku, name, variant, price, sid_, stock in [("RT-GRN", "Ridgeline Tent 2P", "Green", 12500, "shopify:111", 10), ("TB-2L", "Trail Bottle 2L", None, 1450, "shopify:121", 10),
                                                   ("SJ-1", "Summit Jacket", None, 9500, "woo:21", 5)]:
        db.run("INSERT INTO products(id,sku,name,variant,price,stock,sold30,art,keywords,source,source_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
               [db.uid("p"), sku, name, variant, price, stock, 0, "box", "", HOST, sid_])
    return sid


def stock(sku):
    return db.get("SELECT stock FROM products WHERE sku=?", [sku])["stock"]


def b64sig(raw, secret=SECRET):
    return base64.b64encode(hmac.new(secret.encode(), raw, hashlib.sha256).digest()).decode()


async def post(http, payload, *, kind="shopify", secret=SECRET, sid="cs_test1", topic=None, raw=None, headers=None):
    raw = raw if raw is not None else json.dumps(payload).encode()
    h = {"content-type": "application/json"}
    if kind == "shopify":
        h.update({"X-Shopify-Hmac-Sha256": b64sig(raw, secret), "X-Shopify-Topic": topic or "orders/create"})
    elif kind == "woo":
        h.update({"X-WC-Webhook-Signature": b64sig(raw, secret), "X-WC-Webhook-Topic": topic or "order.created"})
    else:
        h.update({"X-Dakbox-Signature": "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()})
    h.update(headers or {})
    return await http.post(f"/webhooks/shop/{sid}", content=raw, headers=h)


def shopify_order(**over):
    o = {"id": 5001, "name": "#1001", "email": "buyer@example.com", "currency": "BDT", "financial_status": "pending", "cancelled_at": None,
         "total_price": "13900.00", "payment_gateway_names": ["Cash on Delivery (COD)"],
         "total_shipping_price_set": {"shop_money": {"amount": "110.00", "currency_code": "BDT"}},
         "customer": {"id": 77, "first_name": "Web", "last_name": "Buyer"},
         "shipping_address": {"name": "Web Buyer", "phone": "+8801755500022", "address1": "House 3, Road 5", "address2": "Zindabazar", "city": "Sylhet", "province": "", "zip": "3100"},
         "line_items": [{"id": 1, "variant_id": 111, "title": "Ridgeline Tent 2P", "variant_title": "Green", "sku": "RT-GRN", "quantity": 1, "price": "12500.00", "total_discount": "0.00"},
                        {"id": 2, "variant_id": 121, "title": "Trail Bottle 2L", "variant_title": "Default Title", "sku": "", "quantity": 1, "price": "1450.00", "total_discount": "160.00"}]}
    o.update(over)
    return o


def woo_order(**over):
    o = {"id": 900, "number": "900", "status": "processing", "currency": "BDT", "total": "9610.00", "shipping_total": "110.00", "shipping_tax": "0.00", "payment_method": "cod",
         "payment_method_title": "Cash on delivery", "date_paid": None, "customer_id": 0,
         "billing": {"first_name": "Woo", "last_name": "Buyer", "email": "w@example.com", "phone": "01955500033", "address_1": "Road 2", "city": "Dhaka", "postcode": "1205"},
         "shipping": {"first_name": "", "last_name": "", "address_1": ""},
         "line_items": [{"id": 5, "product_id": 21, "name": "Summit Jacket", "sku": "SJ-1", "quantity": 1, "total": "9500.00"}]}
    o.update(over)
    return o


def website_orders():
    return db.all("SELECT * FROM orders WHERE source='website' ORDER BY rowid")


# ---------------------------------------------------------------- Shopify
async def test_a_shopify_order_arrives_once_with_what_the_customer_was_charged(http, fired):
    make_source()
    r = await post(http, shopify_order())
    assert r.status_code == 200 and r.json()["created"].startswith("#")
    (o,) = website_orders()
    assert (o["source"], o["channel_kind"], o["ext_source"], o["ext_id"], o["ext_number"]) == ("website", "site", HOST, "5001", "#1001")
    items = db.jl(o["items"], [])
    assert [(i["sku"], i["qty"], i["price"], i["stock"] if "stock" in i else None) for i in items] == [("RT-GRN", 1, 12500, True), ("TB-2L", 1, 1290, True)]   # discount spread into the price
    assert items[0]["variant"] == "Green" and items[1]["variant"] is None
    assert (o["shipping"], o["zone"], o["pay_status"], o["pay_method"], o["stage"]) == (110, "out", "Pending", "Cash on delivery", 0)
    assert o["address"] == "House 3, Road 5, Zindabazar, Sylhet, 3100" and (o["ship_name"], o["ship_phone"]) == ("Web Buyer", "01755500022")
    assert stock("RT-GRN") == 9 and stock("TB-2L") == 9                                       # Dakbox's own count follows the shop
    sub, total = store.order_total(o)
    assert (sub, total) == (13790, 13900)                                                     # the shop charged 13,900: that is the total, and what the courier collects
    assert couriers.cod_amount(o) == 13900
    cust = store.customer(o["customer_id"])
    assert cust["phone"] == "01755500022" and "Website order" in db.jl(cust["tags"], [])
    assert fired == [(o["number"], "placed")]
    a = db.get("SELECT * FROM audit WHERE action='order.website'")
    assert a["target"] == o["number"] and "website order #1001" in a["detail"]
    src = db.get("SELECT * FROM catalog_sources")
    assert src["orders_count"] == 1 and src["orders_at"] and src["orders_error"] is None


async def test_http_view_of_a_website_order(http):
    make_source()
    await post(http, shopify_order())
    h = H(await setup_owner(http))
    v = next(o for o in (await http.get("/api/orders", headers=h)).json()["items"] if o["source"] == "website")
    assert v["site"] == {"host": HOST, "number": "#1001"} and v["total"] == 13900 and v["adjustment"] == 13900 - 13790 - 110 and v["channel"] == "site"


async def test_the_shop_sending_the_same_order_again_changes_nothing(http, fired):
    make_source()
    await post(http, shopify_order())
    r = await post(http, shopify_order())
    assert r.status_code == 200 and r.json()["changes"] == []
    assert len(website_orders()) == 1 and stock("RT-GRN") == 9 and len(fired) == 1


async def test_paid_and_cancelled_follow_ups_move_the_order_forward_only(http):
    make_source()
    await post(http, shopify_order(payment_gateway_names=["bKash"], id=6001, name="#1002"))
    (o,) = website_orders()
    assert (o["pay_status"], o["pay_method"]) == ("Pending", "bKash (website)")
    db.run("UPDATE orders SET address='Changed by staff, Dhaka 1200' WHERE number=?", [o["number"]])
    r = await post(http, shopify_order(payment_gateway_names=["bKash"], id=6001, name="#1002", financial_status="paid"), topic="orders/paid")
    assert r.json()["changes"] == ["paid"]
    o = website_orders()[0]
    assert (o["pay_status"], o["stage"]) == ("Paid", 1) and len(db.jl(o["times"], [])) == 2 and o["address"] == "Changed by staff, Dhaka 1200"
    # a later "pending" must not undo a payment
    await post(http, shopify_order(payment_gateway_names=["bKash"], id=6001, name="#1002", financial_status="pending"), topic="orders/updated")
    assert website_orders()[0]["pay_status"] == "Paid"
    r = await post(http, shopify_order(payment_gateway_names=["bKash"], id=6001, financial_status="paid", cancelled_at="2026-11-12T10:00:00Z"), topic="orders/cancelled")
    assert r.json()["changes"] == ["cancelled"]
    assert website_orders()[0]["fulfillment"] == "Cancelled" and stock("RT-GRN") == 10 and stock("TB-2L") == 10          # the stock Dakbox took comes back


async def test_an_order_cancelled_before_it_arrived_is_not_created_and_a_shipped_one_is_not_cancelled(http):
    make_source()
    r = await post(http, shopify_order(id=7001, cancelled_at="2026-11-12T10:00:00Z"))
    assert r.json()["ignored"] and website_orders() == []
    await post(http, shopify_order(id=7002))
    db.run("UPDATE orders SET stage=3, fulfillment='In transit' WHERE ext_id='7002'")
    r = await post(http, shopify_order(id=7002, cancelled_at="2026-11-12T10:00:00Z"))
    assert "already shipped" in r.json()["changes"][0] and website_orders()[0]["fulfillment"] == "In transit"


async def test_products_not_in_the_catalogue_still_make_an_order_and_take_no_stock(http):
    make_source()
    p = shopify_order(id=8001, line_items=[{"id": 9, "variant_id": 999, "title": "Mystery Mug", "variant_title": "Blue", "sku": "", "quantity": 2, "price": "500.00", "total_discount": "0.00"}],
                      total_price="1110.00")
    assert (await post(http, p)).status_code == 200
    (o,) = website_orders()
    (it,) = db.jl(o["items"], [])
    assert it["sku"].startswith("WEB-") and it["name"] == "Mystery Mug" and "stock" not in it and store.order_total(o)[1] == 1110
    assert stock("RT-GRN") == 10
    await post(http, {**p, "cancelled_at": "2026-11-12T10:00:00Z"})
    assert stock("RT-GRN") == 10 and stock("TB-2L") == 10          # nothing was taken, so nothing is given back


async def test_a_website_order_is_never_refused_for_stock(http):
    make_source()
    db.run("UPDATE products SET stock=1 WHERE sku='RT-GRN'")
    r = await post(http, shopify_order(id=8100, line_items=[{"id": 1, "variant_id": 111, "title": "Ridgeline Tent 2P", "variant_title": "Green", "sku": "RT-GRN", "quantity": 3, "price": "12500.00", "total_discount": "0"}], total_price="37610.00"))
    assert r.status_code == 200 and r.json()["stockShort"] == ["Ridgeline Tent 2P"]
    assert stock("RT-GRN") == 0                                       # never negative


async def test_the_customer_is_matched_by_phone_not_duplicated(http):
    make_source()
    n = db.get("SELECT COUNT(*) n FROM customers")["n"]
    await post(http, shopify_order(id=8200, shipping_address={"name": "Nusrat J", "phone": "01712-340042", "address1": "Road 5, Dhanmondi", "city": "Dhaka"}))
    assert website_orders()[0]["customer_id"] == "c_nusrat" and db.get("SELECT COUNT(*) n FROM customers")["n"] == n
    await post(http, shopify_order(id=8201, shipping_address={"name": "No Phone", "phone": None, "address1": "", "city": ""}, phone=None, customer={"id": 5, "first_name": "No", "last_name": "Phone"}))
    o = website_orders()[1]
    assert o["ship_phone"] is None and o["address"] == "Not given" and store.customer(o["customer_id"])["name"] == "No Phone"


# ---------------------------------------------------------------- currency
async def test_a_foreign_currency_order_is_not_imported_unless_that_currency_was_accepted(http):
    make_source()
    r = await post(http, shopify_order(currency="USD"))
    assert r.status_code == 200 and "USD" in r.json()["ignored"] and website_orders() == []
    assert "USD" in db.get("SELECT orders_error FROM catalog_sources")["orders_error"]
    make_source(currency="USD")
    assert (await post(http, shopify_order(currency="USD"))).json()["created"]


# ---------------------------------------------------------------- WooCommerce
async def test_a_woocommerce_order(http):
    make_source(kind="woo")
    r = await post(http, woo_order(), kind="woo")
    assert r.status_code == 200 and r.json()["created"]
    (o,) = website_orders()
    assert (o["ext_id"], o["ext_number"], o["zone"], o["shipping"], o["pay_status"], o["pay_method"]) == ("900", "#900", "dhaka", 110, "Pending", "Cash on delivery")
    assert db.jl(o["items"], [])[0]["sku"] == "SJ-1" and stock("SJ-1") == 4
    assert (o["ship_name"], o["ship_phone"]) == ("Woo Buyer", "01955500033") and "Road 2" in o["address"]
    # paid online: date_paid is the signal, not the status "processing"
    await post(http, woo_order(id=901, number="901", payment_method="bkash", payment_method_title="bKash", date_paid="2026-11-12T09:00:00"), kind="woo")
    assert website_orders()[1]["pay_status"] == "Paid" and website_orders()[1]["pay_method"] == "bKash (website)"
    r = await post(http, woo_order(status="cancelled"), kind="woo", topic="order.updated")
    assert r.json()["changes"] == ["cancelled"] and stock("SJ-1") == 4        # 5 - 1 (order 900) - 1 (order 901) + 1 (cancelled 900)


async def test_woocommerce_pings_drafts_and_deletes_are_acknowledged_and_ignored(http):
    make_source(kind="woo")
    ping = b"webhook_id=12"
    r = await post(http, None, kind="woo", raw=ping, headers={"content-type": "application/x-www-form-urlencoded"})
    assert r.status_code == 200 and r.json()["ignored"]
    assert (await post(http, woo_order(status="checkout-draft"), kind="woo")).json()["ignored"] == "draft"
    assert "deleted" in (await post(http, {"id": 900}, kind="woo", topic="order.deleted")).json()["ignored"]
    assert website_orders() == []


# ---------------------------------------------------------------- Dakbox's own format
async def test_any_other_site_can_post_an_order_in_dakbox_format(http):
    make_source(kind="pages", secret="own-secret-123456")
    p = {"id": "A-77", "number": "A-77", "paid": True, "payment_method": "Card", "currency": "BDT", "name": "Generic Gina", "phone": "01855500044", "address": "Road 9, Banani", "city": "Dhaka",
         "shipping": 70, "total": 2970, "lines": [{"sku": "TB-2L", "name": "Trail Bottle 2L", "price": 1450, "qty": 2}]}
    r = await post(http, p, kind="generic", secret="own-secret-123456")
    assert r.status_code == 200 and r.json()["created"]
    (o,) = website_orders()
    assert (o["ext_number"], o["pay_status"], o["pay_method"], o["zone"], o["stage"]) == ("A-77", "Paid", "Card (website)", "dhaka", 1)
    assert db.jl(o["items"], [])[0]["sku"] == "TB-2L" and stock("TB-2L") == 8 and store.order_total(o)[1] == 2970       # matched by SKU
    assert (await post(http, {**p, "cancelled": True}, kind="generic", secret="own-secret-123456")).json()["changes"] == ["cancelled"]


# ---------------------------------------------------------------- who may post
async def test_requests_without_a_valid_signature_are_refused_and_change_nothing(http):
    make_source()
    raw = json.dumps(shopify_order()).encode()
    for h in ({}, {"X-Shopify-Hmac-Sha256": "bm90LWEtc2lnbg=="}, {"X-Shopify-Hmac-Sha256": b64sig(raw, "some-other-secret")}, {"X-WC-Webhook-Signature": ""}):
        r = await http.post("/webhooks/shop/cs_test1", content=raw, headers=h)
        assert r.status_code == 401, h
    r2 = await http.post("/webhooks/shop/cs_test1", content=raw + b" ", headers={"X-Shopify-Hmac-Sha256": b64sig(raw)})
    assert r2.status_code == 401 and website_orders() == []
    assert "wrong signature" in db.get("SELECT orders_error FROM catalog_sources")["orders_error"]


async def test_unknown_addresses_and_shops_with_no_secret_yet_are_closed(http):
    make_source(secret=None)                                          # Shopify, signing secret not pasted yet
    assert (await post(http, shopify_order())).status_code == 404
    assert (await post(http, shopify_order(), sid="cs_nope")).status_code == 404
    assert (await http.post("/webhooks/shop/cs_test1", content=b"{}")).status_code == 404


async def test_oversized_and_unreadable_orders(http, monkeypatch):
    make_source()
    big = b'{"x": "' + b"a" * 1_100_000 + b'"}'
    assert (await post(http, None, raw=big)).status_code == 413
    r = await post(http, {"id": 1, "hello": "world"}, kind="generic")
    assert r.status_code == 200 and "format" in r.json()["ignored"] and "format" in db.get("SELECT orders_error FROM catalog_sources")["orders_error"]
    assert (await post(http, {"id": 1}, topic="products/update")).json()["ignored"].startswith("not an order event")
    assert (await post(http, shopify_order(line_items=[]))).json()["ignored"] == "no items"
    assert website_orders() == []


# ---------------------------------------------------------------- setup screen API
async def test_setup_shows_the_address_and_secret_and_a_new_secret_cuts_the_old_one_off(http):
    make_source(kind="woo", secret=None)
    h = H(await setup_owner(http))
    s = (await http.get("/api/catalog/sources/cs_test1/orders", headers=h)).json()
    assert s["path"] == "/webhooks/shop/cs_test1" and s["url"].endswith("/webhooks/shop/cs_test1") and s["secret"] and s["secretSet"] and s["publicUrlSet"] is False
    assert (await http.get("/api/catalog/sources/cs_test1/orders", headers=h)).json()["secret"] == s["secret"]      # stable until renewed
    assert (await post(http, woo_order(), kind="woo", secret=s["secret"])).status_code == 200
    s2 = (await http.post("/api/catalog/sources/cs_test1/orders/secret", headers=h)).json()
    assert s2["secret"] and s2["secret"] != s["secret"]
    assert (await post(http, woo_order(id=902), kind="woo", secret=s["secret"])).status_code == 401
    assert (await post(http, woo_order(id=902), kind="woo", secret=s2["secret"])).status_code == 200


async def test_shopify_uses_its_own_signing_secret_pasted_by_the_owner_and_never_shown_again(http):
    make_source(secret=None)
    h = H(await setup_owner(http))
    s = (await http.get("/api/catalog/sources/cs_test1/orders", headers=h)).json()
    assert s["secret"] is None and s["secretSet"] is False
    assert (await http.put("/api/catalog/sources/cs_test1/orders", headers=h, json={"signingSecret": "short"})).status_code == 422
    s = (await http.put("/api/catalog/sources/cs_test1/orders", headers=h, json={"signingSecret": "shopify-given-secret-abc"})).json()
    assert s["secret"] is None and s["secretSet"] is True
    assert (await post(http, shopify_order(), secret="shopify-given-secret-abc")).status_code == 200
    assert (await http.post("/api/catalog/sources/cs_test1/orders/secret", headers=h)).status_code == 400
    make_source(kind="woo")
    assert (await http.put("/api/catalog/sources/cs_test1/orders", headers=h, json={"signingSecret": "something-long-enough"})).status_code == 400


async def test_the_customer_sms_for_website_orders_can_be_switched_off_and_only_managers_may_change_setup(http, fired):
    make_source()
    h = H(await setup_owner(http))
    assert (await http.put("/api/catalog/sources/cs_test1/orders", headers=h, json={"notifySms": False})).json()["notifySms"] is False
    await post(http, shopify_order())
    assert fired == []
    src = (await http.get("/api/catalog/sources", headers=h)).json()["items"][0]
    assert src["ordersCount"] == 1 and src["notifySms"] is False and src["secretSet"] is True and "secret" not in src
    agent = H(await member_token(http, (h["Authorization"].split()[1]), "agent"))
    assert (await http.get("/api/catalog/sources/cs_test1/orders", headers=agent)).status_code == 403
    assert (await http.put("/api/catalog/sources/cs_test1/orders", headers=agent, json={"notifySms": True})).status_code == 403
