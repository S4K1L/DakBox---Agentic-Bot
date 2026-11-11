"""Booking parcels and following them. Steadfast's real docs are not public, so these prove Dakbox's own safety rules and consistency."""
import json

import httpx
import pytest

from app import couriers, db
from app.main import app
from tests.conftest import connect_provider, make_order
from tests.test_auth import H, member_token, setup_owner


@pytest.fixture
async def http():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


def ord_(no="#2001"):
    return db.get("SELECT * FROM orders WHERE number=?", [no])


def cod_order(no="#2001"):
    # Sadia has no phone in the seed: give her a valid Bangladeshi mobile number
    db.run("UPDATE customers SET phone='+8801712345678' WHERE id='c_sadia'")
    return make_order(no, method="Cash on delivery", pay="Pending")


async def ship(http, token, no="#2001", cod=None, courier="steadfast"):
    return await http.post(f"/api/orders/{no.replace('#', '%23')}/ship", headers=H(token), json={"courier": courier, "expectedCod": cod})


# ---------------------------------------------------------------- connecting
async def test_connect_checks_with_steadfast_and_never_echoes_secrets(http, prov):
    owner = await setup_owner(http)
    bad = await http.post("/api/providers/steadfast/connect", headers=H(owner), json={"values": {"api_key": "wrong", "secret_key": "wrong"}})
    assert bad.status_code == 400 and "rejected" in bad.json()["detail"]
    assert not db.get("SELECT live FROM integrations WHERE id='steadfast'")["live"]
    ok = await http.post("/api/providers/steadfast/connect", headers=H(owner), json={"values": {"api_key": "sfkey", "secret_key": "sfsecret"}, "config": {"charge_dhaka": "60", "charge_out": "120"}})
    assert ok.status_code == 200 and ok.json()["live"] and ok.json()["officialDocs"] is False
    assert ok.json()["webhookSecret"] and "sfsecret" not in ok.text and "sfsecret" not in (await http.get("/api/providers", headers=H(owner))).text
    assert "sfkey" not in db.get("SELECT credentials FROM integrations WHERE id='steadfast'")["credentials"]


async def test_unbuilt_providers_say_why(http, prov):
    owner = await setup_owner(http)
    r = await http.post("/api/providers/pathao/connect", headers=H(owner), json={"values": {}})
    assert r.status_code == 400 and "official API documentation" in r.json()["detail"]
    items = (await http.get("/api/providers", headers=H(owner))).json()["items"]
    pathao = next(i for i in items if i["id"] == "pathao")
    assert pathao["supported"] is False and pathao["notBuiltReason"]


async def test_provider_addresses_are_restricted_to_the_providers_own_domains(http, prov):
    owner = await setup_owner(http)
    r = await http.post("/api/providers/bkash/connect", headers=H(owner), json={"mode": "live", "values": {"username": "u", "password": "p", "app_key": "k", "app_secret": "s"}, "config": {"base_url": "https://evil.example.com/v2"}})
    assert r.status_code == 400 and prov.calls == []                       # credentials were never sent anywhere
    r2 = await http.post("/api/providers/bkash/connect", headers=H(owner), json={"mode": "live", "values": {"username": "u", "password": "p", "app_key": "k", "app_secret": "s"}, "config": {"base_url": "http://tokenized.pay.bka.sh/v2"}})
    assert r2.status_code == 400                                           # https only


async def test_only_admins_connect_providers_and_disconnect_wipes(http, prov):
    owner = await setup_owner(http)
    agent = await member_token(http, owner, "agent")
    body = {"values": {"api_key": "sfkey", "secret_key": "sfsecret"}}
    assert (await http.post("/api/providers/steadfast/connect", headers=H(agent), json=body)).status_code == 403
    assert (await http.post("/api/providers/steadfast/connect", headers=H(owner), json=body)).status_code == 200
    assert (await http.delete("/api/providers/steadfast", headers=H(owner))).status_code == 200
    row = db.get("SELECT * FROM integrations WHERE id='steadfast'")
    assert row["credentials"] is None and row["live"] == 0 and row["status"] == "off"


async def test_a_failing_check_switches_the_provider_off_until_fixed(http, prov):
    owner = await setup_owner(http); connect_provider("steadfast")
    db.run("UPDATE integrations SET credentials=? WHERE id='steadfast'", [pcommon_seal({"api_key": "x", "secret_key": "y"})])
    r = (await http.post("/api/providers/steadfast/check", headers=H(owner))).json()
    assert r["ok"] is False and db.get("SELECT status FROM integrations WHERE id='steadfast'")["status"] == "warn"
    from app.providers import common
    assert common.is_live("steadfast") is False                            # fails closed: nothing is booked with a broken connection


