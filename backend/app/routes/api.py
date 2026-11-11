from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .. import auth, checkout, couriers, db, domain, events, metacfg, payments, sms, store
from ..agent.agent import MODEL, has_model
from ..agent.tools import DEFAULT_SETTINGS, agent_settings
from ..events import emit
from ..util import initials, lang_name, rates_for, taka

router = APIRouter(prefix="/api", dependencies=[Depends(auth.current_user)])  # every route here needs a signed-in user


def mask_phone(p: str | None) -> str | None:
    return re.sub(r"^\+?880(\d{4})\d{4}(\d{2})$", r"+880 \1-XXXX\2", p) if p else None


# ---------------------------------------------------------------- views
def conv_item(c) -> dict:
    cust, ch = store.customer(c["customer_id"]), store.channel(c["channel_id"])
    cv = store.customer_view(cust)
    cv["phone"] = mask_phone(cust["phone"])
    return {
        "id": c["id"], "mode": c["mode"], "status": c["status"], "unread": c["unread"], "preview": c["preview"], "lastMessageAt": c["last_message_at"],
        "handoffReason": c["handoff_reason"], "hasPending": bool(c["pending"]), "customer": cv,
        "channel": {"id": ch["id"], "kind": ch["kind"], "name": ch["name"], "handle": ch["handle"]},
        "window": {"open": domain.window_open(c, ch), "expiresAt": c["window_expires_at"]},
    }


def message_view(m) -> dict:
    meta = db.jl(m["meta"], None) or {}
    product = None
    if meta.get("product"):
        p = store.product(meta["product"])
        if p:
            product = {"sku": p["sku"], "name": p["name"], "variant": p["variant"], "price": p["price"], "stock": p["stock"], "art": p["art"]}
    return {
        "id": m["id"], "role": m["role"], "author": m["author"], "text": m["text"], "translation": m["translation"], "delivery": m["delivery"], "at": m["created_at"],
        "event": {"icon": meta.get("icon", "bolt"), "detail": meta.get("detail"), "tone": meta.get("tone")} if m["role"] == "event" else None, "product": product,
    }


def order_view(o) -> dict:
    cust = store.customer(o["customer_id"])
    sub, total = store.order_total(o)
    conv = db.get("SELECT id FROM conversations WHERE customer_id=? ORDER BY last_message_at DESC LIMIT 1", [o["customer_id"]])
    return {
        "id": o["number"], "number": o["number"], "createdAt": o["created_at"], "channel": o["channel_kind"],
        "customer": {"id": cust["id"], "name": cust["name"], "initials": initials(cust["name"]), "hue": cust["hue"]},
        "items": db.jl(o["items"], []), "shipping": o["shipping"], "subtotal": sub, "total": total, "zone": o["zone"], "address": o["address"],
        "payment": {"status": o["pay_status"], "method": o["pay_method"], "ref": o["pay_ref"]}, "fulfillment": o["fulfillment"], "stage": o["stage"],
        "times": db.jl(o["times"], []), "courier": db.jl(o["courier"], None), "scans": db.jl(o["scans"], []), "log": db.jl(o["log"], []),
        "returnRequested": bool(o["return_requested"]), "conversationId": conv["id"] if conv else None,
        "payments": payments.for_order(o["number"]), "cod": couriers.cod_amount(o),
        "source": o["source"], "ship": {"name": o["ship_name"] or cust["name"], "phone": o["ship_phone"] or cust["phone"]},
    }


def approval_view(a) -> dict:
    cust = store.customer(a["customer_id"])
    conv = store.conversation(a["conversation_id"]) if a["conversation_id"] else None
    ch = store.channel(conv["channel_id"]) if conv else None
    return {
        "id": a["id"], "type": a["type"], "order": a["order_number"], "item": a["item"], "amount": a["amount"], "reason": a["reason"], "said": a["said"], "saidTr": a["said_tr"],
        "policy": a["policy"], "attachment": a["attachment"], "status": a["status"], "dueAt": a["due_at"], "decidedAt": a["decided_at"], "createdAt": a["created_at"],
        "conversationId": a["conversation_id"], "channel": ch["kind"] if ch else cust["channel_kind"],
        "customer": {"id": cust["id"], "name": cust["name"], "initials": initials(cust["name"]), "hue": cust["hue"]},
    }


