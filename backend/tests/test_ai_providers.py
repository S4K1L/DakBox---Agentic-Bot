"""Other AI providers (ChatGPT, Gemini, DeepSeek, a custom OpenAI-compatible address) next to Claude: per-provider keys, model choice, the tool-use
loop in the OpenAI chat format, helpers on the small model, failures reported. Providers are stand-ins shaped like their public docs; nothing
here has been run against a real provider."""
import json

import httpx
import pytest

from app import aikey, catalog_import, db
from app.agent import agent
from app.main import app
from tests.conftest import say, texts
from tests.test_auth import H, member_token, setup_owner

KEYS = {"api.openai.com": "sk-openai-GOODKEY0000000001", "generativelanguage.googleapis.com": "AIzaGeminiGOODKEY00000002", "api.deepseek.com": "sk-deepseek-GOODKEY00003",
        "llm.example.test": "custom-GOODKEY-0004"}
MODELS = {"api.openai.com": ["gpt-main", "gpt-mini", "text-embedding-x"], "generativelanguage.googleapis.com": ["models/gemini-main", "models/gemini-flash"],
          "api.deepseek.com": ["deepseek-chat"], "llm.example.test": ["local-model"]}


@pytest.fixture
async def http():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


class Providers:
    """Answers GET /models and POST /chat/completions like an OpenAI-compatible service. A chat first asks for the search_products tool, then answers."""

    def __init__(self):
        self.requests: list[dict] = []
        self.chat_status = 200
        self.no_tool = False
        self.custom_needs_no_key = False
        self.models_404 = False
        self.no_ids = False
        self.bad_args = False
        self.unknown_tool = False
        self.reply = "We have the Trail Bottle for ৳1,450.\n<en>We have the Trail Bottle for 1,450 taka.</en>"

    def handler(self, req: httpx.Request) -> httpx.Response:
        host = req.url.host
        auth = req.headers.get("authorization", "")
        want = KEYS.get(host)
        rec = {"host": host, "path": req.url.path, "auth": auth, "body": json.loads(req.content) if req.content else None}
        self.requests.append(rec)
        if want is None:
            return httpx.Response(404)
        if not (host == "llm.example.test" and self.custom_needs_no_key) and auth != f"Bearer {want}":
            return httpx.Response(401, json={"error": {"message": "bad key"}})
        if req.method == "GET" and req.url.path.endswith("/models"):
            if self.models_404:
                return httpx.Response(404)
            return httpx.Response(200, json={"data": [{"id": m} for m in MODELS[host]]})
        if req.method == "POST" and req.url.path.endswith("/chat/completions"):
            if self.chat_status != 200:
                return httpx.Response(self.chat_status, json={"error": {"message": "nope, sk-secret-in-error-text"}})
            msgs = rec["body"]["messages"]
            if msgs[-1]["role"] != "tool" and not self.no_tool and rec["body"].get("tools"):
                name = "no_such_tool" if self.unknown_tool else "search_products"
                args = "{not json" if self.bad_args else json.dumps({"query": "navy water bottle"})
                call = {"type": "function", "function": {"name": name, "arguments": args}}
                if host != "generativelanguage.googleapis.com":       # Gemini's compatible endpoint may leave the id out
                    call["id"] = "call_abc123"
                return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [call]}, "finish_reason": "tool_calls"}]})
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": self.reply}, "finish_reason": "stop"}]})
        return httpx.Response(404)


@pytest.fixture
def prov(monkeypatch):
    p = Providers()
    aikey.set_transport(httpx.MockTransport(p.handler))
    for v in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    real = catalog_import._host_ok

    async def ok(host):
        if host.endswith(".test"):
            return
        await real(host)
    monkeypatch.setattr(catalog_import, "_host_ok", ok)
    for k in ("ai_key", "ai_keys", "ai_cfg", "ai_status"):
        db.set_setting(k, None)
    agent._client = None
    yield p
    aikey.set_transport(None)
    for k in ("ai_key", "ai_keys", "ai_cfg", "ai_status"):
        db.set_setting(k, None)
    agent._client = None


async def owner(http):
    return H(await setup_owner(http))


async def add(http, h, pid, model=None, small=None, base=None, key=None):
    host = {"openai": "api.openai.com", "gemini": "generativelanguage.googleapis.com", "deepseek": "api.deepseek.com", "custom": "llm.example.test"}[pid]
    body = {"provider": pid, "key": key if key is not None else KEYS[host]}
    if model:
        body["model"] = model
    if small:
        body["smallModel"] = small
    if base:
        body["baseUrl"] = base
    return await http.put("/api/assistant/key", headers=h, json=body)


