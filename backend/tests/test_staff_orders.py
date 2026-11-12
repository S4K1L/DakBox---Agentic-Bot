"""Orders made by staff from a cart (Orders, New order; or from a conversation's cart). A person is accountable, so there is no
customer-confirmation step, but prices are live, stock is taken atomically, details are validated and the same order flow follows."""
import httpx
import pytest

from app import checkout, db, store
from app.main import app
from tests.conftest import connect_provider
from tests.test_auth import H, member_token, setup_owner


@pytest.fixture
async def http():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


ADDR = "House 12, Road 4, Zindabazar, Sylhet 3100"


def body(**kw):
    b = {"lines": [{"sku": "NW-TB2-NVY", "qty": 2}], "zone": "out", "name": "Walk In", "phone": "01755500011", "address": ADDR, "method": "cod"}
    b.update(kw)
    return b


def stock(sku):
    return db.get("SELECT stock FROM products WHERE sku=?", [sku])["stock"]


async def owner(http):
    return H(await setup_owner(http))


# ---------------------------------------------------------------- the quote
async def test_the_quote_uses_live_prices_and_delivery_and_flags_stock_problems(http):
    h = await owner(http)
    q = (await http.post("/api/orders/quote", headers=h, json={"lines": [{"sku": "NW-TB2-NVY", "qty": 1}, {"sku": "NW-TB2-NVY", "qty": 2}, {"sku": "NW-RB-BRN-9", "qty": 1}], "zone": "dhaka"})).json()
    assert [(l["sku"], l["qty"]) for l in q["lines"]] == [("NW-TB2-NVY", 3), ("NW-RB-BRN-9", 1)]          # the same product twice becomes one line
    assert q["subtotal"] == 1450 * 3 + 6900 and q["delivery"] == checkout.delivery_charge("dhaka") and q["total"] == q["subtotal"] + q["delivery"] and q["problems"] == []
    assert q["methods"][0]["id"] == "cod"
    out = (await http.post("/api/orders/quote", headers=h, json={"lines": [{"sku": "NW-TB2-NVY", "qty": 7}, {"sku": "NW-AS-GRN-M", "qty": 1}, {"sku": "NOPE", "qty": 1}], "zone": "out"})).json()
    assert {p["code"] for p in out["problems"]} == {"insufficient_stock", "unknown_product"}
    assert next(l for l in out["lines"] if l["sku"] == "NW-TB2-NVY")["ok"] is False and next(l for l in out["lines"] if l["sku"] == "NW-AS-GRN-M")["stock"] == 0
    assert (await http.post("/api/orders/quote", headers=h, json={"lines": [], "zone": "out"})).json()["problems"] == [{"code": "cart_empty"}]
    assert (await http.post("/api/orders/quote", headers=h, json={"lines": [{"sku": "NW-TB2-NVY", "qty": 1}], "zone": "out", "shipping": 0})).json()["delivery"] == 0     # free delivery by hand
    assert (await http.post("/api/orders/quote", headers=h, json={"lines": [{"sku": "NW-TB2-NVY", "qty": 1}], "zone": "mars"})).status_code == 422


# ---------------------------------------------------------------- placing
async def test_a_staff_order_for_a_new_customer(http):
    h = await owner(http)
    before = stock("NW-TB2-NVY")
    r = await http.post("/api/orders", headers=h, json=body())
    assert r.status_code == 200, r.text
    d = r.json()
    o = d["orderView"]
    assert o["source"] == "staff" and o["number"] == d["order"] and o["payment"] == {"status": "Pending", "method": "Cash on delivery", "ref": ""}
    assert o["items"] == [{"sku": "NW-TB2-NVY", "name": "Trail Bottle 2L", "variant": "Navy", "price": 1450, "qty": 2}]
    assert o["zone"] == "out" and o["shipping"] == checkout.delivery_charge("out") and o["total"] == 2900 + o["shipping"]
    assert o["ship"] == {"name": "Walk In", "phone": "01755500011"} and o["address"] == ADDR and o["channel"] == "store"
    assert stock("NW-TB2-NVY") == before - 2
    cust = store.customer(d["customerId"])
    assert cust["name"] == "Walk In" and cust["phone"] == "01755500011"
    assert any(x["number"] == d["order"] for x in (await http.get("/api/orders", headers=h)).json()["items"])
    a = db.get("SELECT * FROM audit WHERE action='order.create'")
    assert a["target"] == d["order"] and "Cash on delivery" in a["detail"]
    nxt = (await http.post("/api/orders", headers=h, json=body(lines=[{"sku": "NW-RB-BRN-9", "qty": 1}]))).json()["order"]
    assert int(nxt.lstrip("#")) == int(d["order"].lstrip("#")) + 1


async def test_an_existing_customer_is_reused_by_id_or_by_phone_and_never_duplicated(http):
    h = await owner(http)
    n = db.get("SELECT COUNT(*) n FROM customers")["n"]
    # by id: name and number default to the saved ones
    r = (await http.post("/api/orders", headers=h, json=body(customerId="c_nusrat", name=None, phone=None))).json()
    assert r["customerId"] == "c_nusrat" and r["orderView"]["ship"] == {"name": "Nusrat Jahan", "phone": "01712340042"}
    # by phone: the saved number is +8801712340042, typed as 01712340042
    r2 = (await http.post("/api/orders", headers=h, json=body(name="Nusrat J", phone="01712-340042"))).json()
    assert r2["customerId"] == "c_nusrat"
    assert db.get("SELECT COUNT(*) n FROM customers")["n"] == n
    assert (await http.post("/api/orders", headers=h, json=body(customerId="c_nobody"))).status_code == 400


