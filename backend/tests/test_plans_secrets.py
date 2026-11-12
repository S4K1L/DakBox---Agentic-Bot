"""Phase 4 of many businesses: a separate encryption key per business (and the move of older secrets onto it), plans with limits (team seats, products,
AI replies per month), usage counting, and the platform's own AI keys for businesses whose plan allows them. The original install runs on the Unlimited plan."""
import json

import httpx
import pytest
from cryptography.fernet import Fernet

from app import aikey, catalog_import, db, limits, metacfg, registry, secrets_store as ss
from app.agent import agent
from app.main import app
from tests.conftest import say, texts
from tests.test_auth import H, PW, login, setup_owner

PROVIDER_KEY = "sk-platform-OPENAI-0000000001"


@pytest.fixture
async def http():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture(autouse=True)
def businesses(monkeypatch):
    registry.create("Alpha Store", "alpha"), registry.create("Beta Store", "beta")
    for v in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    for k in ("ai_key", "ai_keys", "ai_cfg", "ai_status"):
        db.set_setting(k, None)
    registry.save_platform_ai({"keys": {}, "models": {}})
    agent._client = None
    yield
    db.close_all()
    for r in registry.all_businesses():
        if r["slug"] != "default":
            registry.delete(r["id"])
    registry.save_platform_ai({"keys": {}, "models": {}})
    aikey.set_transport(None)
    for k in ("ai_key", "ai_keys", "ai_cfg", "ai_status"):
        db.set_setting(k, None)
    agent._client = None


class FakeOpenAI:
    """An OpenAI-compatible stand-in: valid key, some models, and a plain chat answer naming the model."""

    def __init__(self):
        self.calls = []

    def handler(self, req: httpx.Request) -> httpx.Response:
        auth = req.headers.get("authorization", "")
        self.calls.append((req.url.path, auth))
        if auth not in (f"Bearer {PROVIDER_KEY}", "Bearer sk-own-key-OPENAI-0000002"):
            return httpx.Response(401, json={"error": {"message": "bad"}})
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "gpt-main"}, {"id": "gpt-mini"}]})
        body = json.loads(req.content)
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": f"Hello from {body['model']} via {auth[-4:]}"}}]})


@pytest.fixture
def fake():
    f = FakeOpenAI()
    aikey.set_transport(httpx.MockTransport(f.handler))
    return f


async def owner(http):
    t = await setup_owner(http)
    me = registry.account_by_email("owner@shop.test")["id"]
    for slug in ("alpha", "beta"):
        registry.add_membership(me, registry.resolve(slug)["id"], "owner")
    return t


async def enter(http, token, slug):
    assert (await http.post("/api/auth/switch", headers=H(token), json={"business": slug})).status_code == 200


# ================================================================ per-business encryption keys
def test_each_business_has_its_own_key_and_a_sealed_value_opens_only_there():
    with db.business("alpha"):
        sealed = ss.seal("alpha-secret")
        assert sealed.startswith("b1.") and "alpha-secret" not in sealed and ss.unseal(sealed) == "alpha-secret"
    with db.business("beta"):
        assert ss.unseal(sealed) is None                                          # the same text, copied into another business, is unreadable
        assert ss.unseal(ss.seal("x")) == "x"
    with db.business("default"):
        assert ss.unseal(sealed) is None
    assert ss._business_key("a") is ss._business_key("a") and ss._business_key("a")._signing_key != ss._business_key("b")._signing_key


def test_a_value_copied_between_businesses_is_not_a_secret_there():
    with db.business("alpha"):
        metacfg.update(app_secret_="alpha-app-secret", verify_token_="alpha-token")
        copied = db.get_setting("meta")
    with db.business("beta"):
        db.set_setting("meta", copied)                                            # a stolen row pasted into another business
        assert metacfg.app_secret() is None and metacfg.verify_token() is None
    with db.business("alpha"):
        assert metacfg.app_secret() == "alpha-app-secret"


