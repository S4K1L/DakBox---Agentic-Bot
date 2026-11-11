"""Inbound: webhook payloads in the shapes Meta documents, through the real HTTP route."""
import json

import httpx
import pytest

from app import db, meta, metacfg, store
from app.main import app
from tests.conftest import make_channel, settle
from tools.fake_graph import (page_attachment, page_delivery, page_read, page_text, sign, wa_media, wa_reaction, wa_status, wa_text)

SECRET = "shh-test-secret"


@pytest.fixture
async def http():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture(autouse=True)
def app_secret():
    metacfg.update(app_secret_=SECRET, verify_token_="verify-me-please")


async def hook(http, payload, secret=SECRET, ascii_=True, header=True):
    raw = json.dumps(payload, ensure_ascii=ascii_).encode()
    headers = {"content-type": "application/json"}
    if header:
        headers["x-hub-signature-256"] = sign(raw, secret)
    r = await http.post("/webhooks/meta", content=raw, headers=headers)
    await settle()
    return r


def msgs(conv_id):
    return db.all("SELECT * FROM messages WHERE conversation_id=? ORDER BY id", [conv_id])


def conv_for(ext, kind, channel_id=None):
    """The conversation for an identity on a channel of that kind (or a specific channel)."""
    q = "SELECT c.* FROM conversations c JOIN identities i ON i.customer_id=c.customer_id JOIN channels h ON h.id=c.channel_id WHERE i.external_id=? AND i.kind=? AND h.kind=?"
    args = [ext, kind, kind]
    if channel_id:
        q += " AND c.channel_id=?"; args.append(channel_id)
    return db.get(q + " ORDER BY c.last_message_at DESC", args)


# ---------------------------------------------------------------- handshake and signature
async def test_verification_handshake(http):
    ok = await http.get("/webhooks/meta", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me-please", "hub.challenge": "1158201444"})
    assert ok.status_code == 200 and ok.text == "1158201444"
    assert (await http.get("/webhooks/meta", params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "1"})).status_code == 403


async def test_signatures_are_checked_on_the_raw_bytes(http, graph):
    graph.add_wa("106540352242922"); make_channel("wa", "106540352242922")
    p = wa_text("106540352242922", "8801712340042", "hello ä ö å বাংলা")
    assert (await hook(http, p, secret="not-the-secret")).status_code == 401
    assert (await hook(http, p, header=False)).status_code == 401
    assert (await hook(http, p, ascii_=True)).status_code == 200      # escaped unicode on the wire, like Meta sends it
    p2 = wa_text("106540352242922", "8801712340043", "hello ä ö å", wamid="wamid.IN77")
    assert (await hook(http, p2, ascii_=False)).status_code == 200    # raw UTF-8: still the same bytes we were given


async def test_without_an_app_secret_a_live_install_fails_closed(http, graph):
    db.set_setting("meta", {})
    make_channel("wa", "106540352242922")
    raw = json.dumps(wa_text("106540352242922", "8801712340042", "hi")).encode()
    assert (await http.post("/webhooks/meta", content=raw)).status_code == 401
    db.run("DELETE FROM channels WHERE live=1")                        # demo-only dev install: unsigned is allowed
    assert (await http.post("/webhooks/meta", content=raw)).status_code == 200


# ---------------------------------------------------------------- WhatsApp
async def test_whatsapp_message_reaches_the_right_account_and_gets_an_answer(http, graph):
    graph.add_wa("111111111111111"); graph.add_wa("222222222222222")
    a = make_channel("wa", "111111111111111", name="Shop A"); b = make_channel("wa", "222222222222222", name="Shop B")
    await hook(http, wa_text("222222222222222", "8801712340042", "Do you have a navy water bottle?", name="Nusrat Jahan"))
    conv = conv_for("8801712340042", "wa", b["id"])
    assert conv and conv_for("8801712340042", "wa", a["id"]) is None   # routed by phone_number_id, not "the first WhatsApp channel"
    cust = store.customer(conv["customer_id"])
    assert cust["phone"] == "+8801712340042" and cust["name"] == "Nusrat Jahan"
    reply = [m for m in msgs(conv["id"]) if m["role"] == "assistant"][-1]
    assert "Trail Bottle" in reply["text"] and reply["external_id"].startswith(b["id"] + ":wamid.")
    sent = graph.outbox[-1]
    assert sent["node"] == "222222222222222" and sent["to"] == "+8801712340042"      # the answer left through the same number
    read = [c for c in graph.calls if c["body"] and c["body"].get("status") == "read"]
    assert read and read[0]["body"]["message_id"] == "wamid.IN1"


