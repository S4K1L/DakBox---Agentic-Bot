"""Payments: the rules that keep money honest. Every gateway is a stand-in; what is proven is OUR behaviour."""
import httpx
import pytest

from app import db, payments
from app.main import app
from app.providers import bkash, common as pcommon
from tests.conftest import connect_provider, make_order
from tests.test_auth import H, member_token, setup_owner

TOTAL = 1520  # Trail Bottle 1,450 + 70 shipping


@pytest.fixture
async def http():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def link(http, owner, provider, order="#2001", chat=True):
    r = await http.post(f"/api/orders/{order.replace('#', '%23')}/payment-link", headers=H(owner), json={"provider": provider, "sendInChat": chat})
    return r


def pay_row(order="#2001", provider=None):
    q = "SELECT * FROM payments WHERE order_number=?" + (" AND provider=?" if provider else "") + " ORDER BY created_at DESC"
    return db.get(q, [order] + ([provider] if provider else []))


def order_row(no="#2001"):
    return db.get("SELECT * FROM orders WHERE number=?", [no])


async def get_(http, path, params=None):
    return await http.get(path, params=params)


# ================================================================ SSLCommerz
async def test_sslcommerz_link_payload_matches_the_docs(http, prov):
    owner = await setup_owner(http); connect_provider("sslcommerz"); make_order()
    r = await link(http, owner, "sslcommerz")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["url"].startswith("https://fakegw.test/gw/ssl/") and out["sent"] is True            # the link went to the customer in chat
    form = prov.calls[0]["body"]
    assert prov.calls[0]["path"].endswith("/gwprocess/v4/api.php") and prov.calls[0]["method"] == "POST"
    assert form["total_amount"] == "1520.00" and form["currency"] == "BDT" and form["value_a"] == "#2001" and form["shipping_method"] == "NO"
    assert form["success_url"] == "http://test/pay/sslcommerz/success" and form["ipn_url"] == "http://test/pay/sslcommerz/ipn"
    assert len(form["tran_id"]) <= 30 and pay_row()["status"] == "pending"


async def test_a_verified_payment_marks_the_order_paid_exactly_once(http, prov):
    owner = await setup_owner(http); connect_provider("sslcommerz"); make_order()
    await link(http, owner, "sslcommerz")
    tran = pay_row()["tran_id"]
    form = prov.ssl_pay(tran)
    r = await http.post("/pay/sslcommerz/success", data=form)
    assert r.status_code == 303 and "s=paid" in r.headers["location"]
    o = order_row()
    assert o["pay_status"] == "Paid" and o["pay_method"] == "SSLCOMMERZ" and o["pay_ref"] == form["bank_tran_id"]
    p = pay_row()
    assert p["status"] == "paid" and p["trx_id"] == form["bank_tran_id"]
    # the IPN arrives afterwards, twice: nothing changes
    for _ in range(2):
        assert (await http.post("/pay/sslcommerz/ipn", data=form)).text == "OK"
    assert pay_row()["status"] == "paid" and db.get("SELECT COUNT(*) n FROM payments WHERE order_number='#2001'")["n"] == 1
    log = [x for x in db.jl(order_row()["log"], []) if "received via" in x["x"]]
    assert len(log) == 1


async def test_a_forged_success_does_not_pay_the_order(http, prov):
    owner = await setup_owner(http); connect_provider("sslcommerz"); make_order()
    await link(http, owner, "sslcommerz")
    tran = pay_row()["tran_id"]
    # someone opens the success URL by hand with an invented val_id
    r = await http.post("/pay/sslcommerz/success", data={"tran_id": tran, "val_id": "INVENTED", "status": "VALID", "amount": "1520.00"})
    assert order_row()["pay_status"] != "Paid" and pay_row()["status"] == "pending"
    # and again without any val_id: the gateway has no paid transaction for it
    await http.get("/pay/sslcommerz/success", params={"tran_id": tran, "status": "VALID"})
    assert order_row()["pay_status"] != "Paid"