def test_older_secrets_open_only_in_the_default_business_and_are_moved_under_its_own_key():
    master = ss._f()
    legacy = master.encrypt(b"legacy-secret").decode()                               # written before businesses had their own keys
    assert ss.is_legacy(legacy)
    with db.business("alpha"):
        assert ss.unseal(legacy) is None                                          # not another business's
    with db.business("default"):
        assert ss.unseal(legacy) == "legacy-secret"
        db.run("DELETE FROM channels WHERE id='ch_legacy'")
        db.run("INSERT INTO channels(id,kind,name,handle,status,health,created_at,credentials) VALUES('ch_legacy','wa','L','L','ok','[]',?,?)", [db.now(), master.encrypt(json.dumps({"access_token": "tok"}).encode()).decode()])
        db.set_setting("meta", {"app_id": "1", "app_secret": master.encrypt(b"app-sec").decode(), "verify_token": master.encrypt(b"ver-tok").decode()})
        db.set_setting("ai_keys", {"openai": master.encrypt(b"sk-legacy-ai-key-0001").decode()})
        db.set_setting("bkash_token_bkash", master.encrypt(json.dumps({"id_token": "t", "exp": 9e12}).encode()).decode())
        db.run("DELETE FROM catalog_sources")
        db.run("INSERT INTO catalog_sources(id,host,url,kind,default_stock,created_at,order_secret) VALUES('cs_l','l.test','https://l.test/','woo',5,?,?)", [db.now(), master.encrypt(b"order-sec").decode()])
    n = ss.rekey_business("default")
    assert n == 6
    with db.business("default"):
        assert db.get("SELECT credentials FROM channels WHERE id='ch_legacy'")["credentials"].startswith("b1.")
        assert metacfg.app_secret() == "app-sec" and metacfg.verify_token() == "ver-tok" and db.get_setting("meta")["app_secret"].startswith("b1.")
        assert aikey.panel_key("openai") == "sk-legacy-ai-key-0001"
        assert db.jl(ss.unseal(db.get("SELECT credentials FROM channels WHERE id='ch_legacy'")["credentials"]), {})["access_token"] == "tok"
        assert ss.unseal(db.get("SELECT order_secret FROM catalog_sources WHERE id='cs_l'")["order_secret"]) == "order-sec"
        assert ss.unseal(db.get_setting("bkash_token_bkash")) is not None
        db.run("DELETE FROM channels WHERE id='ch_legacy'")
        db.run("DELETE FROM catalog_sources")
        db.set_setting("meta", None)
        db.set_setting("ai_keys", None)
        db.run("DELETE FROM settings WHERE key LIKE 'bkash_token_%'")
    assert ss.rekey_business("default") == 0                                           # nothing left to move: safe to repeat


def test_platform_secrets_use_the_master_key_and_are_not_a_businesss_to_open():
    sealed = ss.seal_master("platform-secret")
    assert sealed.startswith("m1.") and ss.unseal_master(sealed) == "platform-secret"
    with db.business("alpha"):
        assert ss.unseal(sealed) is None
    assert ss.unseal_master(ss.seal("x")) is None


def test_with_no_business_selected_a_strict_install_has_no_key_to_encrypt_with():
    import os
    os.environ["DAKBOX_STRICT_BUSINESS"] = "1"
    try:
        with pytest.raises(db.NoBusiness):
            ss.seal("x")
    finally:
        os.environ.pop("DAKBOX_STRICT_BUSINESS")


# ================================================================ plans
def test_the_original_install_is_unlimited_and_new_businesses_start_on_free():
    assert registry.plan_of(registry.default_id())["id"] == "unlimited" and registry.plan_of(registry.default_id())["seats"] is None
    p = registry.plan_of(registry.resolve("alpha")["id"])
    assert (p["id"], p["seats"], p["products"], p["ai_replies"], p["platform_ai"]) == ("free", 3, 100, 100, False)
    assert [x["id"] for x in registry.plans()][:3] == ["free", "standard", "unlimited"]


