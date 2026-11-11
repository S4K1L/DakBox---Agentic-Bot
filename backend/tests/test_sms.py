"""Order SMS: provider calls (against stand-ins built from the public API pages), and Dakbox's own safety rules."""
from datetime import datetime, timezone

import httpx
import pytest

from app import couriers, db, payments, sms, store
from app.main import app
from app.providers import alphasms, sslwireless
from app.providers.common import ProviderError, Verified
from tests.conftest import connect_provider, make_order
from tests.test_auth import H, member_token, setup_owner


@pytest.fixture
async def http():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture(autouse=True)
def real_clock():
    sms._now = lambda: datetime.now(timezone.utc)
    yield
    sms._now = lambda: datetime.now(timezone.utc)


def at(y, m, d, hh, mm=0):
    """A clock for sms: given in Bangladesh time (UTC+6)."""
    from datetime import timedelta
    t = datetime(y, m, d, hh, mm, tzinfo=timezone.utc) - timedelta(hours=6)
    sms._now = lambda: t


def order_with_phone(no="#2001", phone="+8801712345678", lang="en", **kw):
    db.run("UPDATE customers SET phone=?, lang=? WHERE id='c_sadia'", [phone, lang])
    return make_order(no, **kw)


def rows():
    return [dict(r) for r in db.all("SELECT * FROM sms_messages ORDER BY created_at, rowid")]


def log_of(no="#2001"):
    return db.jl(store.order(no)["log"], [])


# ---------------------------------------------------------------- measuring
def test_part_counting_follows_the_standard_rules():
    assert sms.measure("a" * 160) == ("GSM-7", 160, 1)
    assert sms.measure("a" * 161) == ("GSM-7", 161, 2)
    assert sms.measure("a" * 306)[2] == 2 and sms.measure("a" * 307)[2] == 3
    assert sms.measure("[" * 81)[2] == 2                      # [ costs two units
    assert sms.measure("অ" * 70) == ("Unicode", 70, 1)
    assert sms.measure("অ" * 71)[2] == 2
    assert sms.measure("Tk ৳")[0] == "Unicode"                 # the taka sign is not in the plain alphabet


def test_phone_numbers_are_normalised_or_refused():
    for raw in ("01712345678", "+8801712345678", "8801712345678", "017 1234-5678"):
        assert alphasms.msisdn(raw) == sslwireless.msisdn(raw) == "8801712345678"
    for bad in ("", "12345", "01212345678", "0171234567", "+4412345678901"):
        with pytest.raises(ProviderError):
            alphasms.msisdn(bad)


def test_messages_are_built_from_order_facts_in_the_customers_language():
    o = order_with_phone(lang="bn", method="Cash on delivery")
    cust = store.customer("c_sadia")
    bn = sms.compose("shipped", store.order(o), cust, tracking="TRK1", cod=3030)
    assert "#2001" in bn and "TRK1" in bn and "৳3,030" in bn
    db.run("UPDATE customers SET lang='en' WHERE id='c_sadia'")
    en = sms.compose("shipped", store.order(o), store.customer("c_sadia"), tracking="TRK1", cod=3030)
    assert "Tk 3,030" in en and sms.measure(en)[0] == "GSM-7"  # plain letters: cheaper than Bangla
    assert "pay on delivery" in en and "keep" in en.lower()
    prepaid = sms.compose("shipped", store.order(o), store.customer("c_sadia"), tracking="TRK1", cod=0)
    assert "Tk" not in prepaid


# ---------------------------------------------------------------- nothing connected / switched off
async def test_nothing_is_sent_without_a_connected_provider(prov):
    order_with_phone()
    r = await sms.notify("#2001", "shipped", tracking="TRK1")
    assert r["status"] == "not_sent" and rows() == [] and prov.calls == []
    assert "Not sent" in log_of()[0]["s"]


async def test_an_event_switched_off_in_notifications_sends_nothing(prov):
    connect_provider("alphasms")
    order_with_phone()
    db.set_setting("notifications", [{"e": "Shipped", "sms": 0, "wa": 0, "em": 0}])
    assert (await sms.notify("#2001", "shipped"))["status"] == "off"
    assert prov.alpha_sent == [] and rows() == []


async def test_a_customer_without_a_valid_mobile_number_is_not_texted(prov):
    connect_provider("alphasms")
    order_with_phone(phone=None)
    r = await sms.notify("#2001", "shipped")
    assert r["status"] == "not_sent" and prov.alpha_sent == [] and "valid mobile" in log_of()[0]["s"]


