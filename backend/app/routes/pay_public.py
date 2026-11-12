"""Public endpoints the payment gateways and the courier call. No login here, so nothing in a request is believed:
every payment is confirmed by asking the gateway, and a courier webhook only tells us *which* parcel to re-check."""
from __future__ import annotations

import hmac
import json
import re
from urllib.parse import parse_qs

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from .. import couriers, db, payments, providers_lookup, publicbiz

router = APIRouter()
_KINDS = {"success", "fail", "cancel", "ipn", "callback"}


async def _params(request: Request) -> dict:
    out = {k: v for k, v in request.query_params.items()}
    if request.method == "POST":
        raw = await request.body()
        if len(raw) > 200_000:
            return out
        ct = request.headers.get("content-type", "")
        try:
            if "json" in ct:
                d = json.loads(raw or b"{}")
                out.update({k: str(v) for k, v in d.items()} if isinstance(d, dict) else {})
            else:
                out.update({k: v[0] for k, v in parse_qs(raw.decode("utf-8", "ignore"), keep_blank_values=True).items()})
        except ValueError:
            pass
    return out


async def _gateway(provider: str, kind: str, request: Request):
    if provider not in payments.PROVIDERS or kind not in _KINDS:
        return Response("not found", status_code=404)
    res = await payments.handle_callback(provider, kind, await _params(request))
    if kind == "ipn":
        return PlainTextResponse("OK")  # the gateway only needs a 200
    return RedirectResponse(f"/pay/done?s={res['outcome']}&o={res.get('order') or ''}", status_code=303)


# /pay/<slug>/<provider>/<kind> for every business; the original /pay/<provider>/<kind> is the default business.
@router.api_route("/pay/{slug}/{provider}/{kind}", methods=["GET", "POST"])
async def gateway_for(slug: str, provider: str, kind: str, request: Request):
    publicbiz.enter(slug)
    return await _gateway(provider, kind, request)


@router.api_route("/pay/{provider}/{kind}", methods=["GET", "POST"])
async def gateway(provider: str, kind: str, request: Request):
    publicbiz.enter(None)
    return await _gateway(provider, kind, request)


@router.get("/pay/done", response_class=HTMLResponse)
async def done(s: str = "pending", o: str = ""):
    s = s if s in {"paid", "already_paid", "pending", "failed", "cancelled", "mismatch", "review", "duplicate_paid", "unknown"} else "pending"
    o = o if re.fullmatch(r"#?\d{3,10}", o or "") else ""
    ok = s in ("paid", "already_paid", "duplicate_paid")
    title, body_en, body_bn = {
        True: ("Payment received", "Thank you. Your payment was confirmed. You can close this page.", "ধন্যবাদ। আপনার পেমেন্ট নিশ্চিত হয়েছে। এই পেজটি বন্ধ করতে পারেন।"),
    }.get(ok, (None, None, None))
    if not ok:
        title, body_en, body_bn = {
            "cancelled": ("Payment cancelled", "You cancelled the payment. Nothing was charged. Ask us for a new link if you want to try again.", "আপনি পেমেন্ট বাতিল করেছেন। কোনো টাকা কাটা হয়নি।"),
            "failed": ("Payment did not go through", "The payment failed and nothing was charged. Ask us for a new link to try again.", "পেমেন্ট সম্পন্ন হয়নি। কোনো টাকা কাটা হয়নি।"),
            "mismatch": ("We are checking your payment", "The amount did not match, so our team will check and contact you.", "পরিমাণ মেলেনি, আমাদের টিম যাচাই করে যোগাযোগ করবে।"),
            "review": ("We are checking your payment", "Your payment is being reviewed. We will confirm shortly.", "আপনার পেমেন্ট যাচাই করা হচ্ছে।"),
        }.get(s, ("Confirming your payment", "We are confirming your payment with the provider. If money left your account, we will update you shortly. You can close this page.", "পেমেন্ট নিশ্চিত করা হচ্ছে। কিছুক্ষণের মধ্যে জানানো হবে।"))
    color = "#0e9f68" if ok else ("#d93a42" if s in ("failed", "cancelled") else "#3558fa")
    return f"""<!doctype html><html lang="bn"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>body{{margin:0;min-height:100dvh;display:grid;place-items:center;background:#f1f3fa;font-family:"Figtree","Hind Siliguri",system-ui,sans-serif;color:#0d1230}}
.c{{max-width:420px;margin:24px;background:#fff;border-radius:24px;padding:36px 30px;text-align:center;box-shadow:0 20px 60px -20px #1a276640}}
.i{{width:64px;height:64px;border-radius:50%;margin:0 auto 18px;display:grid;place-items:center;background:{color};color:#fff;font-size:30px;font-weight:800}}
h1{{margin:0 0 8px;font-size:24px}}p{{margin:6px 0;color:#444c72;line-height:1.55}}small{{display:block;margin-top:18px;color:#8189aa}}</style></head>
<body><div class="c"><div class="i">{'✓' if ok else ('✕' if s in ('failed','cancelled') else '…')}</div><h1>{title}</h1><p>{body_en}</p><p>{body_bn}</p>{f'<small>Order {o}</small>' if o else ''}</div></body></html>"""


@router.post("/hooks/{slug}/steadfast")
async def steadfast_hook_for(slug: str, request: Request):
    publicbiz.enter(slug)
    return await _steadfast_hook(request)


@router.post("/hooks/steadfast")
async def steadfast_hook(request: Request):
    publicbiz.enter(None)
    return await _steadfast_hook(request)


async def _steadfast_hook(request: Request):
    secret = (db.jl(providers_lookup.row("steadfast")["config"], {}) or {}).get("webhook_secret") if providers_lookup.row("steadfast") else None
    got = request.headers.get("authorization", "")
    got = got[7:] if got.lower().startswith("bearer ") else ""
    if not secret or not hmac.compare_digest(got, secret):
        return Response("unauthorized", status_code=401)
    try:
        body = json.loads((await request.body()) or b"{}")
    except ValueError:
        return Response("bad json", status_code=400)
    ids = {str(body.get(k)) for k in ("consignment_id", "tracking_code", "invoice") if isinstance(body, dict) and body.get(k)}
    n = 0
    for o in db.all("SELECT number, courier FROM orders WHERE courier IS NOT NULL AND fulfillment='In transit'"):
        info = db.jl(o["courier"], {}) or {}
        digits = "".join(ch for ch in o["number"] if ch.isdigit())
        if ids & {str(info.get("consignment_id")), str(info.get("track")), digits}:
            await couriers.track(o["number"])  # re-ask Steadfast: the body of this request is never believed
            n += 1
    return {"ok": True, "refreshed": n}