async def test_an_amount_that_does_not_match_is_not_counted(http, prov):
    owner = await setup_owner(http); connect_provider("sslcommerz"); make_order()
    await link(http, owner, "sslcommerz")
    form = prov.ssl_pay(pay_row()["tran_id"], amount=10.0)           # the gateway says ৳10 was paid for a ৳1,520 order
    await http.post("/pay/sslcommerz/success", data=form)
    assert order_row()["pay_status"] != "Paid"
    p = pay_row()
    assert p["status"] == "mismatch" and "amount" in p["note"]


async def test_a_risky_payment_is_held_for_a_person(http, prov):
    owner = await setup_owner(http); connect_provider("sslcommerz"); make_order()
    await link(http, owner, "sslcommerz")
    await http.post("/pay/sslcommerz/success", data=prov.ssl_pay(pay_row()["tran_id"], risk="1"))
    assert pay_row()["status"] == "review" and order_row()["pay_status"] != "Paid"


async def test_paying_twice_is_flagged_not_absorbed(http, prov):
    owner = await setup_owner(http); connect_provider("sslcommerz"); connect_provider("bkash"); make_order()
    await link(http, owner, "sslcommerz")
    await http.post("/pay/sslcommerz/success", data=prov.ssl_pay(pay_row("#2001", "sslcommerz")["tran_id"]))
    assert order_row()["pay_status"] == "Paid"
    # a second payment attempt completes later (an older link the customer still had)
    db.run("INSERT INTO payments(id,order_number,provider,amount,tran_id,status,created_at,mode,provider_ref) VALUES('pay_x','#2001','aamarpay',1520,'DBX2001-late','pending',?,'sandbox',NULL)", [db.now()])
    connect_provider("aamarpay")
    prov.aam_txns["DBX2001-late"] = {"amount": 1520.0, "pay_status": "", "pg": None, "urls": {}}
    form = prov.aam_pay("DBX2001-late")
    await http.post("/pay/aamarpay/success", data=form)
    assert db.get("SELECT status FROM payments WHERE id='pay_x'")["status"] == "duplicate_paid"
    assert db.get("SELECT COUNT(*) n FROM payments WHERE order_number='#2001' AND status='paid'")["n"] == 1


async def test_cancelling_leaves_the_order_unpaid(http, prov):
    owner = await setup_owner(http); connect_provider("sslcommerz"); make_order()
    await link(http, owner, "sslcommerz")
    r = await http.post("/pay/sslcommerz/cancel", data={"tran_id": pay_row()["tran_id"]})
    assert "s=cancelled" in r.headers["location"] and pay_row()["status"] == "cancelled" and order_row()["pay_status"] == "Pending"


async def test_one_open_link_per_order_and_provider(http, prov):
    owner = await setup_owner(http); connect_provider("sslcommerz"); make_order()
    a = (await link(http, owner, "sslcommerz")).json()
    b = (await link(http, owner, "sslcommerz")).json()
    assert b["reused"] is True and a["url"] == b["url"] and len([c for c in prov.calls if c["path"].endswith("api.php")]) == 1


async def test_ssl_full_and_partial_refunds_and_guards(http, prov):
    owner = await setup_owner(http); connect_provider("sslcommerz"); make_order()
    await link(http, owner, "sslcommerz")
    await http.post("/pay/sslcommerz/success", data=prov.ssl_pay(pay_row()["tran_id"]))
    no = "%232001"
    r = await http.post(f"/api/orders/{no}/refund", headers=H(owner), json={"amount": 500, "reason": "damaged lid"})
    assert r.status_code == 200 and r.json()["status"] == "done"
    assert pay_row()["status"] == "partially_refunded" and pay_row()["refunded"] == 500 and order_row()["pay_status"] == "Paid"
    call = [c for c in prov.calls if "refund_amount" in c["query"]][0]["query"]
    assert call["refund_amount"] == "500.00" and call["bank_tran_id"] == pay_row()["trx_id"] and call["refund_trans_id"].startswith("rf_")
    again = await http.post(f"/api/orders/{no}/refund", headers=H(owner), json={"amount": 500})
    assert again.status_code == 409 and "just requested" in again.json()["detail"]             # double click guard
    assert (await http.post(f"/api/orders/{no}/refund", headers=H(owner), json={"amount": 5000})).status_code == 400   # more than is left
    rest = await http.post(f"/api/orders/{no}/refund", headers=H(owner), json={"amount": 1020})
    assert rest.status_code == 200 and pay_row()["status"] == "refunded" and order_row()["pay_status"] == "Refunded"