# ---------------------------------------------------------------- Alpha SMS
async def test_alpha_sms_sends_one_message_with_the_documented_fields(prov):
    connect_provider("alphasms")
    order_with_phone()
    r = await sms.notify("#2001", "shipped", tracking="TRK9", cod=0)
    assert r["status"] == "queued"
    call = next(c for c in prov.calls if c["path"] == "/sendsms")
    assert call["method"] == "POST" and set(call["body"]) == {"api_key", "msg", "to"} and call["body"]["to"] == "8801712345678"
    row = rows()[0]
    assert row["status"] == "Accepted" and row["provider_ref"] == "7001" and row["provider"] == "alphasms"
    assert log_of()[0]["s"] == "Accepted by Alpha SMS" and log_of()[0]["c"] == "sms"


async def test_the_same_event_never_texts_twice(prov):
    connect_provider("alphasms")
    order_with_phone()
    await sms.notify("#2001", "shipped", key="shipped:#2001")
    again = await sms.notify("#2001", "shipped", key="shipped:#2001")
    assert again["status"] == "duplicate" and len(prov.alpha_sent) == 1 and len(rows()) == 1


async def test_alpha_connect_verifies_the_key_by_balance_and_never_echoes_it(http, prov):
    owner = await setup_owner(http)
    bad = await http.post("/api/providers/alphasms/connect", headers=H(owner), json={"values": {"api_key": "nope"}})
    assert bad.status_code == 400 and "API key" in bad.json()["detail"] and not db.get("SELECT live FROM integrations WHERE id='alphasms'")["live"]
    ok = await http.post("/api/providers/alphasms/connect", headers=H(owner), json={"values": {"api_key": "alpha-key-0001", "sender_id": ""}})
    assert ok.status_code == 200 and ok.json()["live"] and "balance" in ok.json()["verifiedName"]
    assert "alpha-key-0001" not in ok.text and "alpha-key-0001" not in db.get("SELECT credentials FROM integrations WHERE id='alphasms'")["credentials"]
    assert prov.alpha_sent == []                                         # connecting sent nothing


async def test_alpha_out_of_balance_fails_clearly_and_resend_works_after_top_up(prov):
    connect_provider("alphasms")
    order_with_phone()
    prov.alpha_balance = 0
    r = await sms.notify("#2001", "shipped")
    row = rows()[0]
    assert row["status"] == "Failed" and "balance" in row["error"] and "Failed" in log_of()[0]["s"]
    assert "balance" in db.get("SELECT last_error FROM integrations WHERE id='alphasms'")["last_error"]
    prov.alpha_balance = 50
    again = await sms.resend(row["id"], "Farhana")
    assert again["status"] == "queued" and rows()[-1]["status"] == "Accepted" and rows()[-1]["manual"] == 1


async def test_a_rejected_key_fails_closed_until_checked_again(prov):
    connect_provider("alphasms")
    order_with_phone()
    prov.alpha_error = 405
    await sms.notify("#2001", "shipped", key="a")
    assert rows()[0]["status"] == "Failed"
    assert db.get("SELECT status FROM integrations WHERE id='alphasms'")["status"] == "warn"
    prov.alpha_error = None
    await sms.notify("#2001", "delivered", key="b")                      # provider is not "ok" any more: nothing is sent
    assert len(prov.alpha_sent) == 0 and sms.live_provider() is None


async def test_alpha_timeout_after_processing_is_unknown_and_never_retried(prov):
    connect_provider("alphasms")
    order_with_phone()
    prov.sms_net = "after"
    await sms.notify("#2001", "shipped")
    assert len(prov.alpha_sent) == 1 and rows()[0]["status"] == "Unknown"       # no client reference: a retry could text twice
    assert "Unknown" in log_of()[0]["s"] and sms.view(db.get("SELECT * FROM sms_messages"))["canResend"]


async def test_delivery_reports_update_status_and_unknown_words_are_not_called_delivered(prov):
    connect_provider("alphasms")
    order_with_phone()
    await sms.notify("#2001", "shipped", key="1")
    await sms.notify("#2001", "delivered", key="2")
    await sms.notify("#2001", "refund", key="3", amount=500)
    prov.alpha_set("7001", "Delivered")
    prov.alpha_set("7002", "Queued at operator")
    prov.alpha_set("7003", "Failed")
    assert await sms.poll_reports() == 2
    st = {r["provider_ref"]: r["status"] for r in rows()}
    assert st == {"7001": "Delivered", "7002": "Accepted", "7003": "Failed"}
    assert "Failed" in next(l["s"] for l in log_of() if l.get("m") == rows()[2]["id"])
    assert await sms.poll_reports() == 0                                  # cooled down, and finished ones are not asked again


