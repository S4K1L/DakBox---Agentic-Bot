"""Sign-in and roles, exercised through the real HTTP app."""
import httpx
import pytest

from app import db
from app.main import app

PW = "correct-horse-battery"


@pytest.fixture
async def http():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


def H(token):
    return {"Authorization": f"Bearer {token}"}


async def setup_owner(http, email="owner@shop.test"):
    r = await http.post("/api/auth/setup", json={"name": "Olive Owner", "email": email, "password": PW})
    assert r.status_code == 200, r.text
    return r.json()["token"]


async def add(http, owner_token, role, email=None, name=None, pw=PW):
    email = email or f"{role}@shop.test"
    r = await http.post("/api/team", headers=H(owner_token), json={"name": name or f"Test {role.title()}", "email": email, "role": role, "password": pw})
    assert r.status_code == 200, r.text
    return r.json()["user"]


async def login(http, email, pw=PW):
    r = await http.post("/api/auth/login", json={"email": email, "password": pw})
    return r


async def member_token(http, owner_token, role):
    """Invite someone, then walk them through the forced password change like a real person would."""
    await add(http, owner_token, role, pw="temporary-pass-1")
    t = (await login(http, f"{role}@shop.test", "temporary-pass-1")).json()["token"]
    r = await http.post("/api/auth/password", headers=H(t), json={"current": "temporary-pass-1", "new": PW})
    assert r.status_code == 200, r.text
    return (await login(http, f"{role}@shop.test")).json()["token"]


# ---------------------------------------------------------------- first run and sign-in
async def test_first_owner_can_be_created_once_only(http):
    assert (await http.get("/api/auth/status")).json() == {"setupRequired": True}
    await setup_owner(http)
    assert (await http.get("/api/auth/status")).json() == {"setupRequired": False}
    r = await http.post("/api/auth/setup", json={"name": "Mallory", "email": "m@evil.test", "password": PW})
    assert r.status_code == 409


async def test_api_requires_a_session(http):
    assert (await http.get("/api/conversations")).status_code == 401
    assert (await http.get("/api/conversations", headers=H("not-a-token"))).status_code == 401
    t = await setup_owner(http)
    assert (await http.get("/api/conversations", headers=H(t))).status_code == 200


async def test_public_surfaces_stay_public(http):
    assert (await http.get("/widget")).status_code == 200
    assert (await http.get("/webhooks/meta")).status_code == 403     # verify handshake refuses, but is reachable
    assert (await http.get("/api/auth/status")).status_code == 200


async def test_wrong_password_is_generic_and_throttled(http):
    await setup_owner(http)
    for _ in range(5):
        r = await login(http, "owner@shop.test", "wrong-password-1")
        assert r.status_code == 401 and r.json()["detail"] == "Wrong email or password."
    ghost = await login(http, "nobody@shop.test", "wrong-password-1")
    assert ghost.status_code == 401 and ghost.json()["detail"] == "Wrong email or password."  # same message for unknown emails
    blocked = await login(http, "owner@shop.test", PW)                 # even the right password waits out the lockout
    assert blocked.status_code == 429


async def test_tokens_are_not_stored_in_plaintext(http):
    t = await setup_owner(http)
    rows = db.all("SELECT token_hash FROM sessions")
    assert rows and all(r["token_hash"] != t and len(r["token_hash"]) == 64 for r in rows)
    stored = db.get("SELECT password_hash FROM users")["password_hash"]
    assert stored.startswith("scrypt$") and PW not in stored


async def test_weak_passwords_are_refused(http):
    for pw in ("short", "password123", "aaaaaaaaaaaa"):
        r = await http.post("/api/auth/setup", json={"name": "Olive", "email": "o@shop.test", "password": pw})
        assert r.status_code == 400, pw


async def test_logout_revokes_the_token(http):
    t = await setup_owner(http)
    await http.post("/api/auth/logout", headers=H(t))
    assert (await http.get("/api/me", headers=H(t))).status_code == 401


# ---------------------------------------------------------------- invited members
async def test_invited_member_must_choose_their_own_password(http):
    owner = await setup_owner(http)
    await add(http, owner, "agent", pw="temporary-pass-1")
    t = (await login(http, "agent@shop.test", "temporary-pass-1")).json()["token"]
    r = await http.get("/api/conversations", headers=H(t))
    assert r.status_code == 403 and r.json()["detail"] == "password_change_required"
    assert (await http.get("/api/me", headers=H(t))).json()["mustChange"] is True
    ok = await http.post("/api/auth/password", headers=H(t), json={"current": "temporary-pass-1", "new": PW})
    assert ok.status_code == 200
    assert (await http.get("/api/conversations", headers=H(t))).status_code == 200


async def test_password_change_signs_out_other_devices(http):
    owner = await setup_owner(http)
    other = (await login(http, "owner@shop.test")).json()["token"]       # a second device
    r = await http.post("/api/auth/password", headers=H(owner), json={"current": PW, "new": "a-brand-new-passphrase"})
    assert r.status_code == 200
    assert (await http.get("/api/me", headers=H(owner))).status_code == 200
    assert (await http.get("/api/me", headers=H(other))).status_code == 401