# ---------------------------------------------------------------- realtime + session
@router.get("/events")
async def sse(request: Request):
    q = events.subscribe()

    async def gen():
        try:
            yield "retry: 2000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(ev)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            events.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/me")
async def me(user: dict = Depends(auth.current_user)):
    u = {k: v for k, v in user.items() if not k.startswith("_")}
    return {**u, "store": agent_settings()["storeName"], "engine": "claude" if has_model() else "offline", "model": MODEL if has_model() else None}


# ---------------------------------------------------------------- inbox
@router.get("/conversations")
async def conversations(q: str | None = None):
    items = [conv_item(c) for c in db.all("SELECT * FROM conversations ORDER BY last_message_at DESC")]
    if q:
        ql = q.lower()
        items = [c for c in items if ql in f"{c['customer']['name']} {c['preview']} {c['channel']['handle']}".lower()]
    return {"items": items}


@router.get("/conversations/{cid}")
async def conversation_detail(cid: str):
    c = store.conversation(cid)
    if not c:
        raise HTTPException(404, "not found")
    cust = store.customer(c["customer_id"])
    stats = store.customer_stats(cust["id"])
    orders = [order_view(o) for o in db.all("SELECT * FROM orders WHERE customer_id=? ORDER BY created_at DESC", [cust["id"]])]
    pending = db.jl(c["pending"], None)
    pending_view = None
    if pending:
        diff = []
        for a in pending["actions"]:
            if a["tool"] == "add_to_cart":
                p = store.product(a["input"]["sku"])
                diff.append({"name": p["name"], "variant": p["variant"], "qty": a["input"]["qty"], "price": p["price"]})
        preview = None
        if any(a["tool"] == "place_order" for a in pending["actions"]):
            sm = checkout.summary(cid, c["customer_id"])
            preview = {k: sm[k] for k in ("lines", "subtotal", "delivery", "total", "payment_method", "name", "phone", "address", "ready", "problems")}
        pending_view = {"text": pending["text"], "translation": pending.get("translation"), "createdAt": pending["createdAt"], "productSku": pending.get("productSku"),
                        "cartDiff": diff, "orderPreview": preview, "other": [a["tool"] for a in pending["actions"] if a["tool"] not in ("add_to_cart", "place_order")]}
    return {
        **conv_item(c), "summary": c["summary"], "messages": [message_view(m) for m in db.all("SELECT * FROM messages WHERE conversation_id=? ORDER BY id", [cid])],
        "pending": pending_view, "cart": db.jl(c["cart"], []),
        "context": {"lang": cust["lang"], "langName": lang_name(cust["lang"]), "phone": mask_phone(cust["phone"]), "area": cust["area"], "since": cust["created_at"], "ltv": stats["spent"], "orders": orders[:5]},
    }


class TextBody(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    internal: bool = False


class ModeBody(BaseModel):
    mode: Literal["agent", "hybrid", "human"]


class ResolveBody(BaseModel):
    on: bool = True


class DraftBody(BaseModel):
    text: str | None = Field(default=None, max_length=4000)


@router.post("/conversations/{cid}/read")
async def mark_read(cid: str):
    db.run("UPDATE conversations SET unread=0 WHERE id=?", [cid])
    emit("conversation", id=cid)
    return {"ok": True}


@router.post("/conversations/{cid}/messages", dependencies=[Depends(auth.require("conv.reply"))])
async def post_message(cid: str, b: TextBody):
    label = await domain.human_reply(cid, auth.staff(), b.text.strip(), b.internal)
    return {"ok": True, "delivery": label}


class TemplateBody(BaseModel):
    name: str = Field(min_length=1, max_length=512)
    language: str = Field(min_length=2, max_length=16)
    params: list[str] = Field(default_factory=list, max_length=20)


@router.get("/conversations/{cid}/templates")
async def conversation_templates(cid: str):
    return {"items": await domain.list_templates(cid)}


@router.post("/conversations/{cid}/template", dependencies=[Depends(auth.require("conv.reply"))])
async def post_template(cid: str, b: TemplateBody):
    label = await domain.send_template(cid, auth.staff(), b.name, b.language, b.params)
    return {"ok": True, "delivery": label}


@router.post("/conversations/{cid}/mode", dependencies=[Depends(auth.require("conv.reply"))])
async def post_mode(cid: str, b: ModeBody):
    domain.set_mode(cid, b.mode, auth.staff())
    return {"ok": True}


@router.post("/conversations/{cid}/resolve", dependencies=[Depends(auth.require("conv.reply"))])
async def post_resolve(cid: str, b: ResolveBody | None = None):
    domain.resolve(cid, auth.staff(), b.on if b else True)
    return {"ok": True}


@router.post("/conversations/{cid}/draft/approve", dependencies=[Depends(auth.require("draft.approve"))])
async def draft_approve(cid: str, b: DraftBody | None = None):
    await domain.approve_draft(cid, auth.staff(), b.text if b else None)
    return {"ok": True}


@router.post("/conversations/{cid}/draft/dismiss", dependencies=[Depends(auth.require("draft.approve"))])
async def draft_dismiss(cid: str):
    domain.dismiss_draft(cid)
    return {"ok": True}


class SimBody(BaseModel):
    channel: Literal["wa", "ms", "ig", "web"]
    name: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=2000)
    phone: str | None = None
    externalId: str | None = None