async def test_ssl_refund_in_progress_is_not_counted_until_confirmed(http, prov):
    owner = await setup_owner(http); connect_provider("sslcommerz"); make_order()
    await link(http, owner, "sslcommerz")
    await http.post("/pay/sslcommerz/success", data=prov.ssl_pay(pay_row()["tran_id"]))
    prov.ssl_refund_mode = "processing"
    r = (await http.post("/api/orders/%232001/refund", headers=H(owner), json={})).json()
    assert r["status"] == "processing" and order_row()["pay_status"] == "Paid" and pay_row()["refunded"] == 0
    for ref in prov.ssl_refunds.values():
        ref["state"] = "refunded"
    chk = (await http.post(f"/api/refunds/{r['refundId']}/check", headers=H(owner))).json()
    assert chk["status"] == "done" and order_row()["pay_status"] == "Refunded"


async def test_a_declined_refund_leaves_everything_as_it_was(http, prov):
    owner = await setup_owner(http); connect_provider("sslcommerz"); make_order()
    await link(http, owner, "sslcommerz")
    await http.post("/pay/sslcommerz/success", data=prov.ssl_pay(pay_row()["tran_id"]))
    prov.ssl_refund_mode = "fail"
    r = (await http.post("/api/orders/%232001/refund", headers=H(owner), json={})).json()
    assert r["status"] == "failed" and "declined" in r["message"] and order_row()["pay_status"] == "Paid" and pay_row()["refunded"] == 0


# ================================================================ bKash
async def test_bkash_create_payload_and_token_cache(http, prov):
    owner = await setup_owner(http); connect_provider("bkash"); make_order(); make_order("#2002")
    await link(http, owner, "bkash")
    create = [c for c in prov.calls if c["path"].endswith("/payment/create")][0]
    assert create["path"] == "/v2/tokenized-checkout/payment/create" and create["headers"]["x-app-key"] == "appkey"
    assert create["body"] == {"payerReference": create["body"]["payerReference"], "callbackURL": "http://test/pay/bkash/callback", "amount": "1520.00", "currency": "BDT", "intent": "sale", "merchantInvoiceNumber": pay_row()["tran_id"]}
    await link(http, owner, "bkash", "#2002")
    assert len([c for c in prov.calls if c["path"].endswith("/grant-token")]) == 1               # the token was reused: bKash allows two grants an hour


async def test_bkash_grant_limit_is_respected(http, prov):
    connect_provider("bkash")
    c, cfg = pcommon.creds("bkash"), pcommon.config("bkash")
    await bkash.token("bkash", c, cfg)
    db.set_setting("bkash_token_bkash", None)
    await bkash.token("bkash", c, cfg)
    db.set_setting("bkash_token_bkash", None)
    with pytest.raises(pcommon.ProviderError) as e:
        await bkash.token("bkash", c, cfg)
    assert "two token requests" in e.value.message and len([c for c in prov.calls if c["path"].endswith("/grant-token")]) == 2


async def test_bkash_success_callback_executes_once_then_verifies(http, prov):
    owner = await setup_owner(http); connect_provider("bkash"); make_order()
    await link(http, owner, "bkash")
    pid = pay_row()["provider_ref"]
    cb = prov.bk_pay(pid).replace("http://test", "")
    r = await http.get(cb)
    assert r.status_code == 303 and "s=paid" in r.headers["location"]
    assert order_row()["pay_status"] == "Paid" and order_row()["pay_method"] == "bKash" and pay_row()["trx_id"]
    await http.get(cb)                                                  # the customer reloads the callback
    assert len([c for c in prov.calls if c["path"].endswith("/payment/execute")]) == 1
    assert [c for c in prov.calls if c["path"].endswith("/query/payment")]