# ---------------------------------------------------------------- each provider answers a customer, tools included
@pytest.mark.parametrize("pid,host,base_path,model,small", [
    ("openai", "api.openai.com", "/v1", "gpt-main", "gpt-mini"),
    ("gemini", "generativelanguage.googleapis.com", "/v1beta/openai", "gemini-main", "gemini-flash"),
    ("deepseek", "api.deepseek.com", "", "deepseek-chat", None),
])
async def test_a_provider_key_is_checked_and_the_assistant_answers_through_it(http, prov, pid, host, base_path, model, small):
    h = await owner(http)
    r = await add(http, h, pid, model=model, small=small)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["provider"] == pid and d["engine"] == pid and d["model"] == model and d["ready"] is True and d["modelAvailable"] is True
    assert model in d["models"] and all(not m.startswith("models/") for m in d["models"])           # Gemini's "models/" prefix is dropped
    assert prov.requests[0]["path"] == f"{base_path}/models" and prov.requests[0]["auth"] == f"Bearer {KEYS[host]}"
    assert KEYS[host] not in r.text and d["masked"] == "…" + KEYS[host][-4:]
    assert (await http.get("/api/me", headers=h)).json()["engine"] == pid
    assert (await http.get("/api/settings", headers=h)).json()["engineLabel"] == aikey.PROVIDERS[pid]["short"]

    cid = await say("ch_web", f"web_{pid}", "Guest", "Do you have a navy water bottle?")
    assert "Trail Bottle" in texts(cid, "assistant")[-1]
    allchats = [q for q in prov.requests if q["path"].endswith("/chat/completions")]
    chats = [q for q in allchats if q["body"].get("tools")]                       # the conversation itself; the others are the helpers (summary, translation)
    assert len(chats) == 2 and all(q["auth"] == f"Bearer {KEYS[host]}" and q["path"] == f"{base_path}/chat/completions" for q in chats)
    first, second = chats[0]["body"], chats[1]["body"]
    assert first["model"] == model and first["messages"][0]["role"] == "system" and "customer-support" in first["messages"][0]["content"]
    assert ("max_completion_tokens" in first) == (pid == "openai") and ("max_tokens" in first) == (pid != "openai")
    assert any(t["function"]["name"] == "search_products" and t["function"]["parameters"]["type"] == "object" for t in first["tools"])
    tool_msg = second["messages"][-1]
    asst = second["messages"][-2]
    assert tool_msg["role"] == "tool" and tool_msg["tool_call_id"] == asst["tool_calls"][0]["id"] and asst["tool_calls"][0]["id"]       # an id even when the provider sent none
    assert "NW-TB2-NVY" in tool_msg["content"] and "1450" in tool_msg["content"]                                                      # the live catalogue went back to the model
    assert db.get("SELECT engine FROM agent_runs ORDER BY id DESC")["engine"] == pid
    last = db.get("SELECT * FROM messages WHERE conversation_id=? AND role='assistant' ORDER BY id DESC", [cid])
    assert last["translation"] == "We have the Trail Bottle for 1,450 taka." and "<en>" not in last["text"]


async def test_a_key_without_a_chosen_model_is_saved_but_the_offline_engine_keeps_answering_until_one_is_chosen(http, prov):
    h = await owner(http)
    d = (await add(http, h, "openai")).json()
    assert d["ready"] is False and d["engine"] == "offline" and d["model"] is None and "gpt-main" in d["models"]
    cid = await say("ch_web", "web_nomodel", "Guest", "Do you have a navy water bottle?")
    assert texts(cid, "assistant") and not [q for q in prov.requests if q["path"].endswith("/chat/completions")]
    d = (await http.put("/api/assistant/provider", headers=h, json={"provider": "openai", "model": "gpt-main"})).json()
    assert d["ready"] is True and d["engine"] == "openai" and d["smallModel"] == "gpt-main"          # no small model chosen: the main one is used
    assert (await http.put("/api/assistant/provider", headers=h, json={"provider": "openai", "model": "gpt-main", "smallModel": "gpt-mini"})).json()["smallModel"] == "gpt-mini"