@router.post("/simulate", dependencies=[Depends(auth.require("simulate"))])
async def simulate(b: SimBody):
    """Pretend a customer wrote on a channel. Used by the demo, QA and the Playground screen."""
    ch = db.get("SELECT id FROM channels WHERE kind=? AND status != 'danger' ORDER BY created_at LIMIT 1", [b.channel])
    if not ch:
        raise HTTPException(400, "no such channel")
    ext = b.externalId or f"sim_{b.channel}_{re.sub(r'\W+', '', b.name.lower())}"
    cid = await domain.process_inbound(ch["id"], ext, b.name.strip(), b.text.strip(), b.phone)
    return {"conversationId": cid}


# ---------------------------------------------------------------- approvals
@router.get("/approvals")
async def approvals(status: str = "pending"):
    where = "status != 'pending'" if status == "decided" else "status = 'pending'"
    rows = db.all(f"SELECT * FROM approvals WHERE {where} ORDER BY due_at ASC")
    return {
        "items": [approval_view(a) for a in rows],
        "pending": db.get("SELECT COUNT(*) n FROM approvals WHERE status='pending'")["n"],
        "drafts": db.get("SELECT COUNT(*) n FROM conversations WHERE pending IS NOT NULL")["n"],
    }


class DecideBody(BaseModel):
    decision: Literal["approved", "rejected"]


@router.post("/approvals/{aid}/decide", dependencies=[Depends(auth.require("approvals.decide"))])
async def decide(aid: int, b: DecideBody):
    a = db.get("SELECT * FROM approvals WHERE id=?", [aid])
    if not a:
        raise HTTPException(404, "not found")
    if a["status"] != "pending":
        raise HTTPException(409, "already decided")
    db.run("UPDATE approvals SET status=?, decided_at=? WHERE id=?", [b.decision, db.now(), aid])
    auth.audit(f"approval.{b.decision}", f"{a['type']} {a['order_number']}", f"{a['amount']}")
    ok = b.decision == "approved"
    if a["conversation_id"]:
        store.add_event(a["conversation_id"], "check" if ok else "alert", f"{auth.staff()} {b.decision} the {a['type'].lower()} request", a["order_number"], "ok" if ok else "warn")
        cust, conv = store.customer(a["customer_id"]), store.conversation(a["conversation_id"])
        lang, kind = cust["lang"], a["type"]
        if ok:
            text = {"bn": f"আপনার {'এক্সচেঞ্জ' if kind == 'Exchange' else 'রিটার্ন'} অনুরোধ অনুমোদিত হয়েছে। বিস্তারিত শীঘ্রই জানানো হবে।",
                    "bl": f"Apnar {kind.lower()} request approve hoyeche. Details shighroi janabo."}.get(lang, f"Good news: your {kind.lower()} request has been approved. We will send the details shortly.")
        else:
            text = {"bn": "দুঃখিত, আপনার অনুরোধটি অনুমোদন করা যায়নি। বিস্তারিত জানতে এখানে লিখুন।",
                    "bl": "Dukkhito, apnar request ta approve kora jayni. Details jante ekhane likhun."}.get(lang, "Sorry, we could not approve this request. Reply here and a teammate will explain.")
        if domain.window_open(conv, store.channel(conv["channel_id"])):
            await domain.human_reply(a["conversation_id"], auth.staff(), text)
        else:
            store.add_event(a["conversation_id"], "clock", "Customer not notified: the 24-hour window is closed", "Send an approved template from the conversation", "warn")
    emit("approvals")
    return {"ok": True}


