"""Connecting channels through the API: validation against Meta, secrecy of tokens, roles, templates."""
import json

import httpx
import pytest

from app import db, meta, metacfg
from app.main import app
from tests.conftest import make_channel, make_customer, settle
from tests.test_auth import H, member_token, setup_owner
from tools.fake_graph import sign, wa_text

TOKEN = "good-token-ABCDEFGH12345"


@pytest.fixture
async def http():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def connect(http, owner, graph, **kw):
    graph.add_wa("106540352242922", name="Northwind Outdoor")
    body = {"kind": "wa", "externalId": "106540352242922", "accessToken": TOKEN, "wabaId": "102290129340398", **kw}
    return await http.post("/api/channels", headers=H(owner), json=body)


async def test_connect_validates_stores_encrypted_and_subscribes(http, graph):
    owner = await setup_owner(http)
    r = await connect(http, owner, graph)
    assert r.status_code == 200, r.text
    out = r.json()
    ch = out["channel"]
    assert ch["live"] and ch["verifiedName"] == "Northwind Outdoor" and ch["tokenHint"] == "••••2345"
    assert out["subscription"]["ok"] is True
    assert any(c["path"].endswith("/102290129340398/subscribed_apps") for c in graph.calls)
    row = db.get("SELECT credentials FROM channels WHERE id=?", [ch["id"]])
    assert TOKEN not in row["credentials"] and row["credentials"].startswith("b1.gAAAA")   # Fernet ciphertext, not the token


async def test_the_token_never_appears_in_any_response(http, graph):
    owner = await setup_owner(http)
    r = await connect(http, owner, graph)
    blobs = [r.text, (await http.get("/api/channels", headers=H(owner))).text, (await http.get("/api/meta", headers=H(owner))).text,
             (await http.get("/api/meta/diagnostics", headers=H(owner))).text]
    chan = r.json()["channel"]
    blobs.append((await http.post(f"/api/channels/{chan['id']}/check", headers=H(owner))).text)
    assert all(TOKEN not in b and "ABCDEFGH12345" not in b for b in blobs)


async def test_a_bad_token_is_refused_and_nothing_is_saved(http, graph):
    owner = await setup_owner(http)
    before = db.get("SELECT COUNT(*) n FROM channels")["n"]
    r = await connect(http, owner, graph, accessToken="wrong-token-0000000")
    assert r.status_code == 400 and "token" in r.json()["detail"].lower()
    assert db.get("SELECT COUNT(*) n FROM channels")["n"] == before


async def test_ids_that_could_alter_a_url_are_refused(http, graph):
    owner = await setup_owner(http)
    r = await http.post("/api/channels", headers=H(owner), json={"kind": "ms", "externalId": "123/../me", "accessToken": TOKEN})
    assert r.status_code == 400 and graph.calls == []


async def test_whatsapp_needs_the_business_account_id(http, graph):
    owner = await setup_owner(http)
    r = await http.post("/api/channels", headers=H(owner), json={"kind": "wa", "externalId": "106540352242922", "accessToken": TOKEN})
    assert r.status_code == 400 and "Business Account" in r.json()["detail"]


async def test_the_same_account_cannot_be_connected_twice(http, graph):
    owner = await setup_owner(http)
    assert (await connect(http, owner, graph)).status_code == 200
    assert (await connect(http, owner, graph)).status_code == 409


async def test_only_admins_can_connect_but_everyone_can_look(http, graph):
    owner = await setup_owner(http)
    agent = await member_token(http, owner, "agent")
    viewer = await member_token(http, owner, "viewer")
    graph.add_wa("106540352242922")
    body = {"kind": "wa", "externalId": "106540352242922", "accessToken": TOKEN, "wabaId": "102290129340398"}
    assert (await http.post("/api/channels", headers=H(agent), json=body)).status_code == 403
    assert (await http.put("/api/meta", headers=H(agent), json={"appSecret": "x" * 20})).status_code == 403
    assert (await http.get("/api/channels", headers=H(viewer))).status_code == 200
    v = (await http.get("/api/meta", headers=H(agent))).json()
    assert "verifyToken" not in v and "appId" not in v           # agents see the webhook URL but none of the setup values