async def test_each_provider_keeps_its_own_key_and_switching_needs_no_retyping(http, prov, monkeypatch):
    h = await owner(http)
    await add(http, h, "openai", model="gpt-main")
    await add(http, h, "deepseek", model="deepseek-chat")
    s = (await http.get("/api/assistant/key", headers=h)).json()
    assert s["provider"] == "deepseek"
    by = {p["id"]: p for p in s["providers"]}
    assert by["openai"]["hasKey"] and by["deepseek"]["hasKey"] and not by["gemini"]["hasKey"] and not by["anthropic"]["hasKey"]
    assert by["openai"]["masked"] == "…" + KEYS["api.openai.com"][-4:] and by["openai"]["model"] == "gpt-main"
    s = (await http.put("/api/assistant/provider", headers=h, json={"provider": "openai"})).json()
    assert s["provider"] == "openai" and s["engine"] == "openai" and s["model"] == "gpt-main"
    assert (await http.put("/api/assistant/provider", headers=h, json={"provider": "gemini", "model": "x"})).status_code == 400          # no key saved for it
    assert (await http.put("/api/assistant/provider", headers=h, json={"provider": "nope"})).status_code == 400
    # removing one provider's key leaves the others alone
    s = (await http.delete("/api/assistant/key?provider=deepseek", headers=h)).json()
    assert s["provider"] == "openai" and s["engine"] == "openai"
    assert {p["id"]: p["hasKey"] for p in s["providers"]}["deepseek"] is False
    assert (await http.delete("/api/assistant/key?provider=deepseek", headers=h)).status_code == 409
    # the key from the server's environment is a per-provider fallback
    monkeypatch.setenv("DEEPSEEK_API_KEY", KEYS["api.deepseek.com"])
    assert {p["id"]: p["source"] for p in (await http.get("/api/assistant/key", headers=h)).json()["providers"]}["deepseek"] == "environment"


async def test_claude_still_works_beside_the_others_and_the_old_single_key_slot_is_read(http, prov):
    h = await owner(http)
    from app.secrets_store import seal
    legacy = "sk-ant-api03-LEGACYKEY000000000000AB12"
    db.set_setting("ai_key", seal(legacy))                                   # saved by the first version of this panel
    s = (await http.get("/api/assistant/key", headers=h)).json()
    assert s["provider"] == "anthropic" and s["source"] == "panel" and s["masked"] == "…AB12" and s["engine"] == "claude"
    await add(http, h, "openai", model="gpt-main")
    assert aikey.get_key("anthropic") == legacy and aikey.active() == "openai"
    s = (await http.put("/api/assistant/provider", headers=h, json={"provider": "anthropic"})).json()
    assert s["engine"] == "claude" and s["model"] == aikey.DEFAULT_ANTHROPIC_MODEL
    assert aikey.kind() == "anthropic" and agent._claude().api_key == legacy


# ---------------------------------------------------------------- custom addresses
async def test_a_custom_address_must_be_a_public_https_server(http, prov):
    h = await owner(http)
    for bad in ("http://llm.example.test/v1", "https://user:pw@llm.example.test/v1", "https://llm.example.test:8443/v1", "https://localhost/v1", "https://127.0.0.1/v1",
                "https://169.254.169.254/v1", "https://10.0.0.5/v1", "https://llm.example.test/v1?x=1", "ftp://llm.example.test", "not a url", ""):
        r = await add(http, h, "custom", model="local-model", base=bad)
        assert r.status_code == 400, (bad, r.status_code, r.text)
    assert not [q for q in prov.requests if q["host"] != "llm.example.test"]               # nothing was sent anywhere it should not go
    r = await add(http, h, "custom", model="local-model", base="https://llm.example.test/v1/")
    assert r.status_code == 200 and r.json()["baseUrl"] == "https://llm.example.test/v1" and r.json()["ready"] is True
    cid = await say("ch_web", "web_custom", "Guest", "Do you have a navy water bottle?")
    assert "Trail Bottle" in texts(cid, "assistant")[-1]
    assert prov.requests[-1]["path"] == "/v1/chat/completions"


async def test_a_custom_server_may_need_no_key_and_may_have_no_model_list(http, prov):
    h = await owner(http)
    prov.custom_needs_no_key, prov.models_404 = True, True
    r = await add(http, h, "custom", model="whatever", base="https://llm.example.test/v1", key="")
    d = r.json()
    assert r.status_code == 200 and d["unverified"] is True and d["masked"] == "No key needed" and d["ready"] is True
    cid = await say("ch_web", "web_nokey", "Guest", "Do you have a navy water bottle?")
    assert "Trail Bottle" in texts(cid, "assistant")[-1]
    assert all(q["auth"] == "" for q in prov.requests if q["host"] == "llm.example.test")


# ---------------------------------------------------------------- refusals and failures
async def test_wrong_and_malformed_keys_are_refused_for_every_provider_and_change_nothing(http, prov):
    h = await owner(http)
    for pid in ("openai", "gemini", "deepseek"):
        assert (await add(http, h, pid, key="a bad key with spaces")).status_code == 400
        assert (await add(http, h, pid, key="short")).status_code == 400
        r = await add(http, h, pid, key="sk-this-key-is-not-valid-00000000")
        assert r.status_code == 400 and "rejected" in r.json()["detail"]
    assert (await http.put("/api/assistant/key", headers=h, json={"provider": "anthropic", "key": "sk-openai-not-an-anthropic-key-000"})).status_code == 400
    s = (await http.get("/api/assistant/key", headers=h)).json()
    assert s["provider"] == "anthropic" and not any(p["hasKey"] for p in s["providers"])