# ---------------------------------------------------------------- orders
def _order(no: str):
    o = store.order(no)
    if not o:
        raise HTTPException(404, "order not found")
    return o


def _log(o, channel: str, text: str, status: str = "Delivered") -> None:
    log = db.jl(o["log"], [])
    log.insert(0, {"c": channel, "x": text, "s": status, "t": db.now()})
    db.run("UPDATE orders SET log=? WHERE number=?", [db.dumps(log), o["number"]])


@router.get("/orders")
async def orders():
    return {"items": [order_view(o) for o in db.all("SELECT * FROM orders ORDER BY created_at DESC")]}


@router.get("/orders/{no}/rates")
async def order_rates(no: str):
    o = _order(no)
    return {"rates": couriers.rate_options(o), "cod": couriers.cod_amount(o), "providers": payments.live_providers()}


class ShipBody(BaseModel):
    courier: str
    expectedCod: int | None = None
    note: str = Field(default="", max_length=200)


@router.post("/orders/{no}/ship", dependencies=[Depends(auth.require("orders.manage"))])
async def ship(no: str, b: ShipBody):
    o = _order(no)
    if b.courier in couriers.COURIERS:
        res = await couriers.book(o["number"], b.courier, auth.staff(), b.expectedCod if b.expectedCod is not None else -1, b.note)
        return {"ok": True, "tracking": res["tracking"], "demo": False, "cod": res["cod"]}
    # No courier connected: the demo booking records a label in Dakbox only. Nothing is sent to any courier.
    if couriers.live_couriers():
        raise HTTPException(400, "Choose one of the connected couriers.")
    if o["pay_status"] == "Failed":
        raise HTTPException(409, "Payment must be received first")
    r = next((x for x in rates_for(o["zone"]) if "demo-" + x["id"] == b.courier), None)
    if not r:
        raise HTTPException(400, "unknown courier")
    import random
    track = f"DEMO-{26000000 + random.randint(0, 999999)}"
    times = db.jl(o["times"], [])
    while len(times) < 4:
        times.append(db.now())
    times[2] = times[3] = db.now()
    db.run("UPDATE orders SET courier=?, fulfillment='In transit', stage=3, times=?, scans=? WHERE number=?",
           [db.dumps({"name": f"{r['name']} (demo)", "track": track, "eta": "Tomorrow" if o["zone"] == "dhaka" else "In 3 days", "demo": True}), db.dumps(times), db.dumps([{"x": "Demo booking: nothing was sent to a courier", "t": db.now()}]), o["number"]])
    auth.audit("order.ship.demo", o["number"], r["name"])
    emit("orders")
    return {"ok": True, "tracking": track, "demo": True}


@router.post("/orders/{no}/track", dependencies=[Depends(auth.require("orders.manage"))])
async def track(no: str):
    _order(no)
    return await couriers.track(store.order(no)["number"])


class RefundBody(BaseModel):
    amount: int | None = Field(default=None, ge=1, le=1_000_000)
    reason: str = Field(default="Refund", max_length=200)
    manual: bool = False


@router.post("/orders/{no}/refund", dependencies=[Depends(auth.require("orders.refund"))])
async def refund(no: str, b: RefundBody | None = None):
    _order(no)
    b = b or RefundBody()
    return await payments.refund(store.order(no)["number"], b.amount, b.reason, auth.staff(), b.manual)


@router.post("/refunds/{rid}/check", dependencies=[Depends(auth.require("orders.refund"))])
async def refund_check(rid: str):
    return await payments.refund_check(rid, auth.staff())


