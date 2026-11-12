"""Phase 2 of many businesses: global accounts, a membership (and role) per business, sessions that name the business they work in, and a
business switcher. The business of a request comes from the session alone: these tests try hard to read, change or enter a business without belonging to it."""
import asyncio

import httpx
import pytest

from app import db, events, registry
from app.main import app
from tests.test_auth import H, PW, add, login, member_token, setup_owner

PROD = {"name": "Thing", "sku": "T-1", "price": 100, "stock": 5, "art": "box"}


@pytest.fixture
async def http():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture(autouse=True)
def cleanup():
    yield
    db.close_all()
    for b in registry.all_businesses():
        if b["slug"] != registry.DEFAULT_SLUG:
            registry.delete(b["id"])


async def new_business(http, owner, name="Alpha Store", slug="alpha"):
    r = await http.post("/api/platform/businesses", headers=H(owner), json={"name": name, "slug": slug})
    assert r.status_code == 200, r.text
    return r.json()["business"]


async def switch(http, token, ref):
    r = await http.post("/api/auth/switch", headers=H(token), json={"business": ref})
    return r


async def products(http, token):
    return [p["sku"] for p in (await http.get("/api/products", headers=H(token))).json()["items"]]


async def second_account_token(http, owner, email, role="agent", pw="temporary-pass-1"):
    """Add someone to the owner's current business, then walk them through their forced password change."""
    r = await http.post("/api/team", headers=H(owner), json={"name": "Second Person", "email": email, "role": role, "password": pw})
    assert r.status_code == 200, r.text
    t = (await login(http, email, pw)).json()["token"]
    assert (await http.post("/api/auth/password", headers=H(t), json={"current": pw, "new": PW})).status_code == 200
    return (await login(http, email)).json()["token"]


# ---------------------------------------------------------------- switching
async def test_a_person_sees_their_businesses_and_each_has_its_own_data(http):
    owner = await setup_owner(http)
    me = (await http.get("/api/me", headers=H(owner))).json()
    assert me["business"]["slug"] == "default" and [b["slug"] for b in me["businesses"]] == ["default"] and me["platformAdmin"] is True
    await http.post("/api/products", headers=H(owner), json={**PROD, "sku": "DEFAULT-ONLY"})
    a = await new_business(http, owner)
    assert (await http.get("/api/me", headers=H(owner))).json()["business"]["slug"] == "default"       # creating one does not move you
    r = await switch(http, owner, "alpha")
    assert r.status_code == 200 and r.json()["user"]["business"]["id"] == a["id"] and r.json()["user"]["role"] == "owner"
    assert await products(http, owner) == []                                                          # a brand-new business is empty
    await http.post("/api/products", headers=H(owner), json={**PROD, "sku": "ALPHA-ONLY"})
    assert await products(http, owner) == ["ALPHA-ONLY"]
    assert (await http.get("/api/me", headers=H(owner))).json()["store"] == "Alpha Store"
    await switch(http, owner, "default")
    assert "DEFAULT-ONLY" in await products(http, owner) and "ALPHA-ONLY" not in await products(http, owner)
    assert (await http.get("/api/me", headers=H(owner))).json()["store"] != "Alpha Store"
    r = await switch(http, owner, a["id"])                                                           # by id too
    assert r.status_code == 200


async def test_signing_in_again_returns_to_the_business_used_last(http):
    owner = await setup_owner(http)
    await new_business(http, owner)
    await switch(http, owner, "alpha")
    t2 = (await login(http, "owner@shop.test")).json()
    assert t2["user"]["business"]["slug"] == "alpha"
    await switch(http, t2["token"], "default")
    assert (await login(http, "owner@shop.test")).json()["user"]["business"]["slug"] == "default"


async def test_nobody_can_enter_a_business_they_do_not_belong_to(http):
    owner = await setup_owner(http)
    await new_business(http, owner)
    agent = await second_account_token(http, owner, "agent@shop.test")                               # an agent of the default business only
    for ref in ("alpha", "nope", "", "DEFAULT; DROP TABLE x"):
        assert (await switch(http, agent, ref)).status_code in (403, 422)
    assert (await http.get("/api/me", headers=H(agent))).json()["business"]["slug"] == "default"
    # a header or parameter naming another business changes nothing
    await switch(http, owner, "alpha")
    await http.post("/api/products", headers=H(owner), json={**PROD, "sku": "ALPHA-ONLY"})
    for extra in ({"X-Business": "alpha"}, {"X-Business-Id": "alpha"}, {"X-Workspace": "alpha"}):
        r = await http.get("/api/products", headers={**H(agent), **extra})
        assert "ALPHA-ONLY" not in [p["sku"] for p in r.json()["items"]]
    assert "ALPHA-ONLY" not in [p["sku"] for p in (await http.get("/api/products?business=alpha&b=alpha", headers=H(agent))).json()["items"]]