async def test_bkash_callback_without_customer_approval_pays_nothing(http, prov):
    owner = await setup_owner(http); connect_provider("bkash"); make_order()
    await link(http, owner, "bkash")
    pid = pay_row()["provider_ref"]
    # a forged "success" redirect: the customer never approved in the bKash app
    r = await http.get("/pay/bkash/callback", params={"paymentID": pid, "status": "success", "signature": "x"})
    assert order_row()["pay_status"] != "Paid" and pay_row()["status"] in ("pending", "created")


async def test_bkash_failure_and_cancel_callbacks(http, prov):
    owner = await setup_owner(http); connect_provider("bkash"); make_order()
    await link(http, owner, "bkash")
    pid = pay_row()["provider_ref"]
    r = await http.get("/pay/bkash/callback", params={"paymentID": pid, "status": "cancel"})
    assert "s=cancelled" in r.headers["location"] and pay_row()["status"] == "cancelled" and not [c for c in prov.calls if c["path"].endswith("/payment/execute")]


async def test_bkash_falls_back_to_bearer_when_the_bare_token_is_refused(http, prov):
    owner = await setup_owner(http); connect_provider("bkash"); make_order()
    prov.bk_bearer_only = True
    assert (await link(http, owner, "bkash")).status_code == 200


async def test_bkash_refund_and_the_ten_minute_duplicate_rule(http, prov):
    owner = await setup_owner(http); connect_provider("bkash"); make_order()
    await link(http, owner, "bkash")
    await http.get(prov.bk_pay(pay_row()["provider_ref"]).replace("http://test", ""))
    r = await http.post("/api/orders/%232001/refund", headers=H(owner), json={"amount": 520, "reason": "wrong size"})
    assert r.status_code == 200 and r.json()["status"] == "done"
    body = [c for c in prov.calls if c["path"].endswith("/refund/payment/transaction")][0]["body"]
    assert body["refundAmount"] == "520.00" and body["trxId"] == pay_row()["trx_id"] and body["paymentId"] == pay_row()["provider_ref"] and body["sku"] == "#2001"
    assert (await http.post("/api/orders/%232001/refund", headers=H(owner), json={"amount": 520})).status_code == 409
    assert pay_row()["refunded"] == 520 and order_row()["pay_status"] == "Paid"


async def test_an_unknown_refund_outcome_is_never_counted_as_refunded(http, prov):
    owner = await setup_owner(http); connect_provider("bkash"); make_order()
    await link(http, owner, "bkash")
    await http.get(prov.bk_pay(pay_row()["provider_ref"]).replace("http://test", ""))
    prov.bk_refund_timeout = True                                      # bKash did the refund but never answered us
    r = (await http.post("/api/orders/%232001/refund", headers=H(owner), json={})).json()
    assert r["status"] == "unknown" and pay_row()["refunded"] == 0 and order_row()["pay_status"] == "Paid"
    chk = (await http.post(f"/api/refunds/{r['refundId']}/check", headers=H(owner))).json()   # ask bKash what happened
    assert chk["status"] == "done" and order_row()["pay_status"] == "Refunded"


# ================================================================ aamarPay
async def test_aamarpay_flow_and_manual_refund(http, prov):
    owner = await setup_owner(http); connect_provider("aamarpay"); make_order()
    await link(http, owner, "aamarpay")
    init = prov.calls[0]["body"]
    assert prov.calls[0]["path"] == "/jsonpost.php" and init["type"] == "json" and init["amount"] == "1520.00" and init["success_url"] == "http://test/pay/aamarpay/success"
    tran = pay_row()["tran_id"]
    await http.post("/pay/aamarpay/success", data={"mer_txnid": tran, "pay_status": "Successful"})      # claims success, but nothing was paid yet
    assert order_row()["pay_status"] != "Paid"
    form = prov.aam_pay(tran)
    r = await http.post("/pay/aamarpay/success", data=form)
    assert "s=paid" in r.headers["location"] and order_row()["pay_status"] == "Paid" and pay_row()["trx_id"] == form["pg_txnid"]
    no = "%232001"
    refused = await http.post(f"/api/orders/{no}/refund", headers=H(owner), json={})
    assert refused.status_code == 409 and "no refund API" in refused.json()["detail"]
    ok = await http.post(f"/api/orders/{no}/refund", headers=H(owner), json={"manual": True, "reason": "refunded in the panel"})
    assert ok.status_code == 200 and ok.json()["manual"] is True and order_row()["pay_status"] == "Refunded"
    assert db.get("SELECT manual FROM payment_refunds").get("manual") if False else db.get("SELECT manual FROM payment_refunds")["manual"] == 1