def test_overrides_replace_the_plans_numbers_for_one_business_only():
    a = registry.resolve("alpha")["id"]
    registry.set_plan("alpha", limits={"seats": 7, "ai_replies": 5, "platform_ai": True})
    p = registry.plan_of(a)
    assert (p["seats"], p["products"], p["ai_replies"], p["platform_ai"], p["overridden"]) == (7, 100, 5, True, ["ai_replies", "platform_ai", "seats"])
    assert registry.plan_of(registry.resolve("beta")["id"])["seats"] == 3
    registry.set_plan("alpha", limits={})
    assert registry.plan_of(a)["seats"] == 3 and registry.plan_of(a)["overridden"] == []
    for bad in ({"seats": -1}, {"products": "ten"}):
        with pytest.raises(registry.RegistryError):
            registry.set_plan("alpha", limits=bad)
    with pytest.raises(registry.RegistryError):
        registry.set_plan("alpha", "nope")


async def test_team_size_follows_the_plan_and_seats_free_up_when_people_leave(http):
    o = await owner(http)
    await http.post("/api/platform/businesses", headers=H(o), json={"name": "Gamma Store", "slug": "gamma"})
    await enter(http, o, "gamma")
    inv = lambda n: http.post("/api/team", headers=H(o), json={"name": f"Person {n}", "email": f"p{n}@shop.test", "role": "agent", "password": "temporary-pass-1"})      # noqa: E731
    assert (await http.get("/api/team", headers=H(o))).json()["seats"] == {"used": 1, "limit": 3, "left": 2}
    assert (await inv(1)).status_code == 200 and (await inv(2)).status_code == 200
    r = await inv(3)
    assert r.status_code == 409 and "allows 3 team members" in r.json()["detail"]
    assert registry.account_by_email("p3@shop.test") is None                          # nothing was created for the refused invite
    p1 = registry.account_by_email("p1@shop.test")["id"]
    assert (await http.patch(f"/api/team/{p1}", headers=H(o), json={"active": False})).status_code == 200
    assert (await inv(3)).status_code == 200                                         # the freed seat is used
    assert (await http.patch(f"/api/team/{p1}", headers=H(o), json={"active": True})).status_code == 409      # no seat to bring them back
    await http.patch("/api/platform/businesses/gamma", headers=H(o), json={"limits": {"seats": 10}})
    assert (await http.patch(f"/api/team/{p1}", headers=H(o), json={"active": True})).status_code == 200
    assert (await http.get("/api/team", headers=H(o))).json()["seats"]["used"] == 4
    # an existing account from another business needs a seat too
    assert (await http.get("/api/plan", headers=H(o))).json()["seats"]["limit"] == 10


async def test_the_original_install_has_no_team_limit(http):
    o = await owner(http)
    for i in range(6):
        assert (await http.post("/api/team", headers=H(o), json={"name": f"Person {i}", "email": f"p{i}@shop.test", "role": "viewer", "password": "temporary-pass-1"})).status_code == 200
    assert (await http.get("/api/team", headers=H(o))).json()["seats"]["limit"] is None


async def test_the_product_limit_stops_new_products_but_never_blocks_changes(http):
    o = await owner(http)
    await http.post("/api/platform/businesses", headers=H(o), json={"name": "Gamma Store", "slug": "gamma"})
    await http.patch("/api/platform/businesses/gamma", headers=H(o), json={"limits": {"products": 2}})
    await enter(http, o, "gamma")
    prod = lambda sku: http.post("/api/products", headers=H(o), json={"name": "Thing", "sku": sku, "price": 100, "stock": 5, "art": "box"})      # noqa: E731
    assert (await prod("A-1")).status_code == 200 and (await prod("A-2")).status_code == 200
    r = await prod("A-3")
    assert r.status_code == 409 and "allows 2 products" in r.json()["detail"]
    assert (await http.put("/api/products/A-1", headers=H(o), json={"name": "Thing 2", "sku": "A-1", "price": 150, "stock": 1, "art": "box"})).status_code == 200
    assert (await http.get("/api/plan", headers=H(o))).json()["products"] == {"used": 2, "limit": 2, "left": 0}
    assert (await http.delete("/api/products/A-2", headers=H(o))).status_code == 200
    assert (await prod("A-3")).status_code == 200