@router.post("/orders/{no}/mark-paid", dependencies=[Depends(auth.require("orders.manage"))])
async def mark_paid(no: str):
    """A person confirms money arrived outside any gateway (cash, a bank transfer). Audited; any open payment links are closed."""
    o = _order(no)
    if o["pay_status"] in ("Paid", "Refunded"):
        raise HTTPException(409, "This order is already marked paid.")
    t = db.jl(o["times"], [])
    while len(t) < 2:
        t.append(db.now())
    t[1] = db.now()
    db.run("UPDATE orders SET pay_status='Paid', pay_method='Cash collected', stage=MAX(stage,1), times=? WHERE number=?", [db.dumps(t), o["number"]])
    db.run("UPDATE payments SET status='superseded' WHERE order_number=? AND status IN ('created','pending')", [o["number"]])
    auth.audit("order.mark_paid", o["number"], taka(store.order_total(o)[1]))
    emit("orders")
    return {"ok": True}


class PayLinkBody(BaseModel):
    provider: str
    sendInChat: bool = True


@router.post("/orders/{no}/payment-link", dependencies=[Depends(auth.require("orders.manage"))])
async def payment_link(no: str, b: PayLinkBody, request: Request):
    _order(no)
    base = metacfg.public_url() or str(request.base_url).rstrip("/")
    return await payments.create_link(store.order(no)["number"], b.provider, auth.staff(), base, b.sendInChat)


@router.post("/payments/{pid}/refresh", dependencies=[Depends(auth.require("orders.manage"))])
async def payment_refresh(pid: str):
    return await payments.refresh(pid, auth.staff())


@router.post("/orders/{no}/cancel", dependencies=[Depends(auth.require("orders.manage"))])
async def cancel(no: str):
    o = _order(no)
    if o["stage"] >= 3:
        raise HTTPException(409, "Already shipped")
    if o["fulfillment"] == "Cancelled":
        raise HTTPException(409, "Already cancelled")
    db.run("UPDATE orders SET fulfillment='Cancelled' WHERE number=?", [o["number"]])
    checkout.cancel_restock(o)
    auth.audit("order.cancel", o["number"])
    emit("orders")
    return {"ok": True}


class NotifyBody(BaseModel):
    via: Literal["sms", "wa", "email"]


@router.post("/orders/{no}/notify", dependencies=[Depends(auth.require("orders.manage"))])
async def notify(no: str, b: NotifyBody):
    o = _order(no)
    fb = {"Unfulfilled": "প্রস্তুত হচ্ছে", "In transit": "পথে আছে", "Delivered": "ডেলিভারি হয়েছে", "Cancelled": "বাতিল হয়েছে"}
    txt = f"অর্ডার {o['number']} এখন {fb.get(o['fulfillment'], o['fulfillment'])}।"
    if b.via == "sms":
        st = {"Unfulfilled": ("প্রস্তুত হচ্ছে", "prostut hocche", "being prepared"), "In transit": ("পথে আছে", "pothe ache", "on the way"),
              "Delivered": ("ডেলিভারি হয়েছে", "delivery hoyeche", "delivered"), "Cancelled": ("বাতিল হয়েছে", "batil hoyeche", "cancelled")}.get(o["fulfillment"])
        if not st:
            raise HTTPException(409, "There is no status message for this order's state.")
        n = o["number"]
        text = sms.compose("status", o, store.customer(o["customer_id"]), status_bn=f"অর্ডার {n} এখন {st[0]}।", status_bl=f"Order {n} ekhon {st[1]}.", status_en=f"Your order {n} is now {st[2]}.")
        r = await sms.submit(n, "status", text, manual=True, by=auth.staff())
        if r["status"] in ("not_sent", "held", "error"):
            raise HTTPException(409, r.get("error") or "The message was not sent.")
        emit("orders")
        return {"ok": True, "sms": r.get("message")}
    _log(o, b.via, txt)
    emit("orders")
    return {"ok": True}


# ---------------------------------------------------------------- products & customers
@router.get("/products")
async def products():
    return {"items": [dict(r) for r in db.all("SELECT * FROM products ORDER BY sold30 DESC")]}


ART_KINDS = ("bottle", "tent", "boot", "jacket", "box")


