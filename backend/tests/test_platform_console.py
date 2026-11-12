"""The platform console's data: one business as the platform sees it, the feature matrix, and administering any person's account across businesses."""
import json

import httpx
import pytest

from app import db, registry
from app.main import app
from tests.conftest import say
from tests.test_auth import H, PW, login, member_token, setup_owner


@pytest.fixture
async def http():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture(autouse=True)
def cleanup():
    registry.create("Alpha Store", "alpha"), registry.create("Beta Store", "beta")
    yield
    db.close_all()
    for b in registry.all_businesses():
        if b["slug"] != "default":
            registry.delete(b["id"])


async def admin(http):
    return await setup_owner(http)


# ================================================================ a business as the platform sees it
async def test_business_detail_shows_setup_and_use_but_never_customer_content(http):
    o = await admin(http)
    with db.business("alpha"):
        db.run("INSERT INTO products(id,sku,name,price,stock,art) VALUES('p1','S-1','Red saree',1200,5,'box')")
        await say("ch_web", "web_x", "Secretive Customer", "my phone is 01799998888 and I live at Secret Lane 9", "01799998888")
        db.run("UPDATE integrations SET status='ok', live=1 WHERE id='steadfast'")
        db.run("INSERT INTO channels(id,kind,name,handle,status,health,created_at,live) VALUES('ch_wa','wa','WhatsApp','+880','ok','[]',?,1)", [db.now()])
        db.run("INSERT INTO catalog_sources(id,host,url,kind,default_stock,created_at,last_count) VALUES('cs1','shop.test','https://shop.test/','shopify',10,?,42)", [db.now()])
    registry.add_membership(registry.account_by_email("owner@shop.test")["id"], registry.resolve("alpha")["id"], "owner")
    r = await http.get("/api/platform/businesses/alpha", headers=H(o))
    assert r.status_code == 200
    d = r.json()
    assert d["slug"] == "alpha" and d["plan"]["name"] == "Free" and d["plan"]["seats"] == 3 and d["usage"]["seats"] == 1
    assert d["counts"]["products"] == 1 and d["counts"]["customers"] == 1 and d["counts"]["conversations"] == 1 and d["counts"]["messages30"] >= 2
    assert {"kind": "wa", "name": "WhatsApp", "status": "ok", "live": True} == {k: d["channels"][-1][k] for k in ("kind", "name", "status", "live")}
    assert d["features"]["channels"] == ["wa"] and d["features"]["couriers"] == ["Steadfast"] and d["features"]["webChat"] is True and d["features"]["websiteImport"] == 1
    assert d["catalogSources"][0]["lastCount"] == 42 and d["ai"]["engine"] == "offline"
    assert [m["email"] for m in d["members"]] == ["owner@shop.test"] and d["members"][0]["role"] == "owner"
    blob = json.dumps(d)
    for secret in ("Secretive Customer", "01799998888", "Secret Lane", "Red saree"):
        assert secret not in blob                                                       # sizes, statuses and staff actions only
    assert (await http.get("/api/platform/businesses/nope", headers=H(o))).status_code == 404


async def test_the_feature_matrix_lists_every_business_and_survives_a_broken_one(http, monkeypatch):
    o = await admin(http)
    with db.business("beta"):
        db.run("UPDATE integrations SET status='ok', live=1 WHERE id='bkash'")
    items = {i["slug"]: i for i in (await http.get("/api/platform/features", headers=H(o))).json()["items"]}
    assert set(items) >= {"default", "alpha", "beta"} and items["beta"]["features"]["payments"] == ["bKash"] and items["alpha"]["features"]["payments"] == []
    from app.routes import platform as pl
    real = pl._facts
    monkeypatch.setattr(pl, "_facts", lambda b: (_ for _ in ()).throw(RuntimeError("corrupt")) if b["slug"] == "alpha" else real(b))
    items = {i["slug"]: i for i in (await http.get("/api/platform/features", headers=H(o))).json()["items"]}
    assert items["alpha"]["error"] and items["beta"]["features"]["payments"] == ["bKash"]