async def test_meta_app_settings_never_return_the_secret(http, graph):
    owner = await setup_owner(http)
    r = await http.put("/api/meta", headers=H(owner), json={"appId": "1234567890", "appSecret": "super-secret-value-000", "verifyToken": "vt-abc", "publicUrl": "https://shop.example.com/"})
    assert r.status_code == 200
    out = (await http.get("/api/meta", headers=H(owner))).json()
    assert out["appSecretSet"] and out["appSecretHint"] == "••••-000" or out["appSecretHint"].startswith("••••")
    assert "super-secret" not in json.dumps(out) and out["webhookUrl"] == "https://shop.example.com/webhooks/meta" and out["verifyToken"] == "vt-abc"
    assert "super-secret" not in db.get("SELECT value FROM settings WHERE key='meta'")["value"]
    assert (await http.put("/api/meta", headers=H(owner), json={"publicUrl": "http://plain.example.com"})).status_code == 400   # Meta needs https


async def test_check_reports_expiry_and_revocation(http, graph):
    owner = await setup_owner(http)
    await http.put("/api/meta", headers=H(owner), json={"appId": "1234567890", "appSecret": "super-secret-value-000"})
    graph.add_page("555000111")
    r = await http.post("/api/channels", headers=H(owner), json={"kind": "ms", "externalId": "555000111", "accessToken": "expiring-token-123456"})
    ch = r.json()["channel"]
    assert ch["status"] == "warn" and "expires in" in json.dumps(ch["health"]).lower()
    # the token is revoked later
    db.run("UPDATE channels SET credentials=? WHERE id=?", [meta.store_credentials("revoked-token-123456"), ch["id"]])
    res = (await http.post(f"/api/channels/{ch['id']}/check", headers=H(owner))).json()
    assert res["check"]["ok"] is False and res["channel"]["status"] == "danger"


async def test_updating_the_token_revalidates_and_heals_the_channel(http, graph):
    owner = await setup_owner(http)
    ch = (await connect(http, owner, graph)).json()["channel"]
    db.run("UPDATE channels SET status='danger', alert='x', last_error='boom' WHERE id=?", [ch["id"]])
    bad = await http.patch(f"/api/channels/{ch['id']}", headers=H(owner), json={"accessToken": "nonsense-token-00000"})
    assert bad.status_code == 400
    ok = await http.patch(f"/api/channels/{ch['id']}", headers=H(owner), json={"accessToken": "good-NEW-token-000000"})
    assert ok.status_code == 200 and ok.json()["channel"]["status"] in ("ok", "warn") and ok.json()["channel"]["lastError"] is None


async def test_disconnect_wipes_credentials_and_stops_routing(http, graph):
    owner = await setup_owner(http)
    metacfg.update(app_secret_="shh-test-secret")
    ch = (await connect(http, owner, graph)).json()["channel"]
    assert (await http.delete(f"/api/channels/{ch['id']}", headers=H(owner))).status_code == 200
    row = db.get("SELECT * FROM channels WHERE id=?", [ch["id"]])
    assert row["credentials"] is None and row["live"] == 0 and row["status"] == "off"
    raw = json.dumps(wa_text("106540352242922", "8801700000050", "hi")).encode()
    await http.post("/webhooks/meta", content=raw, headers={"x-hub-signature-256": sign(raw, "shh-test-secret")})
    await settle()
    assert db.get("SELECT COUNT(*) n FROM conversations c JOIN identities i ON i.customer_id=c.customer_id WHERE i.external_id='8801700000050'")["n"] == 0


