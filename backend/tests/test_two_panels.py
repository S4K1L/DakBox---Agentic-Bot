"""Two panels: the super administrator creates businesses (each with its own owner) and does the platform work; the business owner runs their own business
and adds their own staff. The super administrator is not made the owner of other people's businesses."""
import io
import json
import zipfile

import httpx
import pytest

from app import db, registry
from app.main import app
from tests.conftest import say
from tests.test_auth import H, PW, login, setup_owner


@pytest.fixture
async def http():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture(autouse=True)
def cleanup(monkeypatch):
    monkeypatch.delenv("DAKBOX_HOSTED", raising=False)
    yield
    db.close_all()
    for b in registry.all_businesses():
        if b["slug"] != "default":
            registry.delete(b["id"])


async def make(http, admin, owner=None, **extra):
    body = {"name": "Rina Saree House", "slug": "rina", "plan": "standard", **extra}
    if owner is not False:
        body["owner"] = owner or {"name": "Rina Owner", "email": "rina@shop.test", "password": "temporary-pass-9"}
    return await http.post("/api/platform/businesses", headers=H(admin), json=body)


async def owner_token(http, email="rina@shop.test", temp="temporary-pass-9", new="rina-own-password-1"):
    t = (await login(http, email, temp)).json()["token"]
    assert (await http.post("/api/auth/password", headers=H(t), json={"current": temp, "new": new})).status_code == 200
    return (await login(http, email, new)).json()["token"]


# ================================================================ the super administrator creates a business and its owner
async def test_a_new_business_gets_its_own_owner_and_the_super_admin_is_not_a_member(http):
    admin = await setup_owner(http)
    r = await make(http, admin)
    assert r.status_code == 200
    d = r.json()
    assert d["business"]["slug"] == "rina" and d["owner"] == {"id": d["owner"]["id"], "name": "Rina Owner", "email": "rina@shop.test", "created": True}
    assert d["business"]["owners"] == ["Rina Owner"] and d["business"]["members"] == 1
    me = registry.account_by_email("owner@shop.test")["id"]
    assert registry.membership(me, registry.resolve("rina")["id"]) is None                          # not a member of someone else's business
    assert (await http.post("/api/auth/switch", headers=H(admin), json={"business": "rina"})).status_code == 403
    acct = registry.account_by_email("rina@shop.test")
    assert acct["must_change"] == 1 and acct["platform_admin"] == 0
    assert any(x["action"] == "business.create" and "rina@shop.test" in x["detail"] for x in (await http.get("/api/platform/log", headers=H(admin))).json()["items"])


async def test_the_owner_signs_in_to_their_own_panel_only(http):
    admin = await setup_owner(http)
    await make(http, admin)
    first = await login(http, "rina@shop.test", "temporary-pass-9")
    assert first.json()["user"]["mustChange"] is True
    t = await owner_token(http)
    me = (await http.get("/api/me", headers=H(t))).json()
    assert me["role"] == "owner" and me["business"]["slug"] == "rina" and me["platformAdmin"] is False
    for p in ("/api/platform/overview", "/api/platform/businesses", "/api/platform/accounts", "/api/platform/features"):
        assert (await http.get(p, headers=H(t))).status_code == 403, p                              # the owner has no super admin powers
    assert (await http.post("/api/platform/businesses", headers=H(t), json={"name": "Sneaky Shop"})).status_code == 403


async def test_an_existing_person_can_be_made_the_owner_without_touching_their_password(http):
    admin = await setup_owner(http)
    await make(http, admin)
    before = registry.account_by_email("rina@shop.test")["password_hash"]
    r = await make(http, admin, owner={"email": "rina@shop.test"}, name="Rina Second Shop", slug="rina2")
    assert r.status_code == 200 and r.json()["owner"]["created"] is False and r.json()["owner"]["name"] == "Rina Owner"
    assert registry.account_by_email("rina@shop.test")["password_hash"] == before
    t = (await login(http, "rina@shop.test", "temporary-pass-9")).json()["user"]
    assert {b["slug"] for b in t["businesses"]} == {"rina", "rina2"}


async def test_a_refused_business_leaves_no_stray_account(http):
    admin = await setup_owner(http)
    await make(http, admin)
    for owner, code in (({"name": "X Person", "email": "nope", "password": "temporary-pass-9"}, 400), ({"name": "", "email": "new@shop.test", "password": "temporary-pass-9"}, 400),
                        ({"name": "New Owner", "email": "new@shop.test", "password": "short"}, 400)):
        assert (await make(http, admin, owner=owner, name="Other Shop", slug="other")).status_code == code
    assert registry.account_by_email("new@shop.test") is None
    r = await make(http, admin, owner={"name": "New Owner", "email": "new@shop.test", "password": "temporary-pass-9"}, slug="rina")            # the address is taken
    assert r.status_code == 400 and registry.account_by_email("new@shop.test") is None
    assert (await make(http, admin, owner={"name": "New Owner", "email": "new@shop.test", "password": "temporary-pass-9"}, plan="nope", slug="x1")).status_code == 400


async def test_without_an_owner_in_the_request_the_creator_still_becomes_owner(http):
    admin = await setup_owner(http)
    r = await make(http, admin, owner=False, name="Command Line Shop", slug="cli")
    assert r.status_code == 200 and r.json()["owner"] is None
    assert registry.membership(registry.account_by_email("owner@shop.test")["id"], registry.resolve("cli")["id"])["role"] == "owner"