def test_a_website_import_adds_products_only_up_to_the_limit_and_still_updates_the_rest():
    registry.set_plan("alpha", limits={"products": 2})
    items = [catalog_import.Item(source_id=f"s:{i}", name=f"Thing {i}", price=100 + i, in_stock=True) for i in range(4)]
    found = catalog_import.Found("shopify", "https://x.test", "x.test", items=items, complete=True)
    with db.business("alpha"):
        r = catalog_import.apply(found, 5)
        assert (r["added"], r["skipped"]) == (2, 2) and "over your plan's product limit" in r["skippedWhy"]
        found.items[0].price = 999
        r = catalog_import.apply(found, 5)
        assert (r["added"], r["updated"], r["skipped"]) == (0, 2, 2)                  # the two that exist are updated; no room for the rest
        assert db.get("SELECT price FROM products WHERE source_id='s:0'")["price"] == 999
        assert db.get("SELECT COUNT(*) n FROM products")["n"] == 2


# ================================================================ the platform's AI keys and the monthly allowance
async def test_only_the_platform_administrator_manages_plans_usage_and_platform_keys(http, fake):
    o = await owner(http)
    from tests.test_auth import member_token
    agent_t = await member_token(http, o, "agent")
    for method, path, body in (("GET", "/api/platform/plans", None), ("PUT", "/api/platform/plans/team", {"name": "Team"}), ("GET", "/api/platform/usage", None),
                               ("GET", "/api/platform/ai", None), ("PUT", "/api/platform/ai", {"provider": "openai", "key": PROVIDER_KEY}), ("DELETE", "/api/platform/ai?provider=openai", None)):
        assert (await http.request(method, path, headers=H(agent_t), json=body)).status_code == 403, path
        assert (await http.request(method, path, json=body)).status_code == 401, path


async def test_plans_can_be_created_and_businesses_moved_between_them(http):
    o = await owner(http)
    r = await http.put("/api/platform/plans/team", headers=H(o), json={"name": "Team", "seats": 5, "products": 500, "aiReplies": None, "platformAi": True})
    assert r.status_code == 200 and r.json()["plan"] == {"id": "team", "name": "Team", "seats": 5, "products": 500, "aiReplies": None, "platformAi": True, "businesses": 0}
    for bad in ({"name": "x"}, {"name": "Team", "seats": -1}):
        assert (await http.put("/api/platform/plans/team", headers=H(o), json=bad)).status_code == 422
    assert (await http.put("/api/platform/plans/Bad Id", headers=H(o), json={"name": "Team"})).status_code in (400, 404, 422)
    r = await http.post("/api/platform/businesses", headers=H(o), json={"name": "Gamma Store", "slug": "gamma", "plan": "team"})
    assert r.json()["business"]["plan"] == "team" and r.json()["business"]["limits"]["seats"] == 5
    assert (await http.post("/api/platform/businesses", headers=H(o), json={"name": "Delta Store", "plan": "nope"})).status_code == 400
    assert (await http.patch("/api/platform/businesses/alpha", headers=H(o), json={"plan": "standard"})).json()["business"]["limits"]["platformAi"] is True
    assert (await http.patch("/api/platform/businesses/alpha", headers=H(o), json={"plan": "nope"})).status_code == 400
    plans = {p["id"]: p for p in (await http.get("/api/platform/plans", headers=H(o))).json()["items"]}
    assert plans["team"]["businesses"] == 1 and plans["standard"]["businesses"] == 1 and plans["unlimited"]["businesses"] == 1