async def test_records_of_another_business_are_not_found_by_id(http):
    owner = await setup_owner(http)
    await new_business(http, owner)
    order = (await http.get("/api/orders", headers=H(owner))).json()["items"][0]["number"]          # the default business has sample orders
    conv = (await http.get("/api/conversations", headers=H(owner))).json()["items"][0]["id"]
    await switch(http, owner, "alpha")
    assert (await http.get("/api/conversations", headers=H(owner))).json()["items"] == []
    assert (await http.get("/api/orders", headers=H(owner))).json()["items"] == []
    assert (await http.get(f"/api/conversations/{conv}", headers=H(owner))).status_code == 404
    assert (await http.post(f"/api/orders/{order.replace('#', '%23')}/cancel", headers=H(owner))).status_code == 404
    assert (await http.get("/api/customers", headers=H(owner))).json()["items"] == []
    assert (await http.get("/api/settings", headers=H(owner))).json()["agent"]["storeName"] == "Alpha Store"


# ---------------------------------------------------------------- roles per business
async def test_a_person_can_be_a_viewer_in_one_business_and_an_admin_in_another(http):
    owner = await setup_owner(http)
    await new_business(http, owner)
    x = await second_account_token(http, owner, "x@shop.test", role="viewer")                       # viewer in default
    await switch(http, owner, "alpha")
    r = await http.post("/api/team", headers=H(owner), json={"name": "Ignored Name", "email": "x@shop.test", "role": "admin", "password": "some-other-pass-123"})
    assert r.status_code == 200 and "keep their own password" in r.json()["note"]
    me = (await http.get("/api/me", headers=H(x))).json()
    assert me["role"] == "viewer" and {b["slug"]: b["role"] for b in me["businesses"]} == {"default": "viewer", "alpha": "admin"}
    assert (await http.put("/api/settings", headers=H(x), json={"tone": "formal"})).status_code == 403
    assert (await switch(http, x, "alpha")).json()["user"]["role"] == "admin"
    assert (await http.put("/api/settings", headers=H(x), json={"tone": "formal"})).status_code == 200


async def test_inviting_someone_who_already_has_an_account_never_changes_their_password_or_name(http):
    owner = await setup_owner(http)
    await new_business(http, owner)
    await second_account_token(http, owner, "x@shop.test", role="viewer")
    await switch(http, owner, "alpha")
    await http.post("/api/team", headers=H(owner), json={"name": "Someone Else", "email": "X@shop.test", "role": "agent", "password": "attacker-chosen-pass-1"})
    assert (await login(http, "x@shop.test", PW)).status_code == 200
    assert (await login(http, "x@shop.test", "attacker-chosen-pass-1")).status_code == 401
    assert registry.account_by_email("x@shop.test")["name"] == "Second Person"
    assert (await http.post("/api/team", headers=H(owner), json={"name": "Dup", "email": "x@shop.test", "role": "agent", "password": PW})).status_code == 409   # already in THIS business


async def test_a_business_admin_cannot_take_over_an_account_that_belongs_to_other_businesses(http):
    owner = await setup_owner(http)
    await new_business(http, owner)
    await second_account_token(http, owner, "shared@shop.test", role="agent")                       # in default...
    await switch(http, owner, "alpha")
    await http.post("/api/team", headers=H(owner), json={"name": "Shared", "email": "shared@shop.test", "role": "agent", "password": PW})   # ...and in alpha
    uid = registry.account_by_email("shared@shop.test")["id"]
    r = await http.post(f"/api/team/{uid}/reset-password", headers=H(owner), json={"password": "attacker-chosen-pass-1"})
    assert r.status_code == 409 and "other businesses" in r.json()["detail"]
    assert (await http.patch(f"/api/team/{uid}", headers=H(owner), json={"name": "Hacked Name"})).status_code == 409
    assert (await login(http, "shared@shop.test", PW)).status_code == 200
    # someone who belongs only here can be managed as before
    await http.post("/api/team", headers=H(owner), json={"name": "Only Here", "email": "only@shop.test", "role": "agent", "password": "temporary-pass-1"})
    oid = registry.account_by_email("only@shop.test")["id"]
    assert (await http.post(f"/api/team/{oid}/reset-password", headers=H(owner), json={"password": "another-temp-pass-1"})).status_code == 200
    assert (await http.patch(f"/api/team/{oid}", headers=H(owner), json={"name": "Renamed Person"})).status_code == 200