# ================================================================ the owner runs their business and their staff
async def test_the_owner_adds_staff_who_work_in_that_business_and_cannot_manage_it(http):
    admin = await setup_owner(http)
    await make(http, admin)
    t = await owner_token(http)
    r = await http.post("/api/team", headers=H(t), json={"name": "Staff Agent", "email": "staff@shop.test", "role": "agent", "password": "staff-temp-pass-1"})
    assert r.status_code == 200
    s = (await login(http, "staff@shop.test", "staff-temp-pass-1")).json()["token"]
    await http.post("/api/auth/password", headers=H(s), json={"current": "staff-temp-pass-1", "new": "staff-own-password-1"})
    s = (await login(http, "staff@shop.test", "staff-own-password-1")).json()["token"]
    assert (await http.get("/api/me", headers=H(s))).json()["business"]["slug"] == "rina"
    b = (await http.get("/api/business", headers=H(s))).json()
    assert b["canEdit"] is False and b["yourRole"] == "agent"
    assert (await http.patch("/api/business", headers=H(s), json={"name": "Hijacked"})).status_code == 403
    assert (await http.post("/api/business/export", headers=H(s))).status_code == 403
    assert (await http.get("/api/team", headers=H(s))).status_code == 403                           # staff cannot see or change the team
    assert (await http.post("/api/team", headers=H(s), json={"name": "Another One", "email": "x@shop.test", "role": "agent", "password": "x-temp-pass-12"})).status_code == 403


async def test_the_owners_business_page_shows_plan_use_and_lets_them_rename_and_export(http):
    admin = await setup_owner(http)
    await make(http, admin)
    t = await owner_token(http)
    with db.business("rina"):
        db.run("INSERT INTO products(id,sku,name,price,stock,art) VALUES('p1','R-1','Rina Handloom',1500,3,'box')")
        await say("ch_web", "web_r", "Rina Customer", "hello", "01711223344")
    b = (await http.get("/api/business", headers=H(t))).json()
    assert b["slug"] == "rina" and b["name"] == "Rina Saree House" and b["canEdit"] is True and b["owners"] == ["Rina Owner"] and b["people"] == 1
    assert b["plan"]["name"] == "Standard" and b["seats"] == {"used": 1, "limit": 10, "left": 9} and b["products"]["used"] == 1
    r = await http.patch("/api/business", headers=H(t), json={"name": "Rina Saree Emporium"})
    assert r.status_code == 200 and r.json()["name"] == "Rina Saree Emporium"
    assert (await http.get("/api/me", headers=H(t))).json()["business"]["name"] == "Rina Saree Emporium"
    assert (await http.patch("/api/business", headers=H(t), json={"name": "x"})).status_code == 422
    with db.business("rina"):
        assert "business.rename" in [a["action"] for a in db.all("SELECT action FROM audit")]
    ex = (await http.post("/api/business/export", headers=H(t))).json()
    z = zipfile.ZipFile(io.BytesIO((await http.get(ex["url"])).content))
    blob = b"".join(z.read(n) for n in z.namelist()).decode("utf-8", "ignore")
    assert "Rina Handloom" in blob and json.loads(z.read("manifest.json"))["slug"] == "rina"
    # the owner's name change is a platform-visible fact too
    assert [x for x in (await http.get("/api/platform/businesses", headers=H(admin))).json()["items"] if x["slug"] == "rina"][0]["name"] == "Rina Saree Emporium"


async def test_the_business_endpoints_need_a_signed_in_member_of_a_business(http):
    admin = await setup_owner(http)
    for m, p, body in (("GET", "/api/business", None), ("PATCH", "/api/business", {"name": "Some Name"}), ("POST", "/api/business/export", None)):
        assert (await http.request(m, p, json=body)).status_code == 401
    acct = registry.create_account("Plat Only", "platonly@shop.test", "x", platform_admin=True, account_id="usr_platonly")
    tok = registry.open_session(acct["id"], None, "1.1.1.1", "t")
    for m, p, body in (("GET", "/api/business", None), ("PATCH", "/api/business", {"name": "Some Name"}), ("POST", "/api/business/export", None)):
        assert (await http.request(m, p, headers=H(tok), json=body)).status_code == 403, p        # a super admin with no business has no business panel


# ================================================================ a hosted server's first account is the super admin only
async def test_a_hosted_servers_first_account_is_the_super_admin_with_no_business(http, monkeypatch):
    monkeypatch.setenv("DAKBOX_HOSTED", "1")
    monkeypatch.setenv("DAKBOX_STRICT_BUSINESS", "0")
    st = (await http.get("/api/auth/status")).json()
    assert st == {"setupRequired": True, "hosted": True}
    r = await http.post("/api/auth/setup", json={"name": "Plat Founder", "email": "founder@host.test", "password": PW})
    assert r.status_code == 200
    u = r.json()["user"]
    assert u["platformAdmin"] is True and u["business"] is None and u["businesses"] == []
    assert registry.memberships_of(u["id"]) == []
    assert (await http.get("/api/platform/overview", headers=H(r.json()["token"]))).status_code == 200
    assert (await http.get("/api/products", headers=H(r.json()["token"]))).status_code == 403
    monkeypatch.delenv("DAKBOX_HOSTED")
    assert (await http.get("/api/auth/status")).json()["hosted"] is False