# ---------------------------------------------------------------- SSL Wireless
async def test_ssl_wireless_sends_the_documented_json_with_a_client_reference(prov):
    connect_provider("sslwireless")
    order_with_phone()
    await sms.notify("#2001", "delivered")
    call = next(c for c in prov.calls if c["path"].endswith("/send-sms"))
    assert call["method"] == "POST" and set(call["body"]) == {"api_token", "sid", "msisdn", "sms", "csms_id"}
    assert call["body"]["msisdn"] == "8801712345678" and len(call["body"]["csms_id"]) <= 20 and call["body"]["csms_id"].isalnum()
    r = rows()[0]
    assert r["status"] == "Accepted" and r["provider_ref"] == "SSLW000001" and log_of()[0]["s"] == "Accepted by SSL Wireless"
    assert await sms.poll_reports() == 0 and rows()[0]["status"] == "Accepted"  # no delivery report is documented: never "Delivered"


async def test_ssl_wireless_timeout_is_retried_once_with_the_same_reference_and_sent_once(prov):
    connect_provider("sslwireless")
    order_with_phone()
    prov.sms_net = "after"                                                 # first attempt arrives, the answer is lost
    await sms.notify("#2001", "shipped")
    assert len(prov.sslw_sent) == 1 and rows()[0]["status"] == "Accepted"
    sends = [c for c in prov.calls if c["path"].endswith("/send-sms")]
    assert len(sends) == 2 and sends[0]["body"]["csms_id"] == sends[1]["body"]["csms_id"]


async def test_ssl_wireless_request_that_never_arrived_is_retried_and_delivered(prov):
    connect_provider("sslwireless")
    order_with_phone()
    prov.sms_net = "before"
    await sms.notify("#2001", "shipped")
    assert len(prov.sslw_sent) == 1 and rows()[0]["status"] == "Accepted"


async def test_ssl_wireless_ip_not_whitelisted_is_explained(prov):
    connect_provider("sslwireless")
    order_with_phone()
    prov.sslw_error = 4003
    await sms.notify("#2001", "shipped")
    r = rows()[0]
    assert r["status"] == "Failed" and "whitelist" in r["error"]
    assert db.get("SELECT status FROM integrations WHERE id='sslwireless'")["status"] == "warn"


async def test_ssl_wireless_connect_needs_a_real_test_sms(http, prov):
    owner = await setup_owner(http)
    creds = {"api_token": "ssl-token-0001", "sid": "NORTHWIND"}
    none = await http.post("/api/providers/sslwireless/connect", headers=H(owner), json={"values": creds})
    assert none.status_code == 400 and "test SMS" in none.json()["detail"] and prov.sslw_sent == []
    bad = await http.post("/api/providers/sslwireless/connect", headers=H(owner), json={"values": {**creds, "api_token": "wrong"}, "config": {"test_number": "01712345678"}})
    assert bad.status_code == 400 and "token" in bad.json()["detail"] and not db.get("SELECT live FROM integrations WHERE id='sslwireless'")["live"]
    ok = await http.post("/api/providers/sslwireless/connect", headers=H(owner), json={"values": creds, "config": {"test_number": "01712345678"}})
    assert ok.status_code == 200 and ok.json()["live"] and ok.json()["hasReport"] is False
    assert len(prov.sslw_sent) == 1 and prov.sslw_sent[0]["to"] == "8801712345678" and "ssl-token-0001" not in ok.text
    assert "01712345678" not in db.get("SELECT config FROM integrations WHERE id='sslwireless'")["config"]   # the test number is not kept
    chk = await http.post("/api/providers/sslwireless/check", headers=H(owner))
    assert "test SMS" in chk.json()["message"] and len(prov.sslw_sent) == 1  # re-checking never texts anyone


# ---------------------------------------------------------------- quiet hours, caps, crashes
async def test_automatic_messages_wait_for_morning_and_people_are_not_held(prov):
    connect_provider("alphasms")
    db.set_setting("sms_settings", {"quiet": True})
    order_with_phone()
    at(2026, 11, 11, 23, 30)
    r = await sms.notify("#2001", "shipped")
    assert r["message"]["status"] == "Queued" and prov.alpha_sent == []
    assert r["message"]["sendAfter"] == "2026-11-12T02:00:00.000Z" and log_of()[0]["s"] == "Waiting for 08:00"
    assert await sms.process_due() == 0 and prov.alpha_sent == []
    manual = await sms.submit("#2001", "status", "Your order #2001 is on the way.", manual=True, by="Farhana")
    assert manual["message"]["status"] == "Accepted"                       # a person pressing Send is not held
    at(2026, 11, 12, 8, 1)
    assert await sms.process_due() == 1 and len(prov.alpha_sent) == 2
    assert {r["status"] for r in rows()} == {"Accepted"}