async def test_a_business_uses_the_platform_key_only_if_its_plan_allows_it_and_the_model_the_platform_chose(http, fake):
    o = await owner(http)
    r = await http.put("/api/platform/ai", headers=H(o), json={"provider": "openai", "key": PROVIDER_KEY, "model": "gpt-main", "smallModel": "gpt-mini"})
    assert r.status_code == 200 and PROVIDER_KEY not in r.text and r.json()["modelAvailable"] is True
    row = {i["id"]: i for i in r.json()["items"]}["openai"]
    assert row["hasKey"] and row["source"] == "stored" and row["masked"] == "…0001" and row["model"] == "gpt-main"
    assert PROVIDER_KEY not in registry._c().execute("SELECT value FROM registry_meta WHERE key='platform_ai'").fetchone()["value"]       # stored encrypted
    await enter(http, o, "alpha")                                                        # alpha is on Free: no platform AI
    s = (await http.get("/api/assistant/key", headers=H(o))).json()
    assert s["platformAllowed"] is False and s["source"] is None and s["engine"] == "offline"
    assert (await http.put("/api/assistant/provider", headers=H(o), json={"provider": "openai"})).status_code == 400          # no key available to it
    await http.patch("/api/platform/businesses/alpha", headers=H(o), json={"plan": "standard"})
    s = (await http.get("/api/assistant/key", headers=H(o))).json()
    assert s["platformAllowed"] is True
    s = (await http.put("/api/assistant/provider", headers=H(o), json={"provider": "openai"})).json()
    assert s["source"] == "platform" and s["model"] == "gpt-main" and s["smallModel"] == "gpt-mini" and s["engine"] == "openai" and s["masked"] == "…0001"
    with db.business("alpha"):
        cid = await say("ch_web", "web_plat", "Guest", "hello there")
        assert "Hello from gpt-main" in texts(cid, "assistant")[-1]
    assert PROVIDER_KEY not in (await http.get("/api/assistant/key", headers=H(o))).text
    assert (await http.delete("/api/platform/ai?provider=openai", headers=H(o))).status_code == 200
    assert (await http.get("/api/assistant/key", headers=H(o))).json()["engine"] == "offline"
    assert (await http.delete("/api/platform/ai?provider=openai", headers=H(o))).status_code == 409


async def test_a_wrong_or_unsupported_platform_key_is_refused(http, fake):
    o = await owner(http)
    for body in ({"provider": "custom", "key": PROVIDER_KEY}, {"provider": "openai", "key": "short"}, {"provider": "openai", "key": "sk-not-valid-key-000000000"}, {"provider": "nope", "key": PROVIDER_KEY}):
        assert (await http.put("/api/platform/ai", headers=H(o), json=body)).status_code in (400, 422)
    assert not any(i["hasKey"] for i in (await http.get("/api/platform/ai", headers=H(o))).json()["items"])