def pcommon_seal(d):
    from app.secrets_store import seal
    return seal(json.dumps(d))


# ---------------------------------------------------------------- rates and demo mode
async def test_rates_show_the_connected_courier_with_your_charges(http, prov):
    owner = await setup_owner(http); connect_provider("steadfast"); cod_order()
    r = (await http.get("/api/orders/%232001/rates", headers=H(owner))).json()
    assert r["rates"] == [{"id": "steadfast", "name": "Steadfast", "price": 130, "window": "", "live": True, "note": r["rates"][0]["note"]}] and r["cod"] == 1520


async def test_with_no_courier_connected_booking_is_labelled_demo_and_calls_nobody(http, prov):
    owner = await setup_owner(http); cod_order()
    rates = (await http.get("/api/orders/%232001/rates", headers=H(owner))).json()["rates"]
    assert all(x["demo"] for x in rates)
    r = (await ship(http, owner, courier=rates[0]["id"])).json()
    assert r["demo"] is True and r["tracking"].startswith("DEMO-") and prov.calls == []
    assert json.loads(ord_()["courier"])["demo"] is True


# ---------------------------------------------------------------- booking
async def test_booking_sends_the_right_parcel_and_cod(http, prov):
    owner = await setup_owner(http); connect_provider("steadfast"); cod_order()
    r = await ship(http, owner, cod=1520)
    assert r.status_code == 200 and r.json()["demo"] is False and r.json()["cod"] == 1520
    sent = prov.calls[-1]
    assert sent["path"].endswith("/create_order") and sent["headers"]["api-key"] == "sfkey" and sent["headers"]["secret-key"] == "sfsecret"
    assert sent["body"] == {"invoice": "2001", "recipient_name": "Sadia Rahman", "recipient_phone": "01712345678", "recipient_address": "House 12, Road 4, Zindabazar, Sylhet 3100", "cod_amount": 1520, "note": "Dakbox order #2001"}
    o = ord_()
    info = json.loads(o["courier"])
    assert o["fulfillment"] == "In transit" and o["stage"] == 3 and info["consignment_id"] == "1424001" and info["cod"] == 1520


async def test_the_person_booking_must_confirm_the_exact_cod_amount(http, prov):
    owner = await setup_owner(http); connect_provider("steadfast"); cod_order()
    assert (await ship(http, owner, cod=1)).status_code == 409
    assert (await ship(http, owner, cod=None)).status_code == 409
    assert not [c for c in prov.calls if c["path"].endswith("/create_order")]


async def test_prepaid_orders_collect_nothing_and_unpaid_prepaid_orders_do_not_ship(http, prov):
    owner = await setup_owner(http); connect_provider("steadfast")
    db.run("UPDATE customers SET phone='+8801712345678' WHERE id='c_sadia'")
    make_order("#2002", method="bKash", pay="Paid")
    make_order("#2003", method="bKash", pay="Pending")
    assert (await ship(http, owner, "#2003", cod=0)).status_code == 409           # payment not received
    ok = await ship(http, owner, "#2002", cod=0)
    assert ok.status_code == 200 and prov.calls[-1]["body"]["cod_amount"] == 0


async def test_one_parcel_per_order(http, prov):
    owner = await setup_owner(http); connect_provider("steadfast"); cod_order()
    assert (await ship(http, owner, cod=1520)).status_code == 200
    assert (await ship(http, owner, cod=1520)).status_code == 409
    assert len([c for c in prov.calls if c["path"].endswith("/create_order")]) == 1


async def test_bad_phone_or_address_is_caught_before_or_by_the_courier(http, prov):
    owner = await setup_owner(http); connect_provider("steadfast")
    db.run("UPDATE customers SET phone='12345' WHERE id='c_sadia'")
    make_order("#2002", method="Cash on delivery", pay="Pending")
    r = await ship(http, owner, "#2002", cod=1520)
    assert r.status_code == 400 and "11-digit" in r.json()["detail"] and not [c for c in prov.calls if c["path"].endswith("/create_order")]
    db.run("UPDATE customers SET phone='+8801712345678' WHERE id='c_sadia'")
    db.run("UPDATE orders SET address='short' WHERE number='#2002'")
    r2 = await ship(http, owner, "#2002", cod=1520)
    assert r2.status_code == 400 and "address" in r2.json()["detail"]