async def test_daytime_is_not_quiet_and_the_window_can_be_turned_off(prov):
    db.set_setting("sms_settings", {"quiet": True})
    at(2026, 11, 11, 14)
    assert sms.next_allowed() == sms._now()
    at(2026, 11, 11, 7, 59)
    assert sms.next_allowed().astimezone(sms.BD).hour == 8
    at(2026, 11, 11, 3, 0)
    assert sms.next_allowed().astimezone(sms.BD).day == 11 and sms.next_allowed().astimezone(sms.BD).hour == 8
    db.set_setting("sms_settings", {"quiet": False})
    at(2026, 11, 11, 23)
    assert sms.next_allowed() == sms._now()


async def test_a_number_cannot_be_texted_without_limit(prov):
    connect_provider("alphasms")
    db.set_setting("sms_settings", {"quiet": False, "perNumberDay": 2})
    order_with_phone()
    await sms.notify("#2001", "shipped", key="1")
    await sms.notify("#2001", "delivered", key="2")
    r = await sms.notify("#2001", "refund", key="3", amount=100)
    assert r["status"] == "held" and len(prov.alpha_sent) == 2 and "2 messages" in r["error"] and "Held" in log_of()[0]["s"]


async def test_the_daily_limit_applies_across_customers(prov):
    connect_provider("alphasms")
    db.set_setting("sms_settings", {"quiet": False, "perDay": 1})
    order_with_phone()
    await sms.notify("#2001", "shipped", key="1")
    r = await sms.notify("#2001", "delivered", key="2")
    assert r["status"] == "held" and "daily limit" in r["error"]


async def test_a_message_stuck_while_sending_becomes_unknown_and_is_never_sent_again(prov):
    connect_provider("alphasms")
    order_with_phone()
    db.run("INSERT INTO sms_messages(id,order_number,event,to_phone,body,encoding,parts,provider,status,created_at,send_after,updated_at) VALUES('sm_stuck','#2001','shipped','8801712345678','x','GSM-7',1,'alphasms','Sending',?,?,?)",
           ["2020-01-01T00:00:00.000Z", "2020-01-01T00:00:00.000Z", "2020-01-01T00:00:00.000Z"])
    await sms.process_due()
    assert db.get("SELECT status FROM sms_messages WHERE id='sm_stuck'")["status"] == "Unknown" and prov.alpha_sent == []


async def test_two_workers_cannot_send_the_same_message(prov):
    import asyncio
    connect_provider("alphasms")
    db.set_setting("sms_settings", {"quiet": True})
    order_with_phone()
    at(2026, 11, 11, 23)
    await sms.notify("#2001", "shipped")
    mid = rows()[0]["id"]
    at(2026, 11, 12, 9)
    await asyncio.gather(sms.deliver(mid), sms.deliver(mid), sms.deliver(mid))
    assert len(prov.alpha_sent) == 1


# ---------------------------------------------------------------- wired into orders
async def test_booking_a_parcel_texts_the_customer_once_with_tracking_and_cod(prov):
    connect_provider("alphasms")
    connect_provider("steadfast")
    order_with_phone(method="Cash on delivery", pay="Pending")
    await couriers.book("#2001", "steadfast", "Farhana", couriers.cod_amount(store.order("#2001")))
    await sms.drain()
    assert len(prov.alpha_sent) == 1
    t = prov.alpha_sent[0]["text"]
    assert "#2001" in t and "TRK1424001" in t and "Tk" in t


async def test_delivery_and_refund_and_failed_payment_each_text_once(prov):
    connect_provider("alphasms")
    connect_provider("steadfast")
    connect_provider("sslcommerz")
    order_with_phone(method="Cash on delivery", pay="Pending")
    await couriers.book("#2001", "steadfast", "Farhana", couriers.cod_amount(store.order("#2001")))
    await sms.drain()
    prov.sf_set("1424001", "delivered")
    await couriers.track("#2001")
    await couriers.track("#2001")
    await sms.drain()
    texts = [s["text"] for s in prov.alpha_sent]
    assert len(texts) == 2 and "delivered" in texts[1].lower()
    # a gateway-failed payment on another order
    order_with_phone("#2002", method="bKash", pay="Pending")
    db.run("INSERT INTO payments(id,order_number,provider,amount,tran_id,status,created_at) VALUES('pay_x','#2002','sslcommerz',3030,'DBX2002-aa','pending',?)", [db.now()])
    payments.settle("pay_x", Verified(status="failed", reason="Card declined"), "test")
    payments.settle("pay_x", Verified(status="failed", reason="Card declined"), "test")
    await sms.drain()
    assert len(prov.alpha_sent) == 3 and "did not go through" in prov.alpha_sent[2]["text"]


