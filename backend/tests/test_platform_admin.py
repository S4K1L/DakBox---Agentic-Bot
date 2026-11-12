"""Phase 5 of many businesses: the platform administrator's tools (overview, suspend, delete, export, support access, accounts, the platform's own record)
and the setup guide a new business sees."""
import csv
import io
import json
import zipfile

import httpx
import pytest

from app import aikey, db, registry
from app.main import app
from tests.conftest import say
from tests.test_auth import H, member_token, setup_owner


@pytest.fixture
async def http():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture(autouse=True)
def cleanup(monkeypatch):
    for v in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    yield
    db.close_all()
    for b in registry.all_businesses():
        if b["slug"] != "default":
            registry.delete(b["id"])
    aikey.set_transport(None)


async def make(http, o, name, slug=None, **extra):
    r = await http.post("/api/platform/businesses", headers=H(o), json={"name": name, "slug": slug, **extra})
    assert r.status_code == 200, r.text
    return r.json()["business"]


async def enter(http, o, slug):
    assert (await http.post("/api/auth/switch", headers=H(o), json={"business": slug})).status_code == 200


# ================================================================ overview, accounts, record
async def test_overview_counts_businesses_by_status_and_accounts(http):
    o = await setup_owner(http)
    await make(http, o, "Alpha Store", "alpha")
    await make(http, o, "Beta Store", "beta")
    await http.patch("/api/platform/businesses/beta", headers=H(o), json={"status": "suspended"})
    r = (await http.get("/api/platform/overview", headers=H(o))).json()
    assert r["businesses"] == {"total": 3, "active": 2, "trial": 0, "suspended": 1} and r["accounts"] == 1 and r["period"] == registry.period_now()


async def test_the_platforms_record_notes_what_the_administrator_did(http):
    o = await setup_owner(http)
    await make(http, o, "Alpha Store", "alpha", plan="standard")
    await http.patch("/api/platform/businesses/alpha", headers=H(o), json={"name": "Alpha Shop"})
    await http.patch("/api/platform/businesses/alpha", headers=H(o), json={"status": "suspended"})
    log = (await http.get("/api/platform/log", headers=H(o))).json()["items"]
    assert [(x["action"], x["target"]) for x in log[:3]] == [("business.suspended", "alpha"), ("business.rename", "alpha"), ("business.plan", "alpha")] or \
        {x["action"] for x in log} >= {"business.create", "business.rename", "business.suspended"}
    assert all(x["actor"] == "Olive Owner" and x["at"] for x in log)


async def test_accounts_can_be_stopped_and_signed_out_but_not_the_last_administrator(http):
    o = await setup_owner(http)
    agent = await member_token(http, o, "agent")
    items = (await http.get("/api/platform/accounts", headers=H(o))).json()["items"]
    me = next(a for a in items if a["email"] == "owner@shop.test")
    ag = next(a for a in items if a["email"] == "agent@shop.test")
    assert me["platformAdmin"] and ag["businesses"] == [{"slug": "default", "name": "Default business", "role": "agent", "active": True, "status": "active"}]
    assert (await http.patch(f"/api/platform/accounts/{me['id']}", headers=H(o), json={"active": False})).status_code == 400          # not yourself
    assert (await http.get("/api/me", headers=H(agent))).status_code == 200
    assert (await http.patch(f"/api/platform/accounts/{ag['id']}", headers=H(o), json={"signOut": True})).status_code == 200
    assert (await http.get("/api/me", headers=H(agent))).status_code == 401                                                             # signed out of every device
    assert (await http.patch(f"/api/platform/accounts/{ag['id']}", headers=H(o), json={"active": False})).json()["active"] is False
    assert (await http.post("/api/auth/login", json={"email": "agent@shop.test", "password": "correct-horse-battery"})).status_code in (401, 403)
    assert (await http.patch(f"/api/platform/accounts/{ag['id']}", headers=H(o), json={"active": True})).json()["active"] is True
    assert (await http.patch("/api/platform/accounts/nope", headers=H(o), json={"active": False})).status_code == 404
    actions = [x["action"] for x in (await http.get("/api/platform/log", headers=H(o))).json()["items"]]
    assert {"account.stop", "account.allow", "account.signout"} <= set(actions)


async def test_the_new_platform_endpoints_are_for_the_administrator_only(http):
    o = await setup_owner(http)
    agent = await member_token(http, o, "agent")
    for method, path, body in (("GET", "/api/platform/overview", None), ("GET", "/api/platform/accounts", None), ("GET", "/api/platform/log", None),
                               ("PATCH", "/api/platform/accounts/x", {"active": False}), ("POST", "/api/platform/businesses/default/export", None),
                               ("POST", "/api/platform/businesses/default/join", None), ("POST", "/api/platform/businesses/default/leave", None),
                               ("POST", "/api/platform/businesses/default/delete", {"confirm": "default"})):
        assert (await http.request(method, path, headers=H(agent), json=body)).status_code == 403, path
        assert (await http.request(method, path, json=body)).status_code == 401, path