class ProductBody(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    variant: str | None = Field(default=None, max_length=100)
    sku: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    price: int = Field(ge=1, le=10_000_000)
    stock: int = Field(ge=0, le=1_000_000)
    description: str | None = Field(default=None, max_length=500)
    keywords: str = Field(default="", max_length=300)
    art: Literal["bottle", "tent", "boot", "jacket", "box"] = "box"


def _clean(b: ProductBody) -> dict:
    return {"name": " ".join(b.name.split()), "variant": " ".join((b.variant or "").split()) or None, "price": b.price, "stock": b.stock,
            "description": (b.description or "").strip() or None, "keywords": " ".join(b.keywords.lower().split()), "art": b.art}


@router.post("/products", dependencies=[Depends(auth.require("products.manage"))])
async def create_product(b: ProductBody):
    if db.get("SELECT 1 FROM products WHERE lower(sku)=lower(?)", [b.sku]):
        raise HTTPException(409, "A product with that SKU already exists.")
    v = _clean(b)
    db.run("INSERT INTO products(id,sku,name,variant,price,stock,sold30,art,description,keywords) VALUES(?,?,?,?,?,?,?,?,?,?)",
           [db.uid("p"), b.sku, v["name"], v["variant"], v["price"], v["stock"], 0, v["art"], v["description"], v["keywords"]])
    auth.audit("product.create", b.sku, f"{v['name']} · {taka(v['price'])} · stock {v['stock']}")
    emit("products")
    return {"ok": True, "product": dict(db.get("SELECT * FROM products WHERE sku=?", [b.sku]))}


@router.put("/products/{sku}", dependencies=[Depends(auth.require("products.manage"))])
async def update_product(sku: str, b: ProductBody):
    p = db.get("SELECT * FROM products WHERE sku=?", [sku])
    if not p:
        raise HTTPException(404, "No such product.")
    if b.sku != sku:
        raise HTTPException(400, "The SKU cannot be changed: orders and carts refer to it. Add a new product instead.")
    v = _clean(b)
    db.run("UPDATE products SET name=?, variant=?, price=?, stock=?, art=?, description=?, keywords=? WHERE sku=?",
           [v["name"], v["variant"], v["price"], v["stock"], v["art"], v["description"], v["keywords"], sku])
    auth.audit("product.update", sku, f"price {taka(p['price'])} → {taka(v['price'])}, stock {p['stock']} → {v['stock']}")
    emit("products")
    return {"ok": True}


@router.delete("/products/{sku}", dependencies=[Depends(auth.require("products.manage"))])
async def delete_product(sku: str):
    p = db.get("SELECT * FROM products WHERE sku=?", [sku])
    if not p:
        raise HTTPException(404, "No such product.")
    used = db.get("SELECT COUNT(*) n FROM orders WHERE items LIKE ?", [f'%"sku": "{sku}"%'])["n"] or db.get("SELECT COUNT(*) n FROM conversations WHERE cart LIKE ?", [f'%"sku": "{sku}"%'])["n"]
    if used:
        raise HTTPException(409, "This product is in orders or open carts, so it cannot be deleted. Set its stock to 0 instead.")
    db.run("DELETE FROM alerts WHERE product_id=?", [p["id"]])
    db.run("DELETE FROM products WHERE sku=?", [sku])
    auth.audit("product.delete", sku, p["name"])
    emit("products")
    return {"ok": True}


class StockBody(BaseModel):
    delta: int = Field(ge=-1000, le=1000)


@router.post("/products/{sku}/stock", dependencies=[Depends(auth.require("products.stock"))])
async def stock(sku: str, b: StockBody):
    db.run("UPDATE products SET stock = MAX(0, stock + ?) WHERE sku=?", [b.delta, sku])
    emit("products")
    return {"ok": True}


@router.get("/customers")
async def customers():
    out = []
    for c in db.all("SELECT * FROM customers ORDER BY created_at DESC"):
        s = store.customer_stats(c["id"])
        conv = db.get("SELECT id, channel_id FROM conversations WHERE customer_id=? ORDER BY last_message_at DESC LIMIT 1", [c["id"]])
        ch = store.channel(conv["channel_id"]) if conv else None
        v = store.customer_view(c)
        v["phone"] = mask_phone(c["phone"])
        out.append({**v, "orders": s["orders"], "spent": s["spent"], "lastOrder": s["last"], "conversationId": conv["id"] if conv else None, "channel": ch["kind"] if ch else c["channel_kind"]})
    return {"items": out}


# ---------------------------------------------------------------- insights
@router.get("/insights")
async def insights():
    hist = db.get_setting("insights_history", {})
    rows = db.all("SELECT ch.kind AS kind, COUNT(*) AS n FROM conversations c JOIN channels ch ON ch.id=c.channel_id GROUP BY ch.kind")
    total = sum(r["n"] for r in rows) or 1
    names = {"ms": "Messenger", "wa": "WhatsApp", "ig": "Instagram", "web": "Web chat"}
    runs = db.get("SELECT COUNT(*) n, COALESCE(AVG(ms),0) ms FROM agent_runs")
    chat_orders = db.all("SELECT * FROM orders WHERE source='chat' AND fulfillment != 'Cancelled'")
    return {
        "sample": True, "kpis": hist.get("kpis"), "handledSeries": hist.get("handled"), "reasons": hist.get("reasons"),
        "channels": sorted([{"kind": r["kind"], "name": names.get(r["kind"], r["kind"]), "pct": round(r["n"] / total * 100), "n": r["n"]} for r in rows], key=lambda x: -x["n"]),
        "live": {
            "open": db.get("SELECT COUNT(*) n FROM conversations WHERE status='open'")["n"],
            "needsYou": db.get("SELECT COUNT(*) n FROM conversations WHERE status='open' AND mode != 'agent'")["n"],
            "agentRuns": runs["n"], "avgAgentMs": round(runs["ms"]),
            "paidOrders": db.get("SELECT COUNT(*) n FROM orders WHERE pay_status='Paid'")["n"],
            "chatOrders": len(chat_orders), "chatRevenue": sum(store.order_total(o)[1] for o in chat_orders),
        },
    }


# ---------------------------------------------------------------- channels & integrations
@router.get("/integrations")
async def integrations():
    return {"items": [dict(r) for r in db.all("SELECT * FROM integrations ORDER BY rowid")], "notifications": db.get_setting("notifications", [])}


class IntegrationBody(BaseModel):
    status: Literal["ok", "off"]


@router.post("/integrations/{iid}", dependencies=[Depends(auth.require("connections.write"))])
async def set_integration(iid: str, b: IntegrationBody):
    if iid in ("steadfast", "bkash", "sslcommerz", "aamarpay", "sslwireless", "alphasms", "gp", "banglalink"):
        raise HTTPException(400, "Use Connect on the provider card: it checks the credentials with the provider first.")
    db.run("UPDATE integrations SET status=?, note=? WHERE id=?", [b.status, "Connected just now." if b.status == "ok" else "Not connected.", iid])
    auth.audit("integration.connect" if b.status == "ok" else "integration.disconnect", iid)
    return {"ok": True}


class NotifRows(BaseModel):
    rows: list[dict]


@router.put("/notifications", dependencies=[Depends(auth.require("connections.write"))])
async def put_notifications(b: NotifRows):
    db.set_setting("notifications", b.rows)
    return {"ok": True}


# ---------------------------------------------------------------- assistant settings
@router.get("/settings")
async def get_settings():
    return {"agent": agent_settings(), "defaults": DEFAULT_SETTINGS, "engine": "claude" if has_model() else "offline", "model": MODEL,
            "policies": [dict(r) for r in db.all("SELECT * FROM policies ORDER BY key")]}


@router.put("/settings", dependencies=[Depends(auth.require("settings.write"))])
async def put_settings(body: dict):
    allowed = {"storeName", "tone", "replyLanguage", "banglish", "bnDigits", "showTranslation", "confidence", "can", "maxOrder"}
    changed = {k: v for k, v in body.items() if k in allowed}
    if "maxOrder" in changed:
        try:
            changed["maxOrder"] = max(500, min(500000, int(changed["maxOrder"])))
        except (TypeError, ValueError):
            raise HTTPException(400, "The largest order must be a number of taka.")
    db.set_setting("agent", {**agent_settings(), **changed})
    auth.audit("settings.update", ", ".join(changed))
    return {"ok": True}


class PolicyBody(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=2000)


@router.put("/policies/{key}", dependencies=[Depends(auth.require("settings.write"))])
async def put_policy(key: str, b: PolicyBody):
    db.run("INSERT INTO policies(key,title,body) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET title=excluded.title, body=excluded.body", [key, b.title, b.body])
    auth.audit("policy.update", key)
    return {"ok": True}
