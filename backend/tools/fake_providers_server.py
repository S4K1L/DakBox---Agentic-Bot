"""Run the provider stand-ins as a local server, with a fake hosted checkout page, to try payments and parcels end to end.

  .venv/bin/uvicorn tools.fake_providers_server:app --port 4011

Point Dakbox at it by adding to backend/.env (and deleting the lines again for the real providers):
  SSLCOMMERZ_BASE=http://127.0.0.1:4011
  BKASH_BASE=http://127.0.0.1:4011/v2/tokenized-checkout
  AAMARPAY_BASE=http://127.0.0.1:4011
  STEADFAST_BASE=http://127.0.0.1:4011/api/v1
  SSLWIRELESS_BASE=http://127.0.0.1:4011/api/v3
  ALPHASMS_BASE=http://127.0.0.1:4011
Credentials to enter in Dakbox: SSLCOMMERZ teststore / testpass@ssl · bKash merchant / pw / appkey / appsecret · aamarPay aamarpaytest / testkey · Steadfast sfkey / sfsecret
· SSL Wireless token ssl-token-0001, sender NORTHWIND (test number any 01XXXXXXXXX) · Alpha SMS key alpha-key-0001.
See the "texts" the SMS stand-ins received:  curl localhost:4011/_fake/sms   Mark an Alpha SMS delivered:  curl -X POST localhost:4011/_fake/alpha/7001/Delivered
Mark a parcel delivered:  curl -X POST localhost:4011/_fake/steadfast/1424001/delivered
"""
from __future__ import annotations

import html
import json

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from tools.fake_providers import FakeProviders

BASE = "http://127.0.0.1:4011"
app = FastAPI(title="Fake payment providers")
fp = FakeProviders(gw_base=BASE)


def _page(title: str, amount: float, who: str, action: str, cancel: str) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{who}</title>
<style>body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#eef1f8;font-family:system-ui,sans-serif}}.c{{background:#fff;border-radius:20px;padding:32px;width:340px;box-shadow:0 20px 50px -20px #0003;text-align:center}}
.t{{font-size:12px;letter-spacing:.1em;color:#d93a42;font-weight:800}}h1{{margin:10px 0 4px;font-size:34px}}p{{color:#666}}button{{width:100%;padding:14px;border:0;border-radius:12px;background:#3558fa;color:#fff;font-size:16px;font-weight:700;cursor:pointer;margin-top:14px}}a{{display:block;margin-top:12px;color:#888}}</style></head>
<body><div class="c"><div class="t">STAND-IN CHECKOUT, NOT REAL</div><p>{who}</p><h1>৳{amount:,.2f}</h1><p>{html.escape(title)}</p>
<form method="post" action="{action}"><button>Pay now</button></form><a href="{cancel}">Cancel</a></div></body></html>"""


def _autopost(url: str, fields: dict) -> HTMLResponse:
    inputs = "".join(f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(str(v))}">' for k, v in fields.items())
    return HTMLResponse(f'<!doctype html><body onload="document.forms[0].submit()"><form method="post" action="{html.escape(url)}">{inputs}<noscript><button>Continue</button></noscript></form></body>')


@app.get("/gw/ssl/{key}", response_class=HTMLResponse)
async def ssl_page(key: str):
    s = fp.ssl_sessions.get(key)
    if not s:
        return HTMLResponse("unknown session", 404)
    return _page(f"Order via SSLCOMMERZ · {s['tran_id']}", s["amount"], "SSLCOMMERZ", f"/gw/ssl/{key}/pay", f"/gw/ssl/{key}/cancel")


@app.post("/gw/ssl/{key}/pay")
async def ssl_pay(key: str):
    s = fp.ssl_sessions[key]
    form = fp.ssl_pay(s["tran_id"])
    if s.get("ipn_url"):
        try:
            async with httpx.AsyncClient(timeout=8) as c:
                await c.post(s["ipn_url"], data=form)
        except httpx.HTTPError:
            pass
    return _autopost(s["urls"]["success_url"], form)


@app.api_route("/gw/ssl/{key}/cancel", methods=["GET", "POST"])
async def ssl_cancel(key: str):
    s = fp.ssl_sessions[key]
    return _autopost(s["urls"]["cancel_url"], {"tran_id": s["tran_id"], "status": "CANCELLED"})


@app.get("/gw/bkash/{pid}", response_class=HTMLResponse)
async def bk_page(pid: str):
    p = fp.bk_payments.get(pid)
    if not p:
        return HTMLResponse("unknown payment", 404)
    return _page(f"Invoice {p['invoice']}", p["amount"], "bKash", f"/gw/bkash/{pid}/pay", f"/gw/bkash/{pid}/cancel")


@app.post("/gw/bkash/{pid}/pay")
async def bk_pay(pid: str):
    return RedirectResponse(fp.bk_pay(pid), status_code=303)


@app.api_route("/gw/bkash/{pid}/cancel", methods=["GET", "POST"])
async def bk_cancel(pid: str):
    return RedirectResponse(f"{fp.bk_payments[pid]['callback']}?paymentID={pid}&status=cancel&signature=sig", status_code=303)


@app.get("/gw/aamarpay/{tran}", response_class=HTMLResponse)
async def aam_page(tran: str):
    t = fp.aam_txns.get(tran)
    if not t:
        return HTMLResponse("unknown transaction", 404)
    return _page(f"Transaction {tran}", t["amount"], "aamarPay", f"/gw/aamarpay/{tran}/pay", f"/gw/aamarpay/{tran}/cancel")


@app.post("/gw/aamarpay/{tran}/pay")
async def aam_pay(tran: str):
    return _autopost(fp.aam_txns[tran]["urls"]["success_url"], fp.aam_pay(tran))


@app.api_route("/gw/aamarpay/{tran}/cancel", methods=["GET", "POST"])
async def aam_cancel(tran: str):
    return _autopost(fp.aam_txns[tran]["urls"]["cancel_url"], {"mer_txnid": tran, "pay_status": "Failed"})


@app.post("/_fake/steadfast/{cid}/{status}")
async def sf_status(cid: str, status: str):
    fp.sf_set(cid, status)
    return {"ok": True}


@app.post("/_fake/alpha/{rid}/{status}")
async def alpha_status(rid: str, status: str):
    fp.alpha_set(rid, status)
    return {"ok": True}


@app.get("/_fake/sms")
async def sms_state():
    return {"sslwireless": fp.sslw_sent, "alphasms": fp.alpha_sent}


@app.get("/_fake/state")
async def state():
    return {"ssl": list(fp.ssl_sessions), "bkash": list(fp.bk_payments), "aamarpay": list(fp.aam_txns), "steadfast": fp.sf, "calls": fp.calls[-15:]}


@app.api_route("/{path:path}", methods=["GET", "POST"])
async def api(path: str, request: Request):
    body: dict = {}
    raw = await request.body()
    if raw:
        ct = request.headers.get("content-type", "")
        if "json" in ct:
            body = json.loads(raw)
        else:
            from urllib.parse import parse_qs
            body = {k: v[0] for k, v in parse_qs(raw.decode()).items()}
    status, data = fp.handle(request.method, "/" + path, dict(request.query_params), body, dict(request.headers))
    return Response(json.dumps(data), status_code=status, media_type="application/json")