async def test_a_broken_sms_provider_never_breaks_shipping(prov):
    connect_provider("alphasms")
    connect_provider("steadfast")
    order_with_phone(method="Cash on delivery", pay="Pending")
    prov.alpha_error = 409
    res = await couriers.book("#2001", "steadfast", "Farhana", couriers.cod_amount(store.order("#2001")))
    await sms.drain()
    assert res["tracking"] and store.order("#2001")["fulfillment"] == "In transit" and rows()[0]["status"] == "Failed"


# ---------------------------------------------------------------- the API
async def test_status_update_button_sends_a_real_sms_and_reports_problems(http, prov):
    owner = await setup_owner(http)
    order_with_phone()
    r0 = await http.post("/api/orders/%232001/notify", headers=H(owner), json={"via": "sms"})
    assert r0.status_code == 409 and "provider" in r0.json()["detail"]
    connect_provider("alphasms")
    r = await http.post("/api/orders/%232001/notify", headers=H(owner), json={"via": "sms"})
    assert r.status_code == 200 and r.json()["sms"]["status"] == "Accepted" and len(prov.alpha_sent) == 1
    assert "#2001" in prov.alpha_sent[0]["text"]
    viewer = await member_token(http, owner, "viewer")
    assert (await http.post("/api/orders/%232001/notify", headers=H(viewer), json={"via": "sms"})).status_code == 403


async def test_sms_log_resend_and_settings_respect_roles(http, prov):
    owner = await setup_owner(http)
    connect_provider("alphasms")
    order_with_phone()
    prov.alpha_error = 409
    await sms.notify("#2001", "shipped")
    prov.alpha_error = None
    ov = (await http.get("/api/sms", headers=H(owner))).json()
    assert ov["messages"][0]["status"] == "Failed" and ov["messages"][0]["canResend"] and ov["provider"] == "alphasms" and ov["usage"]["failed24h"] == 1
    viewer = await member_token(http, owner, "viewer")
    assert (await http.post(f"/api/sms/{ov['messages'][0]['id']}/resend", headers=H(viewer))).status_code == 403
    assert (await http.put("/api/sms/settings", headers=H(viewer), json={})).status_code == 403
    again = await http.post(f"/api/sms/{ov['messages'][0]['id']}/resend", headers=H(owner))
    assert again.status_code == 200 and len(prov.alpha_sent) == 1
    assert (await http.post(f"/api/sms/{again.json()['message']['id']}/resend", headers=H(owner))).status_code == 409   # already accepted
    s = await http.put("/api/sms/settings", headers=H(owner), json={"quiet": False, "quietFrom": 22, "quietTo": 8, "perNumberDay": 3, "perDay": 100})
    assert s.status_code == 200 and sms.settings()["perNumberDay"] == 3
    assert (await http.put("/api/sms/settings", headers=H(owner), json={"perNumberDay": 0})).status_code == 422


async def test_test_sms_endpoint_and_unbuilt_sms_providers(http, prov):
    owner = await setup_owner(http)
    assert (await http.post("/api/providers/alphasms/test-sms", headers=H(owner), json={"to": "01712345678"})).status_code == 400   # not connected
    connect_provider("alphasms")
    ok = await http.post("/api/providers/alphasms/test-sms", headers=H(owner), json={"to": "01712345678"})
    assert ok.status_code == 200 and "not delivery" in ok.json()["message"] and len(prov.alpha_sent) == 1
    bad = await http.post("/api/providers/alphasms/test-sms", headers=H(owner), json={"to": "123456"})
    assert bad.status_code == 400 and len(prov.alpha_sent) == 1
    gp = await http.post("/api/providers/gp/connect", headers=H(owner), json={"values": {}})
    assert gp.status_code == 400 and "not public" in gp.json()["detail"]
    items = (await http.get("/api/providers", headers=H(owner))).json()["items"]
    assert {i["id"] for i in items if i["group"] == "SMS"} >= {"sslwireless", "alphasms", "gp"}


async def test_sms_hosts_are_locked_to_the_providers_own_domains(prov):
    from app.providers import common
    with pytest.raises(ProviderError):
        common.check_host("alphasms", "https://evil.example.com/sendsms")
    common.check_host("alphasms", "https://api.sms.net.bd/sendsms")
    common.check_host("sslwireless", "https://smsplus.sslwireless.com/api/v3/send-sms")