async def test_connecting_and_disconnecting_are_audited(http, graph):
    owner = await setup_owner(http)
    ch = (await connect(http, owner, graph)).json()["channel"]
    await http.delete(f"/api/channels/{ch['id']}", headers=H(owner))
    actions = [a["action"] for a in (await http.get("/api/audit", headers=H(owner))).json()["items"]]
    assert "channel.connect" in actions and "channel.disconnect" in actions


# ---------------------------------------------------------------- WhatsApp templates (the way out of a closed window)
async def _closed_window_conversation(http, graph, owner):
    ch = (await connect(http, owner, graph)).json()["channel"]
    cust = make_customer("wa", "8801700000060", "Late Customer", "+8801700000060")
    from app import store
    conv = store.find_or_create_conversation(cust["id"], ch["id"])
    db.run("UPDATE conversations SET window_expires_at=?, mode='human' WHERE id=?", [db.ago(120), conv["id"]])
    return conv["id"], ch


async def test_template_is_sent_when_the_window_is_closed(http, graph):
    owner = await setup_owner(http)
    cid, ch = await _closed_window_conversation(http, graph, owner)
    free = await http.post(f"/api/conversations/{cid}/messages", headers=H(owner), json={"text": "hello?"})
    assert free.status_code == 409                                   # free text is blocked
    tpls = (await http.get(f"/api/conversations/{cid}/templates", headers=H(owner))).json()["items"]
    assert [t["name"] for t in tpls] == ["order_update", "return_update"]
    r = await http.post(f"/api/conversations/{cid}/template", headers=H(owner), json={"name": "order_update", "language": "en", "params": ["Late", "#1042"]})
    assert r.status_code == 200 and r.json()["delivery"] == "Sent as template"
    sent = graph.outbox[-1]["body"]
    assert sent["type"] == "template" and sent["template"]["name"] == "order_update" and sent["to"] == "+8801700000060"
    last = db.get("SELECT text, delivery FROM messages WHERE conversation_id=? ORDER BY id DESC", [cid])
    assert last["text"] == "Hello Late, your order #1042 is on its way."


async def test_template_validation(http, graph):
    owner = await setup_owner(http)
    cid, _ = await _closed_window_conversation(http, graph, owner)
    wrong = await http.post(f"/api/conversations/{cid}/template", headers=H(owner), json={"name": "order_update", "language": "en", "params": ["only one"]})
    assert wrong.status_code == 400
    pending = await http.post(f"/api/conversations/{cid}/template", headers=H(owner), json={"name": "promo_draft", "language": "en", "params": ["x"]})
    assert pending.status_code == 404                                # PENDING templates are not offered or sent


async def test_demo_whatsapp_still_offers_local_templates(http, graph):
    owner = await setup_owner(http)
    r = await http.post(f"/api/conversations/cv_tahmid/template", headers=H(owner), json={"name": "return_update", "language": "bn", "params": ["তাহমিদ", "#1041"]})
    assert r.status_code == 200 and r.json()["delivery"] == "Simulated" and graph.calls == []


async def test_a_failed_send_is_shown_not_hidden(http, graph):
    owner = await setup_owner(http)
    ch = (await connect(http, owner, graph)).json()["channel"]
    cust = make_customer("wa", "8801700000061", "Casey", "+8801700000061")
    from app import store
    conv = store.find_or_create_conversation(cust["id"], ch["id"])
    db.run("UPDATE conversations SET window_expires_at=?, mode='human' WHERE id=?", [db.ago(-600), conv["id"]])
    r = await http.post(f"/api/conversations/{conv['id']}/messages", headers=H(owner), json={"text": "[[FAIL:131026]]"})
    assert r.status_code == 200 and r.json()["delivery"].startswith("Failed:")
    stored = db.get("SELECT delivery FROM messages WHERE conversation_id=? AND role='human'", [conv["id"]])
    assert stored["delivery"].startswith("Failed:")
    # Meta says the 24h window is closed even though our clock said open: nothing is stored as sent
    r2 = await http.post(f"/api/conversations/{conv['id']}/messages", headers=H(owner), json={"text": "[[FAIL:131047]]"})
    assert r2.status_code == 409