async def test_a_courier_that_rejects_the_booking_changes_nothing(http, prov):
    owner = await setup_owner(http); connect_provider("steadfast"); cod_order()
    prov.sf_invoices.add("2001")                                         # Steadfast already has this invoice
    r = await ship(http, owner, cod=1520)
    assert r.status_code == 502 and "already been taken" in r.json()["detail"]
    assert ord_()["fulfillment"] == "Unfulfilled" and ord_()["courier"] is None


# ---------------------------------------------------------------- tracking
async def test_tracking_moves_the_order_and_settles_cod_on_delivery(http, prov):
    owner = await setup_owner(http); connect_provider("steadfast"); cod_order()
    await ship(http, owner, cod=1520)
    prov.sf_set("1424001", "delivered")
    r = (await http.post("/api/orders/%232001/track", headers=H(owner))).json()
    assert r["changed"] is True
    o = ord_()
    assert o["fulfillment"] == "Delivered" and o["stage"] == 5 and o["pay_status"] == "Paid" and "collected by courier" in o["pay_method"]
    again = (await http.post("/api/orders/%232001/track", headers=H(owner))).json()
    assert again["changed"] is False                                      # asking twice changes nothing


async def test_prepaid_delivery_does_not_touch_payment(http, prov):
    owner = await setup_owner(http); connect_provider("steadfast")
    db.run("UPDATE customers SET phone='+8801712345678' WHERE id='c_sadia'")
    make_order("#2002", method="bKash", pay="Paid")
    await ship(http, owner, "#2002", cod=0)
    prov.sf_set("1424001", "delivered")
    await http.post("/api/orders/%232002/track", headers=H(owner))
    assert ord_("#2002")["pay_method"] == "bKash"


async def test_unknown_statuses_never_change_an_order(http, prov):
    owner = await setup_owner(http); connect_provider("steadfast"); cod_order()
    await ship(http, owner, cod=1520)
    prov.sf_set("1424001", "some_new_status_we_never_heard_of")
    r = (await http.post("/api/orders/%232001/track", headers=H(owner))).json()
    assert r["changed"] is False and "does not recognise" in r["message"] and ord_()["fulfillment"] == "In transit"


async def test_cancelled_by_the_courier_is_returned_not_delivered(http, prov):
    owner = await setup_owner(http); connect_provider("steadfast"); cod_order()
    await ship(http, owner, cod=1520)
    prov.sf_set("1424001", "cancelled")
    await http.post("/api/orders/%232001/track", headers=H(owner))
    assert ord_()["fulfillment"] == "Returned" and ord_()["pay_status"] == "Pending"


async def test_the_poller_refreshes_every_parcel_on_the_way(http, prov):
    owner = await setup_owner(http); connect_provider("steadfast"); cod_order()
    await ship(http, owner, cod=1520)
    prov.sf_set("1424001", "delivered")
    assert await couriers.poll_all() == 1 and ord_()["fulfillment"] == "Delivered"


# ---------------------------------------------------------------- the courier's webhook
async def test_the_webhook_needs_the_secret_and_never_believes_its_own_body(http, prov):
    owner = await setup_owner(http); connect_provider("steadfast"); cod_order()
    await ship(http, owner, cod=1520)
    body = {"consignment_id": 1424001, "status": "delivered", "delivery_status": "delivered"}
    assert (await http.post("/hooks/steadfast", json=body)).status_code == 401
    assert (await http.post("/hooks/steadfast", json=body, headers={"Authorization": "Bearer wrong"})).status_code == 401
    r = await http.post("/hooks/steadfast", json=body, headers={"Authorization": "Bearer hook-secret-abc"})
    assert r.status_code == 200 and r.json()["refreshed"] == 1
    assert ord_()["fulfillment"] == "In transit"                          # the body said delivered; Steadfast, asked directly, said in_review
    prov.sf_set("1424001", "delivered")
    await http.post("/hooks/steadfast", json=body, headers={"Authorization": "Bearer hook-secret-abc"})
    assert ord_()["fulfillment"] == "Delivered"


async def test_agents_can_book_and_track_but_viewers_cannot(http, prov):
    owner = await setup_owner(http); connect_provider("steadfast"); cod_order()
    agent = await member_token(http, owner, "agent")
    viewer = await member_token(http, owner, "viewer")
    assert (await ship(http, viewer, cod=1520)).status_code == 403
    assert (await ship(http, agent, cod=1520)).status_code == 200
    assert (await http.post("/api/orders/%232001/track", headers=H(viewer))).status_code == 403
    assert (await http.post("/api/orders/%232001/track", headers=H(agent))).status_code == 200