async def test_an_order_can_be_made_from_a_conversations_cart_and_empties_it(http):
    h = await owner(http)
    conv = db.get("SELECT * FROM conversations WHERE customer_id='c_nusrat'")
    db.run("UPDATE conversations SET cart=? WHERE id=?", [db.dumps([{"sku": "NW-TB2-NVY", "name": "Trail Bottle 2L", "variant": "Navy", "price": 1450, "qty": 1}]), conv["id"]])
    db.run("UPDATE conversations SET checkout=? WHERE id=?", [db.dumps({"proposal": {"hash": "x", "mid": 1}, "name": "N"}), conv["id"]])
    r = (await http.post("/api/orders", headers=h, json=body(conversationId=conv["id"], name=None, phone=None, lines=[{"sku": "NW-TB2-NVY", "qty": 1}]))).json()
    assert r["customerId"] == "c_nusrat" and r["orderView"]["channel"] == store.channel(conv["channel_id"])["kind"]
    assert db.jl(store.conversation(conv["id"])["cart"], []) == []
    ck = checkout.get(conv["id"])
    assert "proposal" not in ck and ck["last_order"]["number"] == r["order"]          # a summary the assistant was waiting on can no longer be placed
    assert any(f"Order {r['order']} created by" in m["text"] for m in db.all("SELECT text FROM messages WHERE conversation_id=? AND role='event'", [conv["id"]]))
    other = db.get("SELECT * FROM conversations WHERE customer_id='c_rakib'")
    assert (await http.post("/api/orders", headers=h, json=body(conversationId=other["id"], customerId="c_nusrat"))).status_code == 400


async def test_bad_details_and_unavailable_things_are_refused_and_change_nothing(http):
    h = await owner(http)
    before = (stock("NW-TB2-NVY"), db.get("SELECT COUNT(*) n FROM orders")["n"])
    for patch, code in [({"phone": "12345"}, 400), ({"address": "Sylhet"}, 400), ({"name": "x"}, 400), ({"method": "bkash"}, 400),
                        ({"lines": [{"sku": "NW-TB2-NVY", "qty": 99}]}, 409), ({"lines": [{"sku": "NW-AS-GRN-M", "qty": 1}]}, 409), ({"lines": [{"sku": "NOPE", "qty": 1}]}, 409),
                        ({"lines": []}, 409), ({"shipping": -5}, 422), ({"lines": [{"sku": "NW-TB2-NVY", "qty": 0}]}, 422)]:
        r = await http.post("/api/orders", headers=h, json=body(**patch))
        assert r.status_code == code, (patch, r.status_code, r.text)
    assert (stock("NW-TB2-NVY"), db.get("SELECT COUNT(*) n FROM orders")["n"]) == before
    assert db.get("SELECT COUNT(*) n FROM customers WHERE phone='12345'")["n"] == 0


async def test_the_last_unit_can_only_be_sold_once(http):
    h = await owner(http)
    db.run("UPDATE products SET stock=1 WHERE sku='NW-TB2-NVY'")
    assert (await http.post("/api/orders", headers=h, json=body(lines=[{"sku": "NW-TB2-NVY", "qty": 1}]))).status_code == 200
    r = await http.post("/api/orders", headers=h, json=body(lines=[{"sku": "NW-TB2-NVY", "qty": 1}]))
    assert r.status_code == 409 and stock("NW-TB2-NVY") == 0


async def test_delivery_can_be_set_by_hand_and_is_recorded(http):
    h = await owner(http)
    r = (await http.post("/api/orders", headers=h, json=body(shipping=0))).json()
    assert r["orderView"]["shipping"] == 0 and r["orderView"]["total"] == 2900
    assert "delivery charge set by hand" in db.get("SELECT detail FROM audit WHERE action='order.create'")["detail"]


async def test_online_payment_orders_wait_for_a_payment_link_and_unconnected_providers_are_refused(http):
    h = await owner(http)
    assert (await http.post("/api/orders", headers=h, json=body(method="sslcommerz"))).status_code == 400
    connect_provider("sslcommerz")
    r = (await http.post("/api/orders", headers=h, json=body(method="sslcommerz"))).json()
    assert r["needsPaymentLink"] is True and r["orderView"]["payment"]["status"] == "Pending" and "SSLCOMMERZ" in r["orderView"]["payment"]["method"].upper()


async def test_cancelling_a_staff_order_puts_the_stock_back_but_sample_orders_do_not_invent_stock(http):
    h = await owner(http)
    before = stock("NW-TB2-NVY")
    no = (await http.post("/api/orders", headers=h, json=body())).json()["order"]
    assert stock("NW-TB2-NVY") == before - 2
    assert (await http.post(f"/api/orders/{no.replace('#', '%23')}/cancel", headers=h)).status_code == 200
    assert stock("NW-TB2-NVY") == before
    assert (await http.post("/api/orders/%231043/cancel", headers=h)).status_code == 200      # a sample order took no stock, so none comes back
    assert stock("NW-RB-BRN-9") == 41


async def test_who_may_create_orders(http):
    o = await setup_owner(http)
    agent = await member_token(http, o, "agent")
    viewer = await member_token(http, o, "viewer")
    assert (await http.post("/api/orders", headers=H(agent), json=body())).status_code == 200
    assert (await http.post("/api/orders", headers=H(viewer), json=body())).status_code == 403
    assert (await http.post("/api/orders/quote", headers=H(viewer), json={"lines": [], "zone": "out"})).status_code == 403
    assert (await http.post("/api/orders", json=body())).status_code == 401