async def test_the_server_environment_key_counts_as_a_platform_key_for_plans_that_allow_it(http, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-ENVKEY0000000000000000EF56")
    o = await owner(http)
    s = (await http.get("/api/assistant/key", headers=H(o))).json()
    assert s["source"] == "environment" and s["engine"] == "claude"                    # the original install: unchanged
    await enter(http, o, "alpha")
    assert (await http.get("/api/assistant/key", headers=H(o))).json()["source"] is None          # Free plan: the server's key is not used
    await http.patch("/api/platform/businesses/alpha", headers=H(o), json={"plan": "standard"})
    assert (await http.get("/api/assistant/key", headers=H(o))).json()["source"] == "environment"
    row = {p["id"]: p for p in (await http.get("/api/platform/ai", headers=H(o))).json()["items"]}["anthropic"]
    assert row["source"] == "environment" and row["masked"] == "…EF56"


async def test_the_monthly_allowance_applies_to_platform_keys_and_never_to_a_businesss_own_key(http, fake, monkeypatch):
    o = await owner(http)
    await http.put("/api/platform/ai", headers=H(o), json={"provider": "openai", "key": PROVIDER_KEY, "model": "gpt-main"})
    await http.patch("/api/platform/businesses/alpha", headers=H(o), json={"plan": "standard", "limits": {"aiReplies": 2}})
    await enter(http, o, "alpha")
    await http.put("/api/assistant/provider", headers=H(o), json={"provider": "openai"})
    a = registry.resolve("alpha")["id"]
    with db.business("alpha"):
        for i in range(2):
            cid = await say("ch_web", f"web_q{i}", "Guest", "hi")
            assert "Hello from gpt-main" in texts(cid, "assistant")[-1]
        assert registry.usage_get(a, "ai_replies") == 2 and limits.ai()["exhausted"] is True
        cid = await say("ch_web", "web_q3", "Guest", "hi again")
        assert "Hello from" not in texts(cid, "assistant")[-1]                            # over the allowance: the offline rules answered
    assert registry.usage_get(a, "ai_replies") == 2
    s = (await http.get("/api/assistant/key", headers=H(o))).json()
    assert s["engine"] == "offline" and s["quota"] == {"used": 2, "limit": 2, "exhausted": True} and "used up" in s["lastError"] and "your own AI key" in s["lastError"]
    plan = (await http.get("/api/plan", headers=H(o))).json()
    assert plan["ai"] == {"used": 2, "limit": 2, "limited": True, "exhausted": True, "planLimit": 2} and plan["plan"]["name"] == "Standard"
    # next month the allowance starts again
    monkeypatch.setattr(registry, "period_now", lambda: "2099-01")
    assert (await http.get("/api/assistant/key", headers=H(o))).json()["engine"] == "openai"
    monkeypatch.undo()
    # the business's own key is never limited, and its replies are still counted
    monkeypatch.setattr(registry, "period_now", registry.period_now)
    r = await http.put("/api/assistant/key", headers=H(o), json={"provider": "openai", "key": "sk-own-key-OPENAI-0000002", "model": "gpt-main"})
    assert r.status_code == 200 and r.json()["source"] == "panel" and r.json()["quota"] is None and r.json()["engine"] == "openai"
    with db.business("alpha"):
        cid = await say("ch_web", "web_own", "Guest", "one more please")
        assert "via 0002" in texts(cid, "assistant")[-1]                                 # answered with its own key, over the platform allowance
    assert registry.usage_get(a, "ai_replies") == 3
    assert (await http.get("/api/plan", headers=H(o))).json()["ai"]["limited"] is False


async def test_usage_is_counted_per_business_and_shown_to_the_platform_administrator(http, fake):
    o = await owner(http)
    await http.put("/api/platform/ai", headers=H(o), json={"provider": "openai", "key": PROVIDER_KEY, "model": "gpt-main"})
    base = registry.usage_get(registry.default_id(), "ai_replies")              # other tests may have counted replies in the original business
    for slug in ("alpha", "beta"):
        await http.patch(f"/api/platform/businesses/{slug}", headers=H(o), json={"plan": "standard"})
        await enter(http, o, slug)
        await http.put("/api/assistant/provider", headers=H(o), json={"provider": "openai"})
    with db.business("alpha"):
        await say("ch_web", "web_a1", "Guest", "hi")
        await say("ch_web", "web_a2", "Guest", "hi")
    with db.business("beta"):
        await say("ch_web", "web_b1", "Guest", "hi")
    items = {i["slug"]: i for i in (await http.get("/api/platform/usage", headers=H(o))).json()["items"]}
    assert items["alpha"]["aiReplies"]["used"] == 2 and items["beta"]["aiReplies"]["used"] == 1 and items["default"]["aiReplies"]["used"] == base
    assert items["alpha"]["plan"] == "Standard" and items["alpha"]["seats"] == {"used": 1, "limit": 10} and items["default"]["aiReplies"]["limit"] is None
    assert items["alpha"]["products"] == {"used": 0, "limit": 1000}


async def test_every_member_can_see_their_plan_but_only_their_own(http):
    o = await owner(http)
    await http.patch("/api/platform/businesses/alpha", headers=H(o), json={"limits": {"seats": 9}})
    p = (await http.get("/api/plan", headers=H(o))).json()
    assert p["plan"]["name"] == "Unlimited" and p["seats"]["limit"] is None
    await enter(http, o, "alpha")
    p = (await http.get("/api/plan", headers=H(o))).json()
    assert p["plan"]["name"] == "Free" and p["seats"] == {"used": 1, "limit": 9, "left": 8} and p["plan"]["overridden"] == ["seats"]
    assert (await http.get("/api/plan")).status_code == 401