# ================================================================ delete
async def test_deleting_a_business_needs_its_address_and_removes_everything_of_it(http):
    o = await setup_owner(http)
    b = await make(http, o, "Alpha Store", "alpha")
    path = registry.path_of(b["id"])
    import os
    assert os.path.exists(path)
    await enter(http, o, "alpha")
    assert (await http.post("/api/platform/businesses/alpha/delete", headers=H(o), json={"confirm": "wrong"})).status_code == 400
    assert os.path.exists(path)
    r = await http.post("/api/platform/businesses/alpha/delete", headers=H(o), json={"confirm": "ALPHA"})            # the address is not case-sensitive
    assert r.status_code == 200 and not os.path.exists(path)
    me = await http.get("/api/me", headers=H(o))
    assert me.status_code == 200 and me.json()["business"] is None                                              # still signed in, back at the business picker
    assert registry.account_by_email("owner@shop.test") is not None                                             # the person's account stays
    assert "alpha" not in [x["slug"] for x in (await http.get("/api/platform/businesses", headers=H(o))).json()["items"]]
    assert (await http.post("/api/platform/businesses/alpha/delete", headers=H(o), json={"confirm": "alpha"})).status_code == 404
    assert (await http.post("/api/platform/businesses/default/delete", headers=H(o), json={"confirm": "default"})).status_code == 400
    assert any(x["action"] == "business.delete" and x["target"] == "alpha" for x in (await http.get("/api/platform/log", headers=H(o))).json()["items"])


# ================================================================ export
async def test_an_export_is_a_zip_of_csv_tables_without_any_secret(http):
    o = await setup_owner(http)
    await make(http, o, "Alpha Store", "alpha")
    with db.business("alpha"):
        db.run("INSERT INTO products(id,sku,name,price,stock,art) VALUES('p_1','SKU-1','Red saree',1200,5,'box')") if False else None
        from app import secrets_store as ss
        db.run("INSERT INTO channels(id,kind,name,handle,status,health,created_at,credentials) VALUES('ch_x','wa','WhatsApp','+8801','ok','[]',?,?)", [db.now(), ss.seal('{"access_token":"TOPSECRET-TOKEN"}')])
        db.set_setting("ai_keys", {"openai": ss.seal("sk-very-secret-key-123456")})
        db.set_setting("note", {"hello": "world"})
        db.run("INSERT INTO customers(id,name,created_at) VALUES('cu_1','Rina Akter',?)", [db.now()]) if False else None
    r = await http.post("/api/platform/businesses/alpha/export", headers=H(o))
    assert r.status_code == 200 and r.json()["filename"].startswith("alpha-export-") and r.json()["filename"].endswith(".zip")
    url = r.json()["url"]
    got = await http.get(url)                                                                                  # no sign-in header: the link carries its own token
    assert got.status_code == 200 and got.headers["content-type"] == "application/zip" and "attachment" in got.headers["content-disposition"]
    z = zipfile.ZipFile(io.BytesIO(got.content))
    names = set(z.namelist())
    assert {"manifest.json", "channels.csv", "settings.csv", "policies.csv"} <= names and not names & {"users.csv", "sessions.csv", "webhook_log.csv"}
    man = json.loads(z.read("manifest.json"))
    assert man["slug"] == "alpha" and man["rows"]["channels"] == 2 and "left out on purpose" in man["note"]
    blob = b"".join(z.read(n) for n in names)
    assert b"TOPSECRET" not in blob and b"sk-very-secret" not in blob and b"credentials" not in z.read("channels.csv").splitlines()[0]
    settings = list(csv.DictReader(io.StringIO(z.read("settings.csv").decode())))
    assert "ai_keys" not in [s["key"] for s in settings] and "note" in [s["key"] for s in settings]
    assert (await http.get(url)).status_code == 404                                                            # single use
    assert (await http.get("/api/platform/download/not-a-token")).status_code == 404
    assert (await http.post("/api/platform/businesses/nope/export", headers=H(o))).status_code == 404