# ================================================================ people
async def test_the_accounts_list_and_detail_show_every_business_and_session(http):
    o = await admin(http)
    agent = await member_token(http, o, "agent")
    registry.add_membership(registry.account_by_email("agent@shop.test")["id"], registry.resolve("alpha")["id"], "viewer")
    items = {a["email"]: a for a in (await http.get("/api/platform/accounts", headers=H(o))).json()["items"]}
    a = items["agent@shop.test"]
    assert a["platformAdmin"] is False and a["sessions"] >= 1 and {(b["slug"], b["role"]) for b in a["businesses"]} == {("default", "agent"), ("alpha", "viewer")}
    d = (await http.get(f"/api/platform/accounts/{a['id']}", headers=H(o))).json()
    assert d["sessionList"] and "token" not in json.dumps(d).lower().replace("must", "") and d["sessionList"][0]["business"] == "default"
    await http.patch(f"/api/platform/accounts/{a['id']}", headers=H(o), json={"signOut": True})
    d = (await http.get(f"/api/platform/accounts/{a['id']}", headers=H(o))).json()
    assert d["sessions"] == 0 and any(x["action"] == "account.signout" for x in d["platformLog"])
    assert (await http.get("/api/platform/accounts/nope", headers=H(o))).status_code == 404


async def test_creating_an_account_with_a_business_and_role(http):
    o = await admin(http)
    r = await http.post("/api/platform/accounts", headers=H(o), json={"name": "Nadia Support", "email": "Nadia@Shop.test", "password": "temporary-pass-9", "business": "alpha", "role": "admin"})
    assert r.status_code == 200
    a = r.json()
    assert a["email"] == "nadia@shop.test" and a["mustChange"] is True and a["businesses"] == [{"slug": "alpha", "name": "Alpha Store", "role": "admin", "active": True, "status": "active"}]
    with db.business("alpha"):
        assert "team.add" in [x["action"] for x in db.all("SELECT action FROM audit")]
    t = (await login(http, "nadia@shop.test", "temporary-pass-9")).json()["token"]
    assert (await http.get("/api/me", headers=H(t))).json()["business"]["slug"] == "alpha"
    for bad, code in (({"password": "short"}, 400), ({"email": "nobody"}, 400), ({"email": "nadia@shop.test"}, 409), ({"business": "nope"}, 404), ({"role": "god"}, 400)):
        body = {"name": "Other Person", "email": "other@shop.test", "password": "temporary-pass-9", **bad}
        assert (await http.post("/api/platform/accounts", headers=H(o), json=body)).status_code == code, bad
    assert registry.account_by_email("other@shop.test") is None


async def test_the_plans_seat_limit_applies_when_the_platform_adds_someone(http):
    o = await admin(http)
    registry.set_plan("alpha", limits={"seats": 1})
    registry.add_membership(registry.account_by_email("owner@shop.test")["id"], registry.resolve("alpha")["id"], "owner")
    r = await http.post("/api/platform/accounts", headers=H(o), json={"name": "Extra Person", "email": "extra@shop.test", "password": "temporary-pass-9", "business": "alpha"})
    assert r.status_code == 409 and "allows 1 team member" in r.json()["detail"]
    assert registry.account_by_email("extra@shop.test") is None


async def test_resetting_a_password_signs_them_out_and_forces_a_new_one(http):
    o = await admin(http)
    agent = await member_token(http, o, "agent")
    aid = registry.account_by_email("agent@shop.test")["id"]
    assert (await http.post(f"/api/platform/accounts/{aid}/reset-password", headers=H(o), json={"password": "short"})).status_code == 400
    assert (await http.post(f"/api/platform/accounts/{aid}/reset-password", headers=H(o), json={"password": "fresh-temp-pass-7"})).status_code == 200
    assert (await http.get("/api/me", headers=H(agent))).status_code == 401
    assert (await login(http, "agent@shop.test", PW)).status_code == 401
    r = await login(http, "agent@shop.test", "fresh-temp-pass-7")
    assert r.status_code == 200 and r.json()["user"]["mustChange"] is True
    me = registry.account_by_email("owner@shop.test")["id"]
    assert (await http.post(f"/api/platform/accounts/{me}/reset-password", headers=H(o), json={"password": "fresh-temp-pass-7"})).status_code == 400
    assert (await http.post("/api/platform/accounts/nope/reset-password", headers=H(o), json={"password": "fresh-temp-pass-7"})).status_code == 404