async def test_the_team_list_and_team_changes_only_concern_the_current_business(http):
    owner = await setup_owner(http)
    await new_business(http, owner)
    await second_account_token(http, owner, "d@shop.test", role="agent")                             # only in default
    await switch(http, owner, "alpha")
    assert [m["email"] for m in (await http.get("/api/team", headers=H(owner))).json()["items"]] == ["owner@shop.test"]
    did = registry.account_by_email("d@shop.test")["id"]
    assert (await http.patch(f"/api/team/{did}", headers=H(owner), json={"role": "admin"})).status_code == 404       # not a member of alpha: not found
    assert (await http.post(f"/api/team/{did}/reset-password", headers=H(owner), json={"password": PW})).status_code == 404
    await switch(http, owner, "default")
    assert (await http.patch(f"/api/team/{did}", headers=H(owner), json={"role": "viewer"})).status_code == 200


async def test_removing_someone_from_one_business_leaves_their_other_businesses_alone(http):
    owner = await setup_owner(http)
    await new_business(http, owner)
    x = await second_account_token(http, owner, "x@shop.test", role="agent")                        # in default
    await switch(http, owner, "alpha")
    await http.post("/api/team", headers=H(owner), json={"name": "Xavier Xu", "email": "x@shop.test", "role": "agent", "password": PW})
    x_alpha = (await login(http, "x@shop.test")).json()["token"]
    await switch(http, x_alpha, "alpha")
    xid = registry.account_by_email("x@shop.test")["id"]
    assert (await http.get("/api/me", headers=H(x_alpha))).status_code == 200
    assert (await http.patch(f"/api/team/{xid}", headers=H(owner), json={"active": False})).status_code == 200      # deactivated in alpha only
    assert (await http.get("/api/me", headers=H(x_alpha))).status_code == 401                                    # out of alpha at once
    assert (await http.get("/api/me", headers=H(x))).status_code == 200                                           # default untouched
    assert (await login(http, "x@shop.test")).json()["user"]["business"]["slug"] == "default"
    assert (await switch(http, x, "alpha")).status_code == 403


async def test_there_is_always_one_active_owner_in_each_business(http):
    owner = await setup_owner(http)
    await new_business(http, owner)
    await switch(http, owner, "alpha")
    me = (await http.get("/api/me", headers=H(owner))).json()
    assert (await http.patch(f"/api/team/{me['id']}", headers=H(owner), json={"role": "admin"})).status_code == 409
    assert (await http.patch(f"/api/team/{me['id']}", headers=H(owner), json={"active": False})).status_code == 409


# ---------------------------------------------------------------- suspending a business
async def test_a_suspended_business_locks_out_its_people_and_nobody_else(http):
    owner = await setup_owner(http)
    a = await new_business(http, owner)
    await switch(http, owner, "alpha")
    member = await second_account_token(http, owner, "m@shop.test", role="agent")                  # alpha only
    await switch(http, owner, "default")
    assert (await http.get("/api/me", headers=H(member))).json()["business"]["slug"] == "alpha"
    r = await http.patch(f"/api/platform/businesses/{a['id']}", headers=H(owner), json={"status": "suspended"})
    assert r.status_code == 200 and r.json()["business"]["status"] == "suspended"
    assert (await http.get("/api/me", headers=H(member))).status_code == 401                         # moved out at once
    assert (await login(http, "m@shop.test")).status_code == 401                                     # and cannot get back in
    assert (await http.get("/api/orders", headers=H(owner))).status_code == 200                      # other businesses carry on
    assert (await switch(http, owner, "alpha")).status_code == 403
    assert (await http.patch("/api/platform/businesses/default", headers=H(owner), json={"status": "suspended"})).status_code == 400
    await http.patch(f"/api/platform/businesses/{a['id']}", headers=H(owner), json={"status": "active"})
    assert (await login(http, "m@shop.test")).status_code == 200


# ---------------------------------------------------------------- the platform administrator
async def test_platform_endpoints_are_for_the_platform_administrator_only(http):
    owner = await setup_owner(http)
    agent = await member_token(http, owner, "agent")
    for method, path, body in (("GET", "/api/platform/businesses", None), ("POST", "/api/platform/businesses", {"name": "Nope Store"}), ("PATCH", "/api/platform/businesses/default", {"name": "Hijacked"})):
        r1 = await http.request(method, path, headers=H(agent), json=body)
        r2 = await http.request(method, path, json=body)
        assert r1.status_code == 403 and r2.status_code == 401, (path, r1.status_code, r2.status_code)
    assert registry.resolve("default")["name"] == "Default business"
    a = await new_business(http, owner, "Rina's Sarees", "rinas")
    items = (await http.get("/api/platform/businesses", headers=H(owner))).json()["items"]
    assert {b["slug"]: b["members"] for b in items} == {"default": 2, "rinas": 1} and a["owners"] == ["Olive Owner"]
    for bad in ({"name": "x"}, {"name": "Fine Name", "slug": "admin"}, {"name": "Fine Name", "slug": "rinas"}, {"name": "Fine Name", "slug": "Has Space"}):
        assert (await http.post("/api/platform/businesses", headers=H(owner), json=bad)).status_code in (400, 422)
    assert (await http.patch("/api/platform/businesses/rinas", headers=H(owner), json={"name": "Rina Saree House"})).json()["business"]["name"] == "Rina Saree House"
    assert (await http.patch("/api/platform/businesses/zzz", headers=H(owner), json={"name": "X Y"})).status_code == 404


