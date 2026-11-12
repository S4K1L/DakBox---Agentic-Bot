"""The Claude API key, changeable from the owner panel: checked with Anthropic before saving, stored encrypted, never shown again,
used by the very next message, and removable. Anthropic is a stand-in; nothing here talks to the real service."""
import httpx
import pytest

from app import aikey, db
from app.agent import agent
from app.main import app
from tests.conftest import say, texts
from tests.test_auth import H, member_token, setup_owner

GOOD = "sk-ant-api03-GOODKEY00000000000000AB12"
OTHER = "sk-ant-api03-OTHERKEY0000000000000CD34"


@pytest.fixture
async def http():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture(autouse=True)
def anthropic(monkeypatch):
    """A stand-in for Anthropic's model list. Which keys are valid, and what models they see, is decided here."""
    st = {"good": {GOOD, OTHER}, "models": [agent.MODEL, "claude-haiku-5-5"], "calls": [], "down": False, "limit": set()}

    def handler(req: httpx.Request) -> httpx.Response:
        if st["down"]:
            raise httpx.ConnectError("no network")
        key = req.headers.get("x-api-key", "")
        st["calls"].append((str(req.url.host), key))
        if key in st["limit"]:
            return httpx.Response(429, json={"error": {"type": "rate_limit_error"}})
        if key not in st["good"]:
            return httpx.Response(401, json={"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}})
        return httpx.Response(200, json={"data": [{"id": m} for m in st["models"]]})

    aikey.set_transport(httpx.MockTransport(handler))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    db.set_setting("ai_key", None)
    db.set_setting("ai_status", {})
    agent._client = None
    yield st
    aikey.set_transport(None)
    db.set_setting("ai_key", None)
    db.set_setting("ai_status", {})
    agent._client = None


async def owner(http):
    return H(await setup_owner(http))


async def test_with_no_key_the_offline_engine_answers_and_the_panel_says_so(http):
    h = await owner(http)
    s = (await http.get("/api/assistant/key", headers=h)).json()
    assert s["source"] is None and s["masked"] is None and s["engine"] == "offline"
    assert (await http.get("/api/me", headers=h)).json()["engine"] == "offline"


async def test_a_good_key_is_checked_saved_encrypted_and_used_at_once(http, anthropic):
    h = await owner(http)
    r = await http.put("/api/assistant/key", headers=h, json={"key": f"  {GOOD}  "})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["source"] == "panel" and d["masked"] == "…AB12" and d["engine"] == "claude" and d["modelAvailable"] is True
    assert anthropic["calls"] == [("api.anthropic.com", GOOD)]                       # it was checked with Anthropic, over the fixed address
    assert GOOD not in r.text
    raw = db.get("SELECT value FROM settings WHERE key='ai_key'")["value"]
    assert GOOD not in raw and "AB12" not in raw                                      # stored encrypted
    assert (await http.get("/api/me", headers=h)).json()["engine"] == "claude"
    assert (await http.get("/api/settings", headers=h)).json()["keySource"] == "panel"
    assert agent.has_model() and agent._claude().api_key == GOOD
    a = db.get("SELECT * FROM audit WHERE action='assistant.key_set'")
    assert "AB12" in a["detail"] and GOOD not in (a["detail"] + (a["target"] or ""))
    for path in ("/api/assistant/key", "/api/settings", "/api/me"):
        assert GOOD not in (await http.get(path, headers=h)).text


async def test_replacing_the_key_takes_effect_on_the_next_message_without_a_restart(http):
    h = await owner(http)
    await http.put("/api/assistant/key", headers=h, json={"key": GOOD})
    first = agent._claude()
    assert first.api_key == GOOD
    await http.put("/api/assistant/key", headers=h, json={"key": OTHER})
    assert agent._claude().api_key == OTHER and agent._claude() is not first
    assert (await http.get("/api/assistant/key", headers=h)).json()["masked"] == "…CD34"


async def test_a_wrong_or_malformed_key_is_refused_and_changes_nothing(http, anthropic):
    h = await owner(http)
    await http.put("/api/assistant/key", headers=h, json={"key": GOOD})
    for bad in ("hello", "sk-openai-1234567890123456789", "sk-ant-short", "x" * 300, "sk-ant-api03-" + "a" * 600):
        r = await http.put("/api/assistant/key", headers=h, json={"key": bad})
        assert r.status_code in (400, 422), (bad, r.status_code)
    n = len(anthropic["calls"])
    r = await http.put("/api/assistant/key", headers=h, json={"key": "sk-ant-api03-WRONGKEY00000000000000ZZ99"})
    assert r.status_code == 400 and "rejected" in r.json()["detail"]
    assert len(anthropic["calls"]) == n + 1                                          # only well-formed keys are ever sent to Anthropic
    assert (await http.get("/api/assistant/key", headers=h)).json()["masked"] == "…AB12"      # the old key still stands


async def test_when_anthropic_cannot_be_reached_the_owner_can_still_save_but_must_say_so(http, anthropic):
    h = await owner(http)
    anthropic["down"] = True
    r = await http.put("/api/assistant/key", headers=h, json={"key": GOOD})
    assert r.status_code == 502 and "Could not reach Claude (Anthropic)" in r.json()["detail"] and agent.has_model() is False
    r = await http.put("/api/assistant/key", headers=h, json={"key": GOOD, "skipCheck": True})
    assert r.status_code == 200 and r.json()["engine"] == "claude"
    assert "saved without checking" in db.get("SELECT detail FROM audit WHERE action='assistant.key_set'")["detail"]
    anthropic["down"] = False
    anthropic["limit"].add(GOOD)
    r = await http.post("/api/assistant/key/check", headers=h)
    assert r.status_code == 502 and "too many requests" in r.json()["detail"]


async def test_a_key_that_cannot_use_the_model_is_flagged(http, anthropic):
    h = await owner(http)
    anthropic["models"] = ["claude-old-1"]
    r = await http.put("/api/assistant/key", headers=h, json={"key": GOOD})
    assert r.status_code == 200 and r.json()["modelAvailable"] is False


async def test_the_server_environment_key_is_the_fallback_and_the_panel_key_wins(http, monkeypatch):
    h = await owner(http)
    monkeypatch.setenv("ANTHROPIC_API_KEY", OTHER)
    s = (await http.get("/api/assistant/key", headers=h)).json()
    assert s["source"] == "environment" and s["masked"] == "…CD34" and s["engine"] == "claude"
    assert (await http.delete("/api/assistant/key", headers=h)).status_code == 409           # nothing saved in the panel to remove
    await http.put("/api/assistant/key", headers=h, json={"key": GOOD})
    assert aikey.get_key() == GOOD and (await http.get("/api/assistant/key", headers=h)).json()["source"] == "panel"
    r = await http.delete("/api/assistant/key", headers=h)
    assert r.json()["source"] == "environment" and aikey.get_key() == OTHER and agent._claude().api_key == OTHER
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert (await http.get("/api/assistant/key", headers=h)).json()["engine"] == "offline"


async def test_removing_the_panel_key_returns_to_the_offline_engine(http):
    h = await owner(http)
    await http.put("/api/assistant/key", headers=h, json={"key": GOOD})
    r = await http.delete("/api/assistant/key", headers=h)
    assert r.status_code == 200 and r.json()["engine"] == "offline" and r.json()["masked"] is None
    assert db.get("SELECT 1 FROM audit WHERE action='assistant.key_removed'")


async def test_only_people_who_may_change_settings_can_touch_the_key(http):
    o = await setup_owner(http)
    agent_t = await member_token(http, o, "agent")
    viewer = await member_token(http, o, "viewer")
    for t in (agent_t, viewer):
        assert (await http.get("/api/assistant/key", headers=H(t))).status_code == 403
        assert (await http.put("/api/assistant/key", headers=H(t), json={"key": GOOD})).status_code == 403
        assert (await http.delete("/api/assistant/key", headers=H(t))).status_code == 403
    assert (await http.get("/api/assistant/key")).status_code == 401
    assert (await http.put("/api/assistant/key", json={"key": GOOD})).status_code == 401


async def test_a_key_that_stops_working_is_reported_and_customers_still_get_an_answer(http, monkeypatch):
    h = await owner(http)
    await http.put("/api/assistant/key", headers=h, json={"key": GOOD})

    class Boom(Exception):
        status_code = 401

    async def failing(*a, **k):
        raise Boom("secret detail that must not leak " + GOOD)

    monkeypatch.setattr(agent, "_run_claude", failing)
    cid = await say("ch_web", "web_ai1", "Guest A", "Do you have a navy water bottle?")
    assert texts(cid, "assistant")                                                    # the offline engine answered
    s = (await http.get("/api/assistant/key", headers=h)).json()
    assert "rejected the key" in s["lastError"] and GOOD not in str(s) and "secret detail" not in str(s)
    assert db.get("SELECT engine FROM agent_runs ORDER BY id DESC")["engine"] == "offline-fallback"

    async def working(*a, **k):
        return "Hello from Claude", None, None, []

    monkeypatch.setattr(agent, "_run_claude", working)
    await say("ch_web", "web_ai1", "Guest A", "ok thanks")
    s = (await http.get("/api/assistant/key", headers=h)).json()
    assert s["lastError"] is None and s["lastOkAt"]