async def test_duplicate_deliveries_are_ignored(http, graph):
    graph.add_wa("111111111111111"); make_channel("wa", "111111111111111")
    p = wa_text("111111111111111", "8801700000020", "Do you have a navy water bottle?", wamid="wamid.SAME")
    await hook(http, p); await hook(http, p)
    conv = conv_for("8801700000020", "wa")
    assert len([m for m in msgs(conv["id"]) if m["role"] == "customer"]) == 1
    assert len([m for m in graph.outbox]) == 1                         # and the customer was not answered twice
    assert db.get("SELECT COUNT(*) n FROM webhook_log WHERE outcome='duplicate'")["n"] == 1


async def test_delivery_receipts_move_forward_and_never_back(http, graph):
    graph.add_wa("111111111111111"); ch = make_channel("wa", "111111111111111")
    await hook(http, wa_text("111111111111111", "8801700000021", "navy water bottle?"))
    conv = conv_for("8801700000021", "wa")
    wamid = graph.outbox[-1]["id"]
    row = lambda: db.get("SELECT delivery FROM messages WHERE external_id=?", [f"{ch['id']}:{wamid}"])["delivery"]
    assert row() == "Sent"
    await hook(http, wa_status("111111111111111", wamid, "delivered", "8801700000021")); assert row() == "Delivered"
    await hook(http, wa_status("111111111111111", wamid, "read", "8801700000021")); assert row() == "Read"
    await hook(http, wa_status("111111111111111", wamid, "delivered", "8801700000021")); assert row() == "Read"   # late, out-of-order receipt


async def test_a_failed_status_shows_the_reason_to_staff(http, graph):
    graph.add_wa("111111111111111"); ch = make_channel("wa", "111111111111111")
    await hook(http, wa_text("111111111111111", "8801700000022", "navy water bottle?"))
    wamid = graph.outbox[-1]["id"]
    err = {"code": 131049, "title": "This message was not delivered to maintain healthy ecosystem engagement.", "message": "This message was not delivered to maintain healthy ecosystem engagement."}
    await hook(http, wa_status("111111111111111", wamid, "failed", "8801700000022", err))
    m = db.get("SELECT delivery, conversation_id FROM messages WHERE external_id=?", [f"{ch['id']}:{wamid}"])
    assert m["delivery"].startswith("Failed: This message was not delivered") and "131049" in m["delivery"]
    assert any(e["text"] == "A message was not delivered" for e in msgs(m["conversation_id"]))


async def test_photos_go_to_a_person_not_the_assistant(http, graph):
    graph.add_wa("111111111111111"); make_channel("wa", "111111111111111")
    await hook(http, wa_media("111111111111111", "8801700000023", "image", "lid cracked"))
    conv = conv_for("8801700000023", "wa")
    assert conv["mode"] == "human" and conv["handoff_reason"] == "sent a photo"
    rows = msgs(conv["id"])
    assert any(m["role"] == "customer" and "[Photo] lid cracked" in m["text"] for m in rows)
    assert any(m["role"] == "assistant" and "received" in m["text"] for m in rows)   # a polite acknowledgement, once
    n = len(graph.outbox)
    await hook(http, wa_media("111111111111111", "8801700000023", "image", "second", wamid="wamid.IN55"))
    assert len(graph.outbox) == n                                      # already with a person: no second auto-reply


async def test_reactions_are_ignored(http, graph):
    graph.add_wa("111111111111111"); make_channel("wa", "111111111111111")
    r = await hook(http, wa_reaction("111111111111111", "8801700000024"))
    assert r.status_code == 200 and conv_for("8801700000024", "wa") is None


async def test_username_only_whatsapp_users_still_work(http, graph):
    graph.add_wa("111111111111111"); make_channel("wa", "111111111111111")
    p = wa_text("111111111111111", "x", "navy water bottle?")
    m = p["entry"][0]["changes"][0]["value"]["messages"][0]
    del m["from"]; m["from_user_id"] = "US.13491208655302741918"
    p["entry"][0]["changes"][0]["value"]["contacts"] = [{"profile": {"name": "Sheena"}, "user_id": "US.13491208655302741918"}]
    await hook(http, p)
    assert conv_for("US.13491208655302741918", "wa") is not None
    assert graph.outbox[-1]["body"].get("recipient") == "US.13491208655302741918"


