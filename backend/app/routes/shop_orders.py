"""Where a website's order webhooks arrive. Public (no login: the shop cannot log in), so the signature is the only way in."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request

from .. import db, publicbiz, shop_orders as so

router = APIRouter()
MAX_BODY = 1_000_000


async def _shop_webhook(sid: str, request: Request):
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise HTTPException(413, "Too large.")
    src = db.get("SELECT * FROM catalog_sources WHERE id=?", [sid])
    secret = so.secret_of(src) if src else None
    if not src or not secret:
        raise HTTPException(404, "Not found.")                    # unknown address, or no secret set yet: fails closed
    if not so.verify(secret, raw, dict(request.headers)):
        if src["orders_error"] != so.BAD_SIGNATURE:
            so.note_result(src, so.BAD_SIGNATURE)
        raise HTTPException(401, "Bad signature.")
    try:
        body = json.loads(raw)
    except ValueError:
        return {"ok": True, "ignored": "not an order"}           # WooCommerce's first "ping" is not JSON: it only proves the address works
    if not isinstance(body, dict):
        return {"ok": True, "ignored": "not an order"}
    try:
        p = so.parse(body, dict(request.headers))
        if p.ignore:
            return {"ok": True, "ignored": p.ignore}
        res = so.ingest(src, p)
    except so.ShopOrderError as e:
        so.note_result(src, str(e))
        return {"ok": True, "ignored": str(e)}                    # 200: the shop would retry a refusal for days, and the answer would not change
    so.note_result(src, None)
    return {"ok": True, **res}


@router.post("/webhooks/shop/{slug}/{sid}")
async def shop_webhook_for(slug: str, sid: str, request: Request):
    publicbiz.enter(slug)
    return await _shop_webhook(sid, request)


@router.post("/webhooks/shop/{sid}")
async def shop_webhook(sid: str, request: Request):
    publicbiz.enter(None)                         # the original address: the default business
    return await _shop_webhook(sid, request)
