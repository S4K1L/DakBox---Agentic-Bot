"""Talking to Meta: WhatsApp Cloud API, Facebook Messenger and Instagram messaging.

Payloads follow Meta's published docs (checked 2026-11). Everything goes through `_call`, which
- never puts a token in a message, log line or exception text,
- turns Graph errors into a small set of kinds the app can act on (token, window, rate, recipient, param ...),
- can be pointed at a stand-in server with META_GRAPH_BASE / META_IG_GRAPH_BASE, and a test transport.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from . import db, metacfg, store
from .secrets_store import seal, unseal

# ---------------------------------------------------------------- configuration
def graph_base() -> str:
    return os.environ.get("META_GRAPH_BASE", "https://graph.facebook.com").rstrip("/")


def ig_base() -> str:
    return os.environ.get("META_IG_GRAPH_BASE", "https://graph.instagram.com").rstrip("/")


def version() -> str:
    return os.environ.get("META_GRAPH_VERSION", "v26.0")


_transport: httpx.AsyncBaseTransport | None = None


def set_transport(t: httpx.AsyncBaseTransport | None) -> None:
    """Tests inject an httpx.MockTransport here."""
    global _transport
    _transport = t


# Text limits per channel. WhatsApp 4096 chars (docs). Instagram 1000 bytes (docs). Messenger: the limit was not on the
# pages we could read; 2000 characters is the long-standing documented figure, used conservatively.
LIMITS = {"wa": (4096, None), "ms": (2000, None), "ig": (1000, 1000)}

# ---------------------------------------------------------------- errors
@dataclass
class MetaError(Exception):
    kind: str                # token | window | permission | rate | recipient | blocked | param | network | other
    message: str             # safe to show to staff
    code: int | None = None
    subcode: int | None = None
    status: int | None = None

    def __str__(self) -> str:
        return self.message


_WINDOW_SUBCODES = {2534022, 2018278}
_RATE_CODES = {4, 17, 32, 613, 80007, 130429, 131056}
_PARAM_CODES = {100, 131008, 131009, 132000, 132001, 132012, 131051}
_RECIPIENT_CODES = {131026, 551, 133010, 131021}


def classify(status: int | None, body: dict) -> MetaError:
    e = (body or {}).get("error") or {}
    code, sub = e.get("code"), e.get("error_subcode")
    detail = ((e.get("error_data") or {}).get("details") or e.get("message") or "").strip()
    if code in (190, 102) or status == 401:
        return MetaError("token", "The access token is invalid or has expired. Reconnect this channel with a new token.", code, sub, status)
    if code == 131047 or (code == 10 and sub in _WINDOW_SUBCODES):
        return MetaError("window", "More than 24 hours have passed since the customer last wrote, so free-form messages are blocked.", code, sub, status)
    if code in _RATE_CODES:
        return MetaError("rate", "Meta is rate limiting this account. Try again in a minute.", code, sub, status)
    if code in _RECIPIENT_CODES:
        return MetaError("recipient", "Meta could not deliver this to the customer (not reachable on this channel).", code, sub, status)
    if code in (368, 130403):
        return MetaError("blocked", "This account is restricted or blocked by Meta.", code, sub, status)
    if code in (10, 200, 299) or (isinstance(code, int) and 200 <= code <= 299):
        return MetaError("permission", "The token is missing a permission this action needs.", code, sub, status)
    if code in _PARAM_CODES:
        return MetaError("param", f"Meta rejected the request: {detail[:160] or 'invalid parameter'}", code, sub, status)
    return MetaError("other", f"Meta returned an error{f' ({code})' if code else ''}: {detail[:160] or 'unknown'}", code, sub, status)


async def _call(method: str, url: str, *, token: str | None = None, token_in: str = "bearer", json: Any = None, params: dict | None = None, timeout: float = 15.0) -> dict:
    headers: dict[str, str] = {}
    q = dict(params or {})
    if token:
        if token_in == "bearer":
            headers["Authorization"] = f"Bearer {token}"
        else:
            q["access_token"] = token
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=_transport) as c:
            r = await c.request(method, url, json=json, params=q or None, headers=headers)
    except httpx.TimeoutException:
        raise MetaError("network", "Meta did not answer in time.") from None
    except httpx.HTTPError:
        raise MetaError("network", "Could not reach Meta.") from None  # no URL: it may carry a token
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code >= 400 or (isinstance(data, dict) and "error" in data):
        raise classify(r.status_code, data if isinstance(data, dict) else {})
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------- credentials and channel config
def creds(channel) -> dict:
    return db.jl(unseal(channel["credentials"]), {}) if channel["credentials"] else {}


def token_of(channel) -> str | None:
    return (creds(channel) or {}).get("access_token")


def config(channel) -> dict:
    return db.jl(channel["config"], {}) or {}


def is_live(channel) -> bool:
    return bool(channel["live"]) and bool(channel["external_id"]) and bool(token_of(channel)) and channel["status"] != "off"


_ID = re.compile(r"^\d{5,25}$")


def valid_id(v: str) -> bool:
    """Account IDs go into URL paths, so only digits are accepted (no path tricks)."""
    return bool(_ID.match(v or ""))


# ---------------------------------------------------------------- text chunking
def split_text(text: str, max_chars: int, max_bytes: int | None = None) -> list[str]:
    def fits(s: str) -> bool:
        return len(s) <= max_chars and (max_bytes is None or len(s.encode()) <= max_bytes)

    text = text.strip()
    if fits(text):
        return [text] if text else []
    out: list[str] = []
    cur = ""
    for token in re.split(r"(\s+)", text):
        if not token:
            continue
        if fits(cur + token):
            cur += token
            continue
        if cur.strip():
            out.append(cur.strip())
            cur = ""
        while not fits(token):  # a single very long word: cut by characters
            n = len(token)
            while n > 1 and not fits(token[:n]):
                n -= 1
            out.append(token[:n])
            token = token[n:]
        cur = token.lstrip()
    if cur.strip():
        out.append(cur.strip())
    return out


# ---------------------------------------------------------------- sending
@dataclass
class SendResult:
    delivery: str                      # sent | simulated | stored | failed
    error: str | None = None
    kind: str | None = None            # MetaError kind when failed
    ext_id: str | None = None          # Meta's message id (wamid... / mid...)
    parts: int = 1


def _wa_target(customer) -> dict:
    ext = store.recipient_id(customer, "wa") or ""
    digits = re.sub(r"\D", "", ext)
    if digits and digits == ext.lstrip("+"):
        return {"to": f"+{digits}"}
    return {"recipient": ext}  # BSUID for users who only have a username


async def _send_one(channel, customer, text: str) -> str:
    kind, ext, tok = channel["kind"], channel["external_id"], token_of(channel)
    v = version()
    if kind == "wa":
        body = {"messaging_product": "whatsapp", "recipient_type": "individual", **_wa_target(customer), "type": "text", "text": {"preview_url": False, "body": text}}
        d = await _call("POST", f"{graph_base()}/{v}/{ext}/messages", token=tok, json=body)
        return (d.get("messages") or [{}])[0].get("id", "")
    msg = {"recipient": {"id": store.recipient_id(customer, kind)}, "message": {"text": text}}
    if kind == "ms":
        d = await _call("POST", f"{graph_base()}/{v}/{ext}/messages", token=tok, token_in="query", json={**msg, "messaging_type": "RESPONSE"})
        return d.get("message_id", "")
    if kind == "ig":
        if config(channel).get("via") == "page":
            d = await _call("POST", f"{graph_base()}/{v}/me/messages", token=tok, token_in="query", json=msg)
        else:
            d = await _call("POST", f"{ig_base()}/{v}/{ext}/messages", token=tok, json=msg)
        return d.get("message_id", "")
    raise MetaError("other", "This channel cannot send.")


def note_result(channel_id: str, err: MetaError | None) -> None:
    """Remember the last problem so the channel card tells the truth; a token failure turns the channel red."""
    if err is None:
        db.run("UPDATE channels SET last_error=NULL WHERE id=? AND last_error IS NOT NULL", [channel_id])
        return
    db.run("UPDATE channels SET last_error=? WHERE id=?", [f"{err.message} ({db.now()[:16].replace('T', ' ')} UTC)", channel_id])
    if err.kind == "token":
        db.run("UPDATE channels SET status='danger', alert=? WHERE id=?", ["Meta rejected the access token. Messages are not being sent. Reconnect with a new token.", channel_id])


async def send_text(channel, customer, text: str) -> SendResult:
    kind = channel["kind"]
    if kind == "web":
        return SendResult("stored")
    if not is_live(channel) or not store.recipient_id(customer, kind):
        return SendResult("simulated")
    max_chars, max_bytes = LIMITS[kind]
    parts = split_text(text, max_chars, max_bytes)
    first_id = None
    for p in parts:
        try:
            ext = await _send_one(channel, customer, p)
        except MetaError as e:
            note_result(channel["id"], e)
            return SendResult("failed", e.message, e.kind, first_id, len(parts))
        first_id = first_id or ext
    note_result(channel["id"], None)
    return SendResult("sent", ext_id=first_id, parts=len(parts))


async def send_template(channel, customer, name: str, language: str, params: list[str], param_names: list[str] | None = None) -> SendResult:
    """WhatsApp template message: the only thing allowed outside the 24-hour window."""
    if channel["kind"] != "wa":
        return SendResult("failed", "Templates are only used on WhatsApp.", "param")
    if not is_live(channel) or not store.recipient_id(customer, "wa"):
        return SendResult("simulated")
    comps = []
    if params:
        plist = []
        for i, val in enumerate(params):
            item: dict = {"type": "text", "text": val}
            if param_names and i < len(param_names) and not param_names[i].isdigit():
                item["parameter_name"] = param_names[i]
            plist.append(item)
        comps.append({"type": "body", "parameters": plist})
    body = {"messaging_product": "whatsapp", "recipient_type": "individual", **_wa_target(customer), "type": "template",
            "template": {"name": name, "language": {"code": language}, "components": comps}}
    try:
        d = await _call("POST", f"{graph_base()}/{version()}/{channel['external_id']}/messages", token=token_of(channel), json=body)
    except MetaError as e:
        note_result(channel["id"], e)
        return SendResult("failed", e.message, e.kind)
    note_result(channel["id"], None)
    return SendResult("sent", ext_id=(d.get("messages") or [{}])[0].get("id"))


async def mark_read(channel, wamid: str) -> None:
    """Blue ticks for the customer. Best effort: never blocks or fails the conversation."""
    if channel["kind"] != "wa" or not is_live(channel):
        return
    try:
        await _call("POST", f"{graph_base()}/{version()}/{channel['external_id']}/messages", token=token_of(channel), timeout=6,
                    json={"messaging_product": "whatsapp", "status": "read", "message_id": wamid})
    except MetaError:
        pass


async def typing_on(channel, customer) -> None:
    if channel["kind"] != "ms" or not is_live(channel):
        return
    try:
        await _call("POST", f"{graph_base()}/{version()}/{channel['external_id']}/messages", token=token_of(channel), token_in="query", timeout=6,
                    json={"recipient": {"id": store.recipient_id(customer, "ms")}, "sender_action": "typing_on"})
    except MetaError:
        pass


async def fetch_name(channel, user_id: str) -> str | None:
    """Messenger: the customer's name from their PSID. Instagram has no documented lookup, so it is skipped."""
    if channel["kind"] != "ms" or not is_live(channel) or not valid_id(user_id):
        return None
    try:
        d = await _call("GET", f"{graph_base()}/{version()}/{user_id}", token=token_of(channel), token_in="query", params={"fields": "name"}, timeout=5)
        return d.get("name") or None
    except MetaError:
        return None