async def test_memberships_can_be_set_and_removed_but_a_business_always_keeps_an_owner(http):
    o = await admin(http)
    extra = registry.create_account("Second Owner", "second@shop.test", "x", account_id="usr_second")
    r = await http.put(f"/api/platform/accounts/{extra['id']}/memberships/alpha", headers=H(o), json={"role": "owner"})
    assert r.status_code == 200 and r.json()["businesses"][0]["role"] == "owner"
    # alpha now has exactly one owner, so that owner cannot be demoted, switched off or removed
    assert (await http.put(f"/api/platform/accounts/{extra['id']}/memberships/alpha", headers=H(o), json={"role": "agent"})).status_code == 409        # the only owner
    assert (await http.put(f"/api/platform/accounts/{extra['id']}/memberships/alpha", headers=H(o), json={"active": False})).status_code == 409
    assert (await http.delete(f"/api/platform/accounts/{extra['id']}/memberships/alpha", headers=H(o))).status_code == 409
    other = registry.create_account("Plain Agent", "plain@shop.test", "x", account_id="usr_plain")
    await http.put(f"/api/platform/accounts/{other['id']}/memberships/alpha", headers=H(o), json={"role": "agent"})
    tok = registry.open_session(other["id"], registry.resolve("alpha")["id"], "1.1.1.1", "t")
    assert (await http.get("/api/me", headers=H(tok))).status_code == 200
    r = await http.delete(f"/api/platform/accounts/{other['id']}/memberships/alpha", headers=H(o))
    assert r.status_code == 200 and r.json()["businesses"] == []
    me = await http.get("/api/me", headers=H(tok))
    assert me.status_code == 401 or me.json()["business"] is None                                                   # no longer in alpha
    with db.business("alpha"):
        acts = [x["action"] for x in db.all("SELECT action FROM audit")]
    assert "team.add" in acts and "team.remove" in acts
    assert (await http.delete(f"/api/platform/accounts/{other['id']}/memberships/alpha", headers=H(o))).status_code == 404
    assert (await http.put(f"/api/platform/accounts/{other['id']}/memberships/nope", headers=H(o), json={"role": "agent"})).status_code == 404
    assert (await http.put(f"/api/platform/accounts/{other['id']}/memberships/alpha", headers=H(o), json={"role": "god"})).status_code == 400


async def test_renaming_and_the_platform_administrator_role(http):
    o = await admin(http)
    agent = await member_token(http, o, "agent")
    aid = registry.account_by_email("agent@shop.test")["id"]
    me = registry.account_by_email("owner@shop.test")["id"]
    assert (await http.patch(f"/api/platform/accounts/{aid}", headers=H(o), json={"name": "Renamed Agent"})).json()["name"] == "Renamed Agent"
    assert (await http.patch(f"/api/platform/accounts/{aid}", headers=H(o), json={"platformAdmin": True})).json()["platformAdmin"] is True
    assert (await http.get("/api/platform/overview", headers=H(agent))).status_code == 200                           # now an administrator too
    assert (await http.patch(f"/api/platform/accounts/{aid}", headers=H(o), json={"platformAdmin": False})).json()["platformAdmin"] is False
    assert (await http.patch(f"/api/platform/accounts/{me}", headers=H(o), json={"platformAdmin": False})).status_code == 400   # not yourself / the last one
    log = [x["action"] for x in (await http.get("/api/platform/log", headers=H(o))).json()["items"]]
    assert {"account.rename", "account.admin_on", "account.admin_off"} <= set(log)


async def test_all_the_console_endpoints_are_for_the_administrator_only(http):
    o = await admin(http)
    agent = await member_token(http, o, "agent")
    aid = registry.account_by_email("agent@shop.test")["id"]
    calls = (("GET", "/api/platform/businesses/alpha", None), ("GET", "/api/platform/features", None), ("GET", f"/api/platform/accounts/{aid}", None),
             ("POST", "/api/platform/accounts", {"name": "Some One", "email": "s@x.test", "password": "temporary-pass-9"}),
             ("POST", f"/api/platform/accounts/{aid}/reset-password", {"password": "fresh-temp-pass-7"}),
             ("PUT", f"/api/platform/accounts/{aid}/memberships/alpha", {"role": "agent"}), ("DELETE", f"/api/platform/accounts/{aid}/memberships/alpha", None))
    for m, p, body in calls:
        assert (await http.request(m, p, headers=H(agent), json=body)).status_code == 403, p
        assert (await http.request(m, p, json=body)).status_code == 401, p