# ================================================================ support access
async def test_support_access_is_explicit_audited_and_removable(http):
    o = await setup_owner(http)
    b = await make(http, o, "Alpha Store", "alpha")
    registry.remove_membership(registry.account_by_email("owner@shop.test")["id"], b["id"])                    # the administrator is not a member
    assert (await http.post("/api/auth/switch", headers=H(o), json={"business": "alpha"})).status_code == 403
    r = await http.post("/api/platform/businesses/alpha/join", headers=H(o))
    assert r.status_code == 200 and r.json()["role"] == "admin"
    await enter(http, o, "alpha")
    audit = (await http.get("/api/audit?limit=20", headers=H(o))).json()["items"]
    assert any(a["action"] == "support.join" for a in audit)
    assert (await http.post("/api/platform/businesses/alpha/join", headers=H(o))).json()["role"] == "admin"      # joining twice is harmless
    assert (await http.post("/api/platform/businesses/alpha/leave", headers=H(o))).status_code == 200
    assert (await http.post("/api/auth/switch", headers=H(o), json={"business": "alpha"})).status_code == 403
    with db.business("alpha"):
        assert "support.leave" in [a["action"] for a in db.all("SELECT action FROM audit")]
    assert (await http.post("/api/platform/businesses/alpha/leave", headers=H(o))).status_code == 409
    assert (await http.post("/api/platform/businesses/nope/join", headers=H(o))).status_code == 404


async def test_the_only_owner_cannot_leave_their_own_business(http):
    o = await setup_owner(http)
    await make(http, o, "Alpha Store", "alpha")
    r = await http.post("/api/platform/businesses/alpha/leave", headers=H(o))
    assert r.status_code == 409 and "only owner" in r.json()["detail"]


# ================================================================ the setup guide
async def test_a_new_business_starts_with_the_guide_and_each_step_follows_the_real_data(http):
    o = await setup_owner(http)
    await make(http, o, "Alpha Store", "alpha")
    await enter(http, o, "alpha")
    g = (await http.get("/api/onboarding", headers=H(o))).json()
    assert g["show"] is True and g["done"] == 0 and g["total"] == 5 and [s["id"] for s in g["steps"]] == ["about", "products", "channel", "ai", "test"] and not g["complete"]
    r = await http.put("/api/settings", headers=H(o), json={"storeAbout": "handloom sarees and panjabis"})
    assert r.status_code == 200, r.text
    with db.business("alpha"):
        db.run("INSERT INTO products(id,sku,name,price,stock,art) VALUES('p_1','S-1','Red saree',1200,5,'box')")
    steps = {s["id"]: s for s in (await http.get("/api/onboarding", headers=H(o))).json()["steps"]}
    assert steps["about"]["done"] and steps["products"]["done"] and not steps["channel"]["done"] and not steps["ai"]["done"] and not steps["test"]["done"]


async def test_a_test_message_the_assistant_answers_completes_the_last_step(http):
    o = await setup_owner(http)
    await make(http, o, "Alpha Store", "alpha")
    await enter(http, o, "alpha")
    with db.business("alpha"):
        await say("ch_web", "web_g1", "Guest", "hello")
    steps = {s["id"]: s for s in (await http.get("/api/onboarding", headers=H(o))).json()["steps"]}
    assert steps["test"]["done"] is True


async def test_channel_and_ai_steps_can_be_skipped_and_the_guide_hidden_for_good(http):
    o = await setup_owner(http)
    await make(http, o, "Alpha Store", "alpha")
    await enter(http, o, "alpha")
    r = await http.post("/api/onboarding/skip", headers=H(o), json={"step": "channel"})
    assert r.status_code == 200 and {s["id"]: s for s in r.json()["steps"]}["channel"] == {"id": "channel", "done": True, "skipped": True}
    assert (await http.post("/api/onboarding/skip", headers=H(o), json={"step": "products"})).status_code == 400            # real work cannot be skipped
    r = await http.post("/api/onboarding/skip", headers=H(o), json={"step": "ai"})
    assert r.json()["done"] == 2
    assert (await http.post("/api/onboarding/dismiss", headers=H(o))).json()["show"] is False
    assert (await http.get("/api/onboarding", headers=H(o))).json()["show"] is False


async def test_the_original_business_and_other_roles_see_no_guide_or_cannot_change_it(http):
    o = await setup_owner(http)
    assert (await http.get("/api/onboarding", headers=H(o))).json()["show"] is False                         # the install that already existed is never nagged
    viewer = await member_token(http, o, "viewer")
    assert (await http.post("/api/onboarding/dismiss", headers=H(viewer))).status_code == 403
    assert (await http.post("/api/onboarding/skip", headers=H(viewer), json={"step": "ai"})).status_code == 403
    assert (await http.get("/api/onboarding")).status_code == 401


async def test_two_businesses_keep_separate_guides(http):
    o = await setup_owner(http)
    await make(http, o, "Alpha Store", "alpha")
    await make(http, o, "Beta Store", "beta")
    await enter(http, o, "alpha")
    await http.post("/api/onboarding/skip", headers=H(o), json={"step": "ai"})
    await http.post("/api/onboarding/dismiss", headers=H(o))
    await enter(http, o, "beta")
    g = (await http.get("/api/onboarding", headers=H(o))).json()
    assert g["show"] is True and g["done"] == 0