async def test_deactivated_members_are_locked_out_at_once(http):
    owner = await setup_owner(http)
    agent = await member_token(http, owner, "agent")
    uid = db.get("SELECT id FROM users WHERE role='agent'")["id"]
    assert (await http.get("/api/me", headers=H(agent))).status_code == 200
    assert (await http.patch(f"/api/team/{uid}", headers=H(owner), json={"active": False})).status_code == 200
    assert (await http.get("/api/me", headers=H(agent))).status_code == 401
    assert (await login(http, "agent@shop.test")).status_code == 401


# ---------------------------------------------------------------- what each role may do
async def test_agent_works_the_inbox_but_cannot_touch_money_or_settings(http):
    owner = await setup_owner(http)
    agent = await member_token(http, owner, "agent")
    appr = (await http.get("/api/approvals", headers=H(agent))).json()["items"][0]["id"]
    assert (await http.post(f"/api/approvals/{appr}/decide", headers=H(agent), json={"decision": "approved"})).status_code == 403
    assert (await http.post("/api/orders/%231038/refund", headers=H(agent))).status_code == 403
    assert (await http.put("/api/settings", headers=H(agent), json={"tone": "formal"})).status_code == 403
    assert (await http.put("/api/policies/returns", headers=H(agent), json={"title": "x", "body": "y"})).status_code == 403
    assert (await http.get("/api/team", headers=H(agent))).status_code == 403
    assert (await http.get("/api/audit", headers=H(agent))).status_code == 403
    r = await http.post("/api/conversations/cv_nusrat/messages", headers=H(agent), json={"text": "Hello from the team"})
    assert r.status_code == 200
    last = db.get("SELECT author FROM messages WHERE conversation_id='cv_nusrat' AND role='human' ORDER BY id DESC")
    assert last["author"] == "Test"                                     # the message is signed with the real person, not a fixed name
    assert (await http.post("/api/products/NW-TB2-NVY/stock", headers=H(agent), json={"delta": 1})).status_code == 200


async def test_viewer_is_read_only(http):
    owner = await setup_owner(http)
    viewer = await member_token(http, owner, "viewer")
    assert (await http.get("/api/orders", headers=H(viewer))).status_code == 200
    assert (await http.get("/api/insights", headers=H(viewer))).status_code == 200
    assert (await http.post("/api/conversations/cv_nusrat/messages", headers=H(viewer), json={"text": "hi"})).status_code == 403
    assert (await http.post("/api/conversations/cv_nusrat/draft/approve", headers=H(viewer))).status_code == 403
    assert (await http.post("/api/products/NW-TB2-NVY/stock", headers=H(viewer), json={"delta": 1})).status_code == 403
    assert (await http.post("/api/simulate", headers=H(viewer), json={"channel": "web", "name": "x", "text": "hi"})).status_code == 403


async def test_admin_can_decide_and_refund_but_cannot_touch_an_owner(http):
    owner = await setup_owner(http)
    admin = await member_token(http, owner, "admin")
    appr = (await http.get("/api/approvals", headers=H(admin))).json()["items"][0]["id"]
    assert (await http.post(f"/api/approvals/{appr}/decide", headers=H(admin), json={"decision": "rejected"})).status_code == 200
    assert (await http.post("/api/orders/%231038/refund", headers=H(admin))).status_code == 200
    owner_id = db.get("SELECT id FROM users WHERE role='owner'")["id"]
    assert (await http.patch(f"/api/team/{owner_id}", headers=H(admin), json={"role": "agent"})).status_code == 403
    assert (await http.post(f"/api/team/{owner_id}/reset-password", headers=H(admin), json={"password": "some-new-long-pass"})).status_code == 403
    r = await http.post("/api/team", headers=H(admin), json={"name": "Sneaky Owner", "email": "s@shop.test", "role": "owner", "password": PW})
    assert r.status_code == 403
    actions = [a["action"] for a in (await http.get("/api/audit", headers=H(admin))).json()["items"]]
    assert "approval.rejected" in actions and "order.refund" in actions   # money decisions leave a trail


async def test_there_is_always_one_active_owner(http):
    owner = await setup_owner(http)
    me = (await http.get("/api/me", headers=H(owner))).json()
    assert (await http.patch(f"/api/team/{me['id']}", headers=H(owner), json={"role": "admin"})).status_code == 409
    assert (await http.patch(f"/api/team/{me['id']}", headers=H(owner), json={"active": False})).status_code == 409


async def test_team_emails_are_unique_and_validated(http):
    owner = await setup_owner(http)
    await add(http, owner, "agent")
    dup = await http.post("/api/team", headers=H(owner), json={"name": "Twin", "email": "AGENT@shop.test", "role": "agent", "password": PW})
    assert dup.status_code == 409
    bad = await http.post("/api/team", headers=H(owner), json={"name": "Nope", "email": "not-an-email", "role": "agent", "password": PW})
    assert bad.status_code == 400


async def test_realtime_stream_needs_a_token(http):
    assert (await http.get("/api/events")).status_code == 401