# ---------------------------------------------------------------- Messenger and Instagram
async def test_messenger_message_name_lookup_and_reply(http, graph):
    graph.add_page("555000111"); make_channel("ms", "555000111", name="Northwind Page")
    await hook(http, page_text("555000111", "7777000201", "Do you have a navy water bottle?"))
    conv = conv_for("7777000201", "ms")
    assert store.customer(conv["customer_id"])["name"] == "Customer 0201"   # name fetched from Graph by PSID
    assert graph.outbox[-1]["to"] == "7777000201" and graph.outbox[-1]["node"] == "555000111"
    assert any(c["body"] and c["body"].get("sender_action") == "typing_on" for c in graph.calls)


async def test_echoes_of_our_own_messages_are_ignored(http, graph):
    graph.add_page("555000111"); make_channel("ms", "555000111")
    await hook(http, page_text("555000111", "7777000202", "Hello from the page inbox", echo=True))
    assert conv_for("7777000202", "ms") is None


async def test_messenger_delivery_and_read_watermarks(http, graph):
    graph.add_page("555000111"); ch = make_channel("ms", "555000111")
    await hook(http, page_text("555000111", "7777000203", "navy water bottle?"))
    conv = conv_for("7777000203", "ms")
    mine = lambda: [m["delivery"] for m in msgs(conv["id"]) if m["role"] == "assistant"]
    assert mine() == ["Sent"]
    future = 4102444800000   # the year 2100: every earlier message counts
    await hook(http, page_delivery("555000111", "7777000203", future)); assert mine() == ["Delivered"]
    await hook(http, page_read("555000111", "7777000203", future)); assert mine() == ["Read"]


async def test_instagram_messages_in_both_envelope_styles(http, graph):
    graph.add_ig("17841400000000000"); make_channel("ig", "17841400000000000", name="northwind.outdoor")
    await hook(http, page_text("17841400000000000", "9990101", "Do you have a navy water bottle?", obj="instagram"))
    assert conv_for("9990101", "ig") is not None and graph.outbox[-1]["channel"] == "ig"
    p = {"object": "instagram", "entry": [{"id": "17841400000000000", "time": 1, "changes": [{"field": "messages", "value": {
        "sender": {"id": "9990102"}, "recipient": {"id": "17841400000000000"}, "timestamp": "1", "message": {"mid": "m_changes_1", "text": "hello there"}}}]}]}
    await hook(http, p)
    assert conv_for("9990102", "ig") is not None


async def test_instagram_photo_goes_to_a_person(http, graph):
    graph.add_ig("17841400000000000"); make_channel("ig", "17841400000000000")
    await hook(http, page_attachment("17841400000000000", "9990103", "image", obj="instagram"))
    assert conv_for("9990103", "ig")["mode"] == "human"


# ---------------------------------------------------------------- unknown accounts and bad input
async def test_unknown_accounts_are_logged_not_crashed_on(http, graph):
    r = await hook(http, wa_text("999999999999999", "8801700000030", "hi"))
    assert r.status_code == 200 and conv_for("8801700000030", "wa") is None
    assert db.get("SELECT outcome FROM webhook_log ORDER BY id DESC")["outcome"] == "no_channel"


async def test_disconnected_channels_stop_receiving(http, graph):
    graph.add_wa("111111111111111"); ch = make_channel("wa", "111111111111111")
    db.run("UPDATE channels SET live=0, status='off' WHERE id=?", [ch["id"]])
    await hook(http, wa_text("111111111111111", "8801700000031", "hi"))
    assert conv_for("8801700000031", "wa") is None


async def test_garbage_bodies_are_rejected_cleanly(http):
    raw = b"not json"
    r = await http.post("/webhooks/meta", content=raw, headers={"x-hub-signature-256": sign(raw, SECRET)})
    assert r.status_code == 400
    raw2 = json.dumps({"object": "something_else"}).encode()
    assert (await http.post("/webhooks/meta", content=raw2, headers={"x-hub-signature-256": sign(raw2, SECRET)})).status_code == 200
