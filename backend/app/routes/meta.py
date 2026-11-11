"""Connecting and managing real Meta channels. Tokens go in, are checked against Meta, are stored encrypted,
and never come back out: the API only ever returns the last four characters."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import auth, db, meta, metacfg
from ..events import emit
from ..secrets_store import mask

router = APIRouter(prefix="/api", dependencies=[Depends(auth.current_user)])
WRITE = Depends(auth.require("connections.write"))

KIND_NAMES = {"wa": "WhatsApp Business", "ms": "Facebook Messenger", "ig": "Instagram"}


def _ago(iso: str | None) -> str:
    d = db.parse_ts(iso)
    if not d:
        return "never"
    s = int((datetime.now(timezone.utc) - d).total_seconds())
    return "just now" if s < 60 else f"{s // 60} min ago" if s < 3600 else f"{s // 3600}h ago" if s < 86400 else f"{s // 86400}d ago"


def channel_view(c) -> dict:
    last = db.get("SELECT MAX(last_message_at) t FROM conversations WHERE channel_id=?", [c["id"]])
    base = {
        "id": c["id"], "kind": c["kind"], "name": c["name"], "handle": c["handle"], "status": c["status"], "alert": c["alert"],
        "lastMessageAt": c["last_message_at"] or (last["t"] if last else None),
        "conversations": db.get("SELECT COUNT(*) n FROM conversations WHERE channel_id=?", [c["id"]])["n"],
        "live": bool(c["live"]), "demo": not c["live"],
    }
    if not c["live"]:
        return {**base, "health": db.jl(c["health"], []), "externalId": None, "via": None, "tokenHint": None}
    cfg = meta.config(c)
    tok = meta.token_of(c)
    now = datetime.now(timezone.utc)
    exp = db.parse_ts(c["token_expires_at"])
    health: list[list[str]] = [["Account", c["verified_name"] or c["external_id"], ""]]
    status, alert = c["status"], c["alert"]
    if exp:
        days = (exp - now).days
        health.append(["Access token", f"Expires in {days} days" if days >= 0 else "Expired", "ok" if days > 7 else ("warn" if days >= 0 else "danger")])
        if days <= 7 and status == "ok":
            status, alert = "warn", f"The access token expires in {max(days, 0)} days. Replace it before then so messages keep flowing."
    else:
        health.append(["Access token", "No expiry reported", ""])
    if c["last_webhook_at"]:
        health.append(["Webhook", f"Last event {_ago(c['last_webhook_at'])} · {c['webhook_count']} received", "ok"])
    else:
        health.append(["Webhook", "No events yet", "warn"])
        if status == "ok":
            status, alert = "warn", alert or "No webhook events have arrived yet. Subscribe webhooks, then send a test message to this account."
    if c["last_error"]:
        health.append(["Last problem", c["last_error"], "danger" if status == "danger" else "warn"])
    return {**base, "status": status, "alert": alert, "health": health, "externalId": c["external_id"], "via": cfg.get("via"), "wabaId": cfg.get("waba_id"),
            "tokenHint": mask(tok), "tokenExpiresAt": c["token_expires_at"], "lastWebhookAt": c["last_webhook_at"], "webhookCount": c["webhook_count"],
            "lastError": c["last_error"], "lastCheckAt": c["last_check_at"], "verifiedName": c["verified_name"]}


def _get(cid: str):
    c = db.get("SELECT * FROM channels WHERE id=?", [cid])
    if not c:
        raise HTTPException(404, "No such channel.")
    return c


# ---------------------------------------------------------------- the Meta app (shared by all channels)
class MetaAppBody(BaseModel):
    appId: str | None = Field(default=None, max_length=40)
    appSecret: str | None = Field(default=None, max_length=200)
    verifyToken: str | None = Field(default=None, max_length=200)
    publicUrl: str | None = Field(default=None, max_length=300)


@router.get("/meta")
async def meta_app(user: dict = Depends(auth.current_user)):
    can = "connections.write" in user["permissions"]
    v = metacfg.view(reveal_verify_token=can)
    if not can:
        v = {k: v[k] for k in ("publicUrl", "webhookUrl", "graphVersion")}
    return v


@router.put("/meta", dependencies=[WRITE])
async def update_meta_app(b: MetaAppBody):
    if b.publicUrl and not b.publicUrl.startswith("https://") and "localhost" not in b.publicUrl and "127.0.0.1" not in b.publicUrl:
        raise HTTPException(400, "Meta only delivers webhooks to an https:// address.")
    metacfg.update(b.appId, b.appSecret, b.verifyToken, b.publicUrl)
    auth.audit("meta.app.update", "Meta app", ", ".join(k for k, v in b.model_dump().items() if v))
    return metacfg.view(reveal_verify_token=True)


@router.post("/meta/verify-token", dependencies=[WRITE])
async def new_verify_token():
    t = metacfg.new_verify_token()
    metacfg.update(verify_token_=t)
    return {"verifyToken": t}


@router.get("/meta/diagnostics", dependencies=[WRITE])
async def diagnostics():
    rows = db.all("SELECT * FROM webhook_log ORDER BY id DESC LIMIT 30")
    return {"items": [dict(r) for r in rows]}


# ---------------------------------------------------------------- channels
@router.get("/channels")
async def channels():
    return {"items": [channel_view(c) for c in db.all("SELECT * FROM channels ORDER BY created_at")]}


class ConnectBody(BaseModel):
    kind: Literal["wa", "ms", "ig"]
    externalId: str = Field(min_length=3, max_length=40)
    accessToken: str = Field(min_length=10, max_length=1000)
    name: str | None = Field(default=None, max_length=80)
    wabaId: str | None = Field(default=None, max_length=40)
    via: Literal["instagram_login", "page"] = "instagram_login"


@router.post("/channels", dependencies=[WRITE])
async def connect(b: ConnectBody):
    ext, tok = b.externalId.strip(), b.accessToken.strip()
    if db.get("SELECT 1 FROM channels WHERE kind=? AND external_id=? AND live=1", [b.kind, ext]):
        raise HTTPException(409, "That account is already connected.")
    if b.kind == "wa" and not b.wabaId:
        raise HTTPException(400, "WhatsApp needs the WhatsApp Business Account ID too (it is used to list templates and subscribe webhooks).")
    try:
        info = await meta.validate(b.kind, ext, tok, b.via, b.wabaId)  # nothing is saved unless Meta accepts the token
    except meta.MetaError as e:
        raise HTTPException(400, e.message)
    cid = db.uid("ch")
    cfg = {k: v for k, v in {"via": b.via if b.kind == "ig" else None, "waba_id": b.wabaId.strip() if b.wabaId else None}.items() if v}
    db.run(
        "INSERT INTO channels(id,kind,name,handle,status,health,alert,last_message_at,created_at,external_id,config,credentials,verified_name,live,last_check_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [cid, b.kind, (b.name or KIND_NAMES[b.kind]).strip(), info["name"], "ok", "[]", None, None, db.now(), ext, db.dumps(cfg), meta.store_credentials(tok), info["name"], 1, db.now()],
    )
    ch = _get(cid)
    result = await meta.check_channel(ch)  # fills token expiry when the app ID and secret are known
    sub = await meta.subscribe(_get(cid))
    auth.audit("channel.connect", f"{KIND_NAMES[b.kind]} {info['name']}")
    emit("channels")
    return {"channel": channel_view(_get(cid)), "check": result, "subscription": sub}


class PatchBody(BaseModel):
    accessToken: str | None = Field(default=None, min_length=10, max_length=1000)
    name: str | None = Field(default=None, max_length=80)
    wabaId: str | None = Field(default=None, max_length=40)


@router.patch("/channels/{cid}", dependencies=[WRITE])
async def update_channel(cid: str, b: PatchBody):
    c = _get(cid)
    if not c["live"]:
        raise HTTPException(400, "This is a demo channel. Connect a real account instead.")
    cfg = meta.config(c)
    tok = b.accessToken.strip() if b.accessToken else meta.token_of(c)
    waba = b.wabaId.strip() if b.wabaId else cfg.get("waba_id")
    if b.accessToken or b.wabaId:
        try:
            info = await meta.validate(c["kind"], c["external_id"], tok, cfg.get("via", "instagram_login"), waba)
        except meta.MetaError as e:
            raise HTTPException(400, e.message)
        cfg["waba_id"] = waba
        db.run("UPDATE channels SET credentials=?, config=?, verified_name=?, handle=?, status='ok', alert=NULL, last_error=NULL WHERE id=?",
               [meta.store_credentials(tok), db.dumps({k: v for k, v in cfg.items() if v}), info["name"], info["name"], cid])
    if b.name:
        db.run("UPDATE channels SET name=? WHERE id=?", [b.name.strip(), cid])
    result = await meta.check_channel(_get(cid))
    auth.audit("channel.update", c["handle"], "token replaced" if b.accessToken else None)
    emit("channels")
    return {"channel": channel_view(_get(cid)), "check": result}


@router.post("/channels/{cid}/check", dependencies=[WRITE])
async def check(cid: str):
    c = _get(cid)
    result = await meta.check_channel(c)
    emit("channels")
    return {"channel": channel_view(_get(cid)), "check": result}


@router.post("/channels/{cid}/subscribe", dependencies=[WRITE])
async def subscribe(cid: str):
    c = _get(cid)
    if not c["live"]:
        raise HTTPException(400, "This is a demo channel.")
    result = await meta.subscribe(c)
    return {"channel": channel_view(_get(cid)), "result": result}


@router.delete("/channels/{cid}", dependencies=[WRITE])
async def disconnect(cid: str):
    c = _get(cid)
    if not c["live"]:
        raise HTTPException(400, "This is a demo channel; there is nothing to disconnect.")
    db.run("UPDATE channels SET live=0, status='off', credentials=NULL, alert=?, last_error=NULL WHERE id=?", ["Disconnected. Conversations are kept; nothing is sent or received.", cid])
    auth.audit("channel.disconnect", c["handle"])
    emit("channels")
    return {"ok": True}