# ---------------------------------------------------------------- connecting and checking
async def validate(kind: str, external_id: str, token: str, via: str = "instagram_login", waba_id: str | None = None) -> dict:
    """Prove the ID and token are real and belong together. Returns {name, detail}."""
    if not valid_id(external_id):
        raise MetaError("param", "That ID does not look right. It should be a number of 5 or more digits.")
    if waba_id and not valid_id(waba_id):
        raise MetaError("param", "The WhatsApp Business Account ID should be a number.")
    v = version()
    if kind == "wa":
        d = await _call("GET", f"{graph_base()}/{v}/{external_id}", token=token, params={"fields": "display_phone_number,verified_name"})
        name = d.get("verified_name") or d.get("display_phone_number") or external_id
        if waba_id:
            await _call("GET", f"{graph_base()}/{v}/{waba_id}", token=token, params={"fields": "name"})
        return {"name": name, "detail": d.get("display_phone_number")}
    if kind == "ms":
        d = await _call("GET", f"{graph_base()}/{v}/{external_id}", token=token, token_in="query", params={"fields": "name"})
        return {"name": d.get("name") or external_id, "detail": None}
    if kind == "ig":
        if via == "page":
            d = await _call("GET", f"{graph_base()}/{v}/{external_id}", token=token, token_in="query", params={"fields": "name,instagram_business_account"})
            return {"name": d.get("name") or external_id, "detail": None}
        d = await _call("GET", f"{ig_base()}/{v}/me", token=token, params={"fields": "user_id,username"})
        ids = {str(d.get("user_id")), str(d.get("id"))}
        if external_id not in ids:
            raise MetaError("param", f"That token belongs to @{d.get('username') or 'another account'}, not to the account ID you entered.")
        return {"name": f"@{d['username']}" if d.get("username") else external_id, "detail": None}
    raise MetaError("param", "Unknown channel type.")