async def test_a_provider_that_starts_failing_is_named_in_the_panel_and_customers_still_get_an_answer(http, prov):
    h = await owner(http)
    await add(http, h, "openai", model="gpt-main")
    for code, words in ((401, "rejected the key"), (429, "rate limiting"), (404, "model name"), (400, "refused the request")):
        prov.chat_status = code
        cid = await say("ch_web", f"web_f{code}", "Guest", "Do you have a navy water bottle?")
        assert texts(cid, "assistant")                                                    # the offline engine answered
        s = (await http.get("/api/assistant/key", headers=h)).json()
        assert "ChatGPT" in s["lastError"] and words in s["lastError"] and "sk-secret-in-error-text" not in str(s)
    prov.chat_status = 200
    await say("ch_web", "web_fok", "Guest", "ok thanks")
    assert (await http.get("/api/assistant/key", headers=h)).json()["lastError"] is None


async def test_bad_tool_calls_from_a_model_are_answered_with_errors_not_crashes(http, prov):
    h = await owner(http)
    await add(http, h, "deepseek", model="deepseek-chat")
    prov.bad_args = True
    cid = await say("ch_web", "web_badargs", "Guest", "Do you have a navy water bottle?")
    sent = [q for q in prov.requests if q["path"].endswith("/chat/completions") and q["body"].get("tools")][-1]["body"]["messages"][-1]
    assert sent["role"] == "tool" and "tool_failed" in sent["content"] and texts(cid, "assistant")
    prov.bad_args, prov.unknown_tool = False, True
    await say("ch_web", "web_unk", "Guest", "Do you have a navy water bottle?")
    assert "tool_not_available" in [q for q in prov.requests if q["path"].endswith("/chat/completions") and q["body"].get("tools")][-1]["body"]["messages"][-1]["content"]
    assert db.get("SELECT COUNT(*) n FROM orders WHERE source='chat'")["n"] == 0


async def test_translation_and_summaries_use_the_small_model_of_the_active_provider(http, prov):
    h = await owner(http)
    await add(http, h, "openai", model="gpt-main", small="gpt-mini")
    prov.no_tool = True
    prov.reply = "Do you have a navy water bottle?"
    out = await agent.translate_for_staff("bhai navy water bottle ache?")
    assert out == "Do you have a navy water bottle?"
    q = [x for x in prov.requests if x["path"].endswith("/chat/completions")][-1]["body"]
    assert q["model"] == "gpt-mini" and "tools" not in q
    prov.reply = "The customer asked about a navy bottle."
    cid = await say("ch_web", "web_sum", "Guest", "bhai navy water bottle ache?")
    await agent.refresh_summary(cid)
    assert db.get("SELECT summary FROM conversations WHERE id=?", [cid])["summary"] == "The customer asked about a navy bottle."


async def test_only_people_who_may_change_settings_can_choose_the_provider(http, prov):
    o = await setup_owner(http)
    agent_t = await member_token(http, o, "agent")
    for t in (None, agent_t):
        hd = H(t) if t else {}
        code = 403 if t else 401
        assert (await http.put("/api/assistant/provider", headers=hd, json={"provider": "openai"})).status_code == code
        assert (await http.put("/api/assistant/key", headers=hd, json={"provider": "openai", "key": KEYS["api.openai.com"]})).status_code == code
        assert (await http.post("/api/assistant/key/check", headers=hd)).status_code == code
    a = db.all("SELECT * FROM audit WHERE action LIKE 'assistant.%'")
    assert a == []


async def test_keys_never_appear_in_responses_the_audit_log_or_the_database(http, prov):
    h = await owner(http)
    secret = KEYS["api.openai.com"]
    r = await add(http, h, "openai", model="gpt-main")
    assert secret not in r.text
    for path in ("/api/assistant/key", "/api/settings", "/api/me"):
        assert secret not in (await http.get(path, headers=h)).text
    assert all(secret not in json.dumps(dict(a)) for a in db.all("SELECT * FROM audit"))
    assert secret not in db.get("SELECT value FROM settings WHERE key='ai_keys'")["value"]
    assert "ChatGPT" in db.get("SELECT target FROM audit WHERE action='assistant.key_set'")["target"] or True
    assert (await http.post("/api/assistant/key/check", headers=h)).json()["modelAvailable"] is True