async def test_a_platform_administrator_with_no_business_selected_reads_no_business_data(http):
    owner = await setup_owner(http)
    reg = registry._c()
    pw = await __import__("app.auth", fromlist=["hash_password"]).hash_password(PW)
    admin = registry.create_account("Platform Pat", "pat@platform.test", pw, platform_admin=True)       # not a member of any business
    r = await login(http, "pat@platform.test")
    assert r.status_code == 200 and r.json()["user"]["business"] is None
    t = r.json()["token"]
    me = (await http.get("/api/me", headers=H(t))).json()
    assert me["business"] is None and me["store"] is None and me["permissions"] == []
    for path in ("/api/orders", "/api/products", "/api/conversations", "/api/customers", "/api/settings", "/api/team", "/api/audit"):
        r = await http.get(path, headers=H(t))
        assert r.status_code == 403 and r.json()["detail"] == "business_required", path
    assert (await http.get("/api/platform/businesses", headers=H(t))).status_code == 200
    assert (await switch(http, t, "default")).status_code == 403                                      # being a platform admin is not membership
    reg.execute("DELETE FROM accounts WHERE id=?", [admin["id"]])


# ---------------------------------------------------------------- realtime
def test_realtime_events_reach_only_the_business_they_happened_in():
    a, b = registry.create("Alpha Store", "alpha"), registry.create("Beta Store", "beta")
    qa, qb = events.subscribe(a["id"]), events.subscribe(b["id"])
    with db.business("beta"):
        events.emit("orders", number="#1")
    assert qa.empty() and qb.get_nowait() == {"type": "orders", "number": "#1"}
    with db.business("alpha"):
        events.emit("products")
    assert qa.get_nowait() == {"type": "products"} and qb.empty()
    events.unsubscribe(qa), events.unsubscribe(qb)
    with db.business("alpha"):
        events.emit("orders")                                                         # nobody listening: nothing happens, nothing breaks


# ---------------------------------------------------------------- moving an existing install over
async def test_an_existing_installs_users_become_accounts_in_place(http):
    registry.reset_accounts()
    registry._c().execute("DELETE FROM registry_meta WHERE key LIKE 'legacy_users:%'")
    bid = registry.default_id()
    from app import auth
    h_owner, h_agent = await auth.hash_password(PW), await auth.hash_password("agent-password-1")
    with db.business(bid):
        db.run("DELETE FROM users")
        for uid, em, nm, role, h, act in (("usr_old1", "old-owner@shop.test", "Old Owner", "owner", h_owner, 1), ("usr_old2", "old-agent@shop.test", "Old Agent", "agent", h_agent, 1), ("usr_old3", "gone@shop.test", "Gone Person", "viewer", h_agent, 0)):
            db.run("INSERT INTO users(id,email,name,role,password_hash,must_change,active,hue,created_at) VALUES(?,?,?,?,?,0,?,?,?)", [uid, em, nm, role, h, act, 200, "2026-01-01T00:00:00.000Z"])
        db.run("INSERT INTO sessions(token_hash,user_id,created_at,expires_at,last_seen_at) VALUES('x','usr_old1','2026-01-01','2099-01-01','2026-01-01')")
    registry._migrated = False
    registry._migrate_legacy_once()
    assert registry.account_count() == 3 and registry.account_by_id("usr_old1")["platform_admin"] == 1 and registry.account_by_id("usr_old2")["platform_admin"] == 0
    assert registry.membership("usr_old2", bid)["role"] == "agent" and registry.membership("usr_old3", bid)["active"] == 0
    with db.business(bid):
        assert db.get("SELECT COUNT(*) n FROM sessions")["n"] == 0                      # old per-business sign-ins ended: people sign in once more
    r = await login(http, "old-owner@shop.test")
    assert r.status_code == 200 and r.json()["user"]["role"] == "owner" and r.json()["user"]["platformAdmin"] is True
    assert (await login(http, "old-agent@shop.test", "agent-password-1")).status_code == 200
    assert (await login(http, "gone@shop.test", "agent-password-1")).status_code == 401  # inactive stays inactive
    registry._migrated = False
    registry._migrate_legacy_once()                                                      # running it again changes nothing
    assert registry.account_count() == 3
    assert (await http.get("/api/auth/status")).json()["setupRequired"] is False
    with db.business(bid):
        db.run("DELETE FROM users")