async def token_info(token: str) -> dict | None:
    """Expiry and validity via /debug_token (needs the Meta app ID and secret). None when it cannot be checked."""
    app_id, secret = metacfg.app_id(), metacfg.app_secret()
    if not app_id or not secret:
        return None
    try:
        d = await _call("GET", f"{graph_base()}/{version()}/debug_token", params={"input_token": token, "access_token": f"{app_id}|{secret}"}, timeout=8)
    except MetaError:
        return None
    return d.get("data") or None


async def check_channel(channel) -> dict:
    """Re-verify a live channel and refresh what the card shows. Returns the outcome for the UI."""
    cid, kind, ext, tok = channel["id"], channel["kind"], channel["external_id"], token_of(channel)
    if not is_live(channel):
        return {"ok": False, "message": "This channel is not connected to Meta."}
    cfg = config(channel)
    try:
        info = await validate(kind, ext, tok, cfg.get("via", "instagram_login"), cfg.get("waba_id"))
    except MetaError as e:
        note_result(cid, e)
        db.run("UPDATE channels SET last_check_at=? WHERE id=?", [db.now(), cid])
        return {"ok": False, "message": e.message, "kind": e.kind}
    expires = None
    ti = await token_info(tok) if not (kind == "ig" and cfg.get("via") != "page") else None
    warn = None
    if ti is not None:
        if ti.get("is_valid") is False:
            err = MetaError("token", "Meta says this access token is no longer valid. Reconnect with a new token.")
            note_result(cid, err)
            db.run("UPDATE channels SET last_check_at=? WHERE id=?", [db.now(), cid])
            return {"ok": False, "message": err.message, "kind": "token"}
        exp = ti.get("expires_at") or 0
        if exp:
            from datetime import datetime, timezone
            expires = datetime.fromtimestamp(int(exp), timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    db.run("UPDATE channels SET verified_name=?, token_expires_at=?, last_check_at=?, last_error=NULL, status=CASE WHEN status='danger' THEN 'ok' ELSE status END, alert=CASE WHEN status='danger' THEN NULL ELSE alert END WHERE id=?",
           [info["name"], expires, db.now(), cid])
    return {"ok": True, "message": f"Connected as {info['name']}.", "name": info["name"], "expiresAt": expires, "warning": warn}


async def subscribe(channel) -> dict:
    """Subscribe this app to the account's webhooks (so Meta starts sending messages here)."""
    kind, ext, tok, v = channel["kind"], channel["external_id"], token_of(channel), version()
    cfg = config(channel)
    try:
        if kind == "wa":
            waba = cfg.get("waba_id")
            if not waba:
                return {"ok": False, "message": "Add the WhatsApp Business Account ID to subscribe webhooks."}
            await _call("POST", f"{graph_base()}/{v}/{waba}/subscribed_apps", token=tok)
        elif kind == "ms":
            await _call("POST", f"{graph_base()}/{v}/{ext}/subscribed_apps", token=tok, token_in="query", params={"subscribed_fields": "messages,message_deliveries,message_reads"})
        elif kind == "ig":
            if cfg.get("via") == "page":
                await _call("POST", f"{graph_base()}/{v}/{ext}/subscribed_apps", token=tok, token_in="query", params={"subscribed_fields": "messages"})
            else:
                await _call("POST", f"{ig_base()}/{v}/{ext}/subscribed_apps", token=tok, token_in="query", params={"subscribed_fields": "messages,messaging_seen"})
        else:
            return {"ok": False, "message": "Nothing to subscribe for this channel."}
    except MetaError as e:
        note_result(channel["id"], e)
        return {"ok": False, "message": e.message, "kind": e.kind}
    return {"ok": True, "message": "Subscribed. Meta will now send this account's messages to your webhook."}


# ---------------------------------------------------------------- WhatsApp templates
_PH = re.compile(r"\{\{\s*(\w+)\s*\}\}")

DEMO_TEMPLATES = [
    {"name": "return_update", "language": "bn", "category": "UTILITY", "body": "আসসালামু আলাইকুম {{1}}, আপনার {{2}} অর্ডারের রিটার্ন রিভিউ চলছে। ১ কার্যদিবসের মধ্যে জানাব।", "params": ["1", "2"], "label": "Return update (বাংলা)"},
    {"name": "order_followup", "language": "en", "category": "UTILITY", "body": "Hello {{1}}, we are following up on your request. Reply here and we can continue.", "params": ["1"], "label": "Follow-up (English)"},
]

_tpl_cache: dict[str, tuple[float, list[dict]]] = {}


def simplify_template(t: dict) -> dict | None:
    body = next((c.get("text", "") for c in (t.get("components") or []) if str(c.get("type", "")).upper() == "BODY"), "")
    if not body:
        return None
    params = list(dict.fromkeys(_PH.findall(body)))
    return {"name": t.get("name"), "language": t.get("language"), "category": t.get("category"), "body": body, "params": params,
            "label": f"{t.get('name', '').replace('_', ' ').capitalize()} ({t.get('language')})"}


async def list_templates(channel) -> list[dict]:
    """Approved templates only: the sole thing WhatsApp allows outside the 24-hour window."""
    import time
    if not is_live(channel):
        return DEMO_TEMPLATES
    waba = config(channel).get("waba_id")
    if not waba:
        raise MetaError("param", "Add the WhatsApp Business Account ID to this channel to list templates.")
    hit = _tpl_cache.get(channel["id"])
    if hit and time.time() - hit[0] < 300:
        return hit[1]
    d = await _call("GET", f"{graph_base()}/{version()}/{waba}/message_templates", token=token_of(channel),
                    params={"fields": "name,language,status,category,components,parameter_format", "limit": 100})
    out = []
    for t in d.get("data", []):
        if t.get("status") != "APPROVED":
            continue
        s = simplify_template(t)
        if s:
            out.append(s)
    _tpl_cache[channel["id"]] = (time.time(), out)
    return out


def render_template(body: str, params: list[str], names: list[str]) -> str:
    mapping = dict(zip(names, params))
    return _PH.sub(lambda m: mapping.get(m.group(1), m.group(0)), body)


def store_credentials(token: str) -> str:
    return seal(db.dumps({"access_token": token}))