async def test_aamarpay_amount_mismatch_is_not_counted(http, prov):
    owner = await setup_owner(http); connect_provider("aamarpay"); make_order()
    await link(http, owner, "aamarpay")
    tran = pay_row()["tran_id"]
    await http.post("/pay/aamarpay/success", data=prov.aam_pay(tran, amount=15.0))
    assert order_row()["pay_status"] != "Paid" and pay_row()["status"] == "mismatch"


# ================================================================ rules that hold for every provider
async def test_you_cannot_get_a_link_for_a_paid_order_or_an_unconnected_provider(http, prov):
    owner = await setup_owner(http); make_order(); make_order("#2003", pay="Paid")
    assert (await link(http, owner, "bkash")).status_code == 409                    # not connected
    connect_provider("bkash")
    assert (await link(http, owner, "bkash", "#2003")).status_code == 409           # already paid
    assert (await link(http, owner, "nagad")).status_code == 400                    # not a provider we support


async def test_live_mode_refuses_a_non_https_public_url(http, prov):
    owner = await setup_owner(http); connect_provider("sslcommerz", mode="live"); make_order()
    assert (await link(http, owner, "sslcommerz")).status_code == 400


async def test_roles_on_payments(http, prov):
    owner = await setup_owner(http); connect_provider("sslcommerz"); make_order()
    agent = await member_token(http, owner, "agent")
    viewer = await member_token(http, owner, "viewer")
    assert (await link(http, agent, "sslcommerz")).status_code == 200                 # agents may send payment links
    await http.post("/pay/sslcommerz/success", data=prov.ssl_pay(pay_row()["tran_id"]))
    assert (await http.post("/api/orders/%232001/refund", headers=H(agent), json={})).status_code == 403    # but not move money back
    assert (await link(http, viewer, "sslcommerz")).status_code == 403
    assert (await http.post("/api/orders/%232001/refund", headers=H(owner), json={})).status_code == 200


async def test_secrets_never_leave_the_server(http, prov):
    owner = await setup_owner(http)
    for pid in ("sslcommerz", "bkash", "aamarpay"):
        connect_provider(pid)
    make_order()
    await link(http, owner, "sslcommerz")
    blob = (await http.get("/api/providers", headers=H(owner))).text + (await http.get("/api/orders", headers=H(owner))).text
    for secret in ("testpass@ssl", "appsecret", "testkey", "sfsecret"):
        assert secret not in blob
    stored = " ".join(r["credentials"] or "" for r in db.all("SELECT credentials FROM integrations"))
    assert "testpass" not in stored and "appsecret" not in stored                        # encrypted at rest


async def test_callbacks_for_unknown_payments_are_harmless(http, prov):
    for url in ("/pay/sslcommerz/success", "/pay/aamarpay/ipn", "/pay/bkash/callback"):
        r = await http.post(url, data={"tran_id": "nope", "mer_txnid": "nope", "paymentID": "nope"}) if "bkash" not in url else await http.get(url, params={"paymentID": "nope", "status": "success"})
        assert r.status_code in (200, 303)
    assert (await http.get("/pay/done", params={"s": "<script>", "o": "<img onerror=1>"})).status_code == 200
    assert "<script>" not in (await http.get("/pay/done", params={"s": "<script>", "o": "<b>"})).text
    assert (await http.post("/pay/evil/success")).status_code == 404
