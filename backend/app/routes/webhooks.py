"""Meta webhooks: WhatsApp Cloud API, Facebook Messenger and Instagram all deliver to /webhooks/meta.

Rules (from Meta's docs): answer the GET handshake with hub.challenge, verify X-Hub-Signature-256 (HMAC-SHA256 of the
raw bytes as received, keyed with the app secret), and return 200 within 5 seconds, so the work happens after the reply.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Request, Response

from .. import db, domain, metacfg, meta, publicbiz, store
from ..events import emit

router = APIRouter()


# ---------------------------------------------------------------- normalised events
@dataclass
class Inbound:
    kind: str                       # wa | ms | ig
    accounts: list[str]             # ids that may identify our channel (phone number ID / page ID / IG ID)
    sender: str
    name: str | None
    text: str
    ext_id: str | None
    media: dict | None = None       # {"type": "image", "caption": "..."}
    wa_phone: bool = False


@dataclass
class Status:
    kind: str
    accounts: list[str]
    ext_id: str | None
    status: str                     # sent | delivered | read | failed
    error: str | None = None
    code: int | None = None
    user: str | None = None
    watermark: int | None = None    # ms since epoch (Messenger delivery/read)


_MEDIA_TYPES = {"image", "video", "audio", "document", "location", "file"}
_IGNORED = {"reaction", "sticker", "unsupported", "system", "ephemeral", "order"}


def parse(body: dict) -> tuple[list[Inbound], list[Status]]:
    inbound: list[Inbound] = []
    statuses: list[Status] = []
    obj = body.get("object")
    if obj == "whatsapp_business_account":
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                v = change.get("value") or {}
                if change.get("field") not in (None, "messages"):
                    continue
                pid = (v.get("metadata") or {}).get("phone_number_id")
                accounts = [str(pid)] if pid else []
                contacts = v.get("contacts") or []
                for m in v.get("messages", []):
                    t = m.get("type")
                    if t in _IGNORED:
                        continue
                    sender = m.get("from") or m.get("from_user_id") or ""
                    c = next((c for c in contacts if c.get("wa_id") == m.get("from") or c.get("user_id") == m.get("from_user_id")), None)
                    name = ((c or {}).get("profile") or {}).get("name")
                    text, media = "", None
                    if t == "text":
                        text = (m.get("text") or {}).get("body", "")
                    elif t == "button":
                        text = (m.get("button") or {}).get("text", "")
                    elif t == "interactive":
                        i = m.get("interactive") or {}
                        text = ((i.get("button_reply") or i.get("list_reply") or {}).get("title")) or ""
                    elif t in _MEDIA_TYPES:
                        blob = m.get(t) or {}
                        cap = blob.get("caption") or blob.get("filename") or blob.get("name") or blob.get("address") or ""
                        media = {"type": t, "caption": cap}
                    else:
                        continue
                    if not sender or not (text or media):
                        continue
                    inbound.append(Inbound("wa", accounts, sender, name, text, m.get("id"), media, wa_phone=sender.isdigit()))
                for st in v.get("statuses", []):
                    err = (st.get("errors") or [{}])[0]
                    statuses.append(Status("wa", accounts, st.get("id"), st.get("status", ""),
                                           (err.get("message") or err.get("title")) if err else None, err.get("code") if err else None))
    elif obj in ("page", "instagram"):
        kind = "ms" if obj == "page" else "ig"
        for entry in body.get("entry", []):
            events = list(entry.get("messaging", []))
            for ch in entry.get("changes", []):  # Instagram can also deliver as changes[].value
                if ch.get("field") in ("messages", "messaging_seen") and isinstance(ch.get("value"), dict):
                    events.append(ch["value"])
            for ev in events:
                accounts = [str(x) for x in (entry.get("id"), (ev.get("recipient") or {}).get("id")) if x]
                sender = (ev.get("sender") or {}).get("id", "")
                msg = ev.get("message")
                if msg:
                    if msg.get("is_echo"):
                        continue  # our own outgoing message echoed back
                    text = msg.get("text") or (msg.get("quick_reply") or {}).get("payload") or ""
                    media = None
                    atts = msg.get("attachments") or []
                    if not text and atts:
                        at = atts[0].get("type", "file")
                        if at in ("image", "video", "audio", "file", "location", "reel", "ig_reel", "share", "story_mention"):
                            media = {"type": "document" if at == "file" else at, "caption": ""}
                    if sender and (text or media):
                        inbound.append(Inbound(kind, accounts, sender, None, text, msg.get("mid"), media))
                elif ev.get("delivery"):
                    d = ev["delivery"]
                    for mid in d.get("mids") or []:
                        statuses.append(Status(kind, accounts, mid, "delivered", user=sender))
                    if not d.get("mids") and d.get("watermark"):
                        statuses.append(Status(kind, accounts, None, "delivered", user=sender, watermark=int(d["watermark"])))
                elif ev.get("read"):
                    r = ev["read"]
                    if r.get("mid"):
                        statuses.append(Status(kind, accounts, r["mid"], "read", user=sender))
                    elif r.get("watermark"):
                        statuses.append(Status(kind, accounts, None, "read", user=sender, watermark=int(r["watermark"])))
    return inbound, statuses


# ---------------------------------------------------------------- security
def _secret() -> str | None:
    return metacfg.app_secret()


def _any_live() -> bool:
    return bool(db.get("SELECT 1 FROM channels WHERE live=1 AND status != 'off' LIMIT 1"))


def signature_ok(raw: bytes, header: str | None) -> bool:
    secret = _secret()
    if not secret:
        # No secret: an unsigned webhook could inject fake customer messages. Only allow it on a demo-only dev install.
        return os.environ.get("DAKBOX_ENV") != "production" and not _any_live()
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header[7:], expected)


def log(kind: str | None, account: str | None, outcome: str, detail: str | None = None) -> None:
    db.run("INSERT INTO webhook_log(at,kind,account_id,outcome,detail) VALUES(?,?,?,?,?)", [db.now(), kind, account, outcome, (detail or "")[:200]])
    db.run("DELETE FROM webhook_log WHERE id NOT IN (SELECT id FROM webhook_log ORDER BY id DESC LIMIT 100)")


# ---------------------------------------------------------------- routing
def find_channel(kind: str, accounts: list[str]):
    if not accounts:
        return None
    marks = ",".join("?" * len(accounts))
    return db.get(f"SELECT * FROM channels WHERE kind=? AND live=1 AND status != 'off' AND external_id IN ({marks}) LIMIT 1", [kind, *accounts])


def _touch(ch) -> None:
    db.run("UPDATE channels SET last_webhook_at=?, webhook_count=webhook_count+1 WHERE id=?", [db.now(), ch["id"]])


_RANK = {"Sent": 1, "Delivered": 2, "Read": 3}
_LABEL = {"sent": "Sent", "delivered": "Delivered", "read": "Read", "played": "Read"}


async def _inbound(ev: Inbound) -> None:
    ch = find_channel(ev.kind, ev.accounts)
    if not ch:
        log(ev.kind, ",".join(ev.accounts), "no_channel", "A message arrived for an account that is not connected here")
        return
    _touch(ch)
    key = f"{ch['id']}:{ev.ext_id}" if ev.ext_id else None
    if key and db.get("SELECT 1 FROM messages WHERE external_id=?", [key]):
        log(ev.kind, ch["external_id"], "duplicate")  # Meta retries and can deliver twice
        return
    name = ev.name
    known = db.get("SELECT c.name FROM identities i JOIN customers c ON c.id=i.customer_id WHERE i.kind=? AND i.external_id=?", [ev.kind, ev.sender])
    if not known and not name:
        name = await meta.fetch_name(ch, ev.sender)
    if not name:
        name = f"{ {'wa': 'WhatsApp', 'ms': 'Messenger', 'ig': 'Instagram'}[ev.kind] } user {ev.sender[-4:]}"
    if ev.kind == "wa" and ev.ext_id:
        asyncio_create(meta.mark_read(ch, ev.ext_id))
    await domain.process_inbound(ch["id"], ev.sender, name if not known else known["name"], ev.text, phone=f"+{ev.sender}" if ev.wa_phone else None, ext_msg_id=key, media=ev.media)
    log(ev.kind, ch["external_id"], "ok")


def asyncio_create(coro) -> None:
    import asyncio
    t = asyncio.create_task(coro)
    domain._tasks.add(t)
    t.add_done_callback(domain._tasks.discard)


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _status(st: Status) -> None:
    ch = find_channel(st.kind, st.accounts)
    if not ch:
        return
    _touch(ch)
    label = _LABEL.get(st.status)
    if st.watermark and st.user:
        # Messenger: everything sent before the watermark was delivered / read.
        cust = db.get("SELECT customer_id AS id FROM identities WHERE kind=? AND external_id=?", [st.kind, st.user])
        conv = store_conv(cust["id"], ch["id"]) if cust else None
        if conv and label:
            allowed = ("Sent",) if label == "Delivered" else ("Sent", "Delivered")
            marks = ",".join("?" * len(allowed))
            db.run(f"UPDATE messages SET delivery=? WHERE conversation_id=? AND role IN ('assistant','human') AND created_at <= ? AND delivery IN ({marks})",
                   [label, conv["id"], _iso(st.watermark), *allowed])
            emit("conversation", id=conv["id"])
        return
    if not st.ext_id:
        return
    m = db.get("SELECT * FROM messages WHERE external_id=?", [f"{ch['id']}:{st.ext_id}"])
    if not m:
        return
    if st.status == "failed":
        reason = f"Failed: {st.error or 'not delivered'}" + (f" ({st.code})" if st.code else "")
        db.run("UPDATE messages SET delivery=? WHERE id=?", [reason, m["id"]])
        store.add_event(m["conversation_id"], "alert", "A message was not delivered", reason, "warn")
        if st.code == 190:
            meta.note_result(ch["id"], meta.MetaError("token", "token", 190))
        return
    if not label:
        return
    cur = _RANK.get(m["delivery"] or "", 0)
    if _RANK[label] > cur and not (m["delivery"] or "").startswith("Failed"):
        db.run("UPDATE messages SET delivery=? WHERE id=?", [label, m["id"]])
        emit("conversation", id=m["conversation_id"])


def store_conv(customer_id: str, channel_id: str):
    return db.get("SELECT id FROM conversations WHERE customer_id=? AND channel_id=? ORDER BY last_message_at DESC LIMIT 1", [customer_id, channel_id])


async def handle(body: dict) -> None:
    try:
        inbound, statuses = parse(body)
        for ev in inbound:
            await _inbound(ev)
        for st in statuses:
            _status(st)
        if not inbound and not statuses:
            log(body.get("object"), None, "ignored")
    except Exception as e:  # never let one bad payload stop the next
        print("[webhook]", repr(e))
        log(body.get("object") if isinstance(body, dict) else None, None, "error", type(e).__name__)


# ---------------------------------------------------------------- routes
def _verify(request: Request) -> Response:
    q = request.query_params
    token = metacfg.verify_token()
    if q.get("hub.mode") == "subscribe" and token and hmac.compare_digest(q.get("hub.verify_token", ""), token):
        return Response(q.get("hub.challenge", ""), media_type="text/plain")
    return Response("forbidden", status_code=403)


async def _receive(request: Request, tasks: BackgroundTasks) -> Response:
    raw = await request.body()
    if len(raw) > 2_000_000:
        return Response("too large", status_code=413)
    if not signature_ok(raw, request.headers.get("x-hub-signature-256")):
        log(None, None, "bad_signature")
        return Response("bad signature", status_code=401)
    try:
        body = await request.json()
    except ValueError:
        return Response("bad json", status_code=400)
    tasks.add_task(handle, body)  # reply now; Meta retries if we take longer than 5 seconds. The task keeps this request's business.
    return Response("ok")


# Each business gives Meta its own address, /webhooks/meta/<slug>, and verifies with its own app secret and token.
# The original /webhooks/meta keeps working for the default business (single-business installs).
@router.get("/webhooks/meta/{slug}")
async def verify_for(slug: str, request: Request):
    publicbiz.enter(slug)
    return _verify(request)


@router.post("/webhooks/meta/{slug}")
async def receive_for(slug: str, request: Request, tasks: BackgroundTasks):
    publicbiz.enter(slug)
    return await _receive(request, tasks)


@router.get("/webhooks/meta")
async def verify(request: Request):
    publicbiz.enter(None)
    return _verify(request)


@router.post("/webhooks/meta")
async def receive(request: Request, tasks: BackgroundTasks):
    publicbiz.enter(None)
    return await _receive(request, tasks)
