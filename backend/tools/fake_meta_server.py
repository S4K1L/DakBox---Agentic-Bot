"""Run the Graph API stand-in as a local server, to try the whole Meta flow without a Meta account.

  .venv/bin/uvicorn tools.fake_meta_server:app --port 4010

Point Dakbox at it by adding to backend/.env (and removing again for real Meta):
  META_GRAPH_BASE=http://127.0.0.1:4010
  META_IG_GRAPH_BASE=http://127.0.0.1:4010

Pretend accounts: WhatsApp phone ID 106540352242922 (WABA 102290129340398), Page 555000111, Instagram 17841400000000000.
Any access token starting with "good" works ("expiring..." ends in 3 days, "revoked..." fails the check).

Fire a customer message at Dakbox (signed with the app secret you saved in Dakbox):
  curl -X POST 'localhost:4010/_fake/webhook?kind=wa&from=8801712340042&text=hello&secret=YOUR_APP_SECRET'
See what Dakbox sent to "Meta":  curl localhost:4010/_fake/outbox
"""
from __future__ import annotations

import json
import os

import httpx
from fastapi import FastAPI, Request, Response

from tools.fake_graph import FakeGraph, page_text, sign, wa_media, wa_status, wa_text

app = FastAPI(title="Fake Meta Graph API")
g = FakeGraph()
g.add_wa("106540352242922", "Northwind Outdoor", "+880 1700-000000")
g.add_page("555000111", "Northwind Outdoor")
g.add_ig("17841400000000000", "northwind.outdoor")
DAKBOX = os.environ.get("DAKBOX_URL", "http://127.0.0.1:4000")


@app.get("/_fake/outbox")
async def outbox():
    return {"items": g.outbox[-30:]}


@app.get("/_fake/calls")
async def calls():
    return {"items": [{k: v for k, v in c.items() if k != "token"} for c in g.calls[-40:]]}


@app.post("/_fake/webhook")
async def webhook(kind: str = "wa", sender: str = "", text: str = "hello", secret: str = "", media: str = "", status: str = "", wamid: str = "", account: str = "", name: str = "Rubel Hossain"):
    sender = sender or {"wa": "8801712349999", "ms": "7777000999", "ig": "9990999"}[kind]
    if kind == "wa":
        acc = account or "106540352242922"
        payload = wa_status(acc, wamid, status, sender) if status else wa_media(acc, sender, media, text) if media else wa_text(acc, sender, text, name=name, wamid=f"wamid.FAKEIN{abs(hash(text + sender)) % 10**8}")
    else:
        acc = account or ("555000111" if kind == "ms" else "17841400000000000")
        payload = page_text(acc, sender, text, mid=f"mid.FAKEIN{abs(hash(text + sender)) % 10**8}", obj="page" if kind == "ms" else "instagram")
    raw = json.dumps(payload).encode()
    headers = {"content-type": "application/json", **({"x-hub-signature-256": sign(raw, secret)} if secret else {})}
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(f"{DAKBOX}/webhooks/meta", content=raw, headers=headers)
    return {"dakbox_status": r.status_code, "sent": payload}


@app.api_route("/{path:path}", methods=["GET", "POST", "DELETE"])
async def graph(path: str, request: Request):
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else request.query_params.get("access_token")
    body = None
    if request.method == "POST":
        try:
            body = await request.json()
        except ValueError:
            body = None
    q = dict(request.query_params)
    status, data = g.handle(request.method, request.url.netloc, "/" + path, q, token, "bearer" if auth else "query", body)
    g.calls.append({"method": request.method, "path": "/" + path, "query": {k: v for k, v in q.items() if k != "access_token"}, "token": None, "token_in": "bearer" if auth else "query", "body": body, "status": status})
    return Response(json.dumps(data), status_code=status, media_type="application/json")
