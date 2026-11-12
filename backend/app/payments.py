"""Payments: create a link, hear back, VERIFY, then (and only then) mark an order paid.

The rules, in order of importance:
1. A redirect or webhook is only a hint that something happened. Money is counted only after we ask the gateway ourselves
   (server to server) and it confirms the payment.
2. The confirmed transaction id, amount and currency must match the payment we created. Any mismatch is recorded and NOT settled.
3. Settling is idempotent: callbacks arrive twice, in any order, and from retries. Nothing is ever applied twice.
4. If a customer pays twice (or pays after the order was already paid), it is flagged for a refund, never silently absorbed.
5. Refunds are guarded against double clicks, over-refunds and half-known outcomes: a request whose result we do not know
   is shown as "unknown" and is never counted as refunded until the gateway says so.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from . import auth, db, domain, publicbiz, sms, store
from .events import emit
from .providers import aamarpay, bkash, common, sslcommerz
from .providers.common import ProviderError, Verified, same_amount
from .util import taka, to_bn_digits

PROVIDERS = {"sslcommerz": sslcommerz, "bkash": bkash, "aamarpay": aamarpay}
NAMES = {"sslcommerz": "SSLCOMMERZ", "bkash": "bKash", "aamarpay": "aamarPay"}
_SETTLED = ("paid", "partially_refunded", "refunded", "duplicate_paid")


def live_providers() -> list[str]:
    return [p for p in PROVIDERS if common.is_live(p)]


def _fail(status: int, message: str):
    raise domain.HttpError(status, message)


def _row(pid: str):
    r = db.get("SELECT * FROM payments WHERE id=?", [pid])
    if not r:
        _fail(404, "No such payment.")
    return r


def refunds_of(payment_id: str) -> list[dict]:
    return [dict(r) for r in db.all("SELECT * FROM payment_refunds WHERE payment_id=? ORDER BY created_at", [payment_id])]


def view(p, include_url: bool = True) -> dict:
    return {
        "id": p["id"], "provider": p["provider"], "providerName": NAMES.get(p["provider"], p["provider"]), "amount": p["amount"], "status": p["status"],
        "url": p["link_url"] if include_url and p["status"] in ("created", "pending") else None, "trxId": p["trx_id"], "mode": p["mode"],
        "createdAt": p["created_at"], "paidAt": p["paid_at"], "refunded": p["refunded"], "note": p["note"], "tranId": p["tran_id"],
        "canRefund": p["status"] in ("paid", "partially_refunded") and p["refunded"] < p["amount"],
        "refunds": [{"id": r["id"], "amount": r["amount"], "status": r["status"], "reason": r["reason"], "manual": bool(r["manual"]), "at": r["created_at"], "note": r["note"], "by": r["created_by"]} for r in refunds_of(p["id"])],
    }


def for_order(order_number: str) -> list[dict]:
    return [view(p) for p in db.all("SELECT * FROM payments WHERE order_number=? ORDER BY created_at DESC", [order_number])]


def _conv_for(order) -> str | None:
    c = db.get("SELECT id FROM conversations WHERE customer_id=? ORDER BY last_message_at DESC LIMIT 1", [order["customer_id"]])
    return c["id"] if c else None


def _event(order, icon: str, label: str, detail: str | None = None, tone: str | None = None) -> None:
    cid = _conv_for(order)
    if cid:
        store.add_event(cid, icon, label, detail, tone)


def _customer_dict(order) -> dict:
    cust = store.customer(order["customer_id"])
    phone = None
    try:
        from .providers.steadfast import bd_phone
        phone = bd_phone(order["ship_phone"] or cust["phone"])
    except ProviderError:
        pass
    addr = order["address"] or ""
    return {"name": order["ship_name"] or cust["name"], "phone": phone, "address": addr, "city": addr.split(",")[-1].strip().split(" ")[0] if "," in addr else "Dhaka", "email": None}


def _link_text(order, cust, url: str) -> str:
    first = cust["name"].split()[0]
    amount = store.order_total(order)[1]
    no = order["number"]
    if cust["lang"] == "bn":
        return f"{first}, আপনার {to_bn_digits(no)} অর্ডারের ({taka(amount, True)}) নিরাপদ পেমেন্ট লিংক: {url}\nআপনার পিন বা ওটিপি কাউকে দেবেন না।"
    if cust["lang"] == "bl":
        return f"{first}, apnar {no} order er ({taka(amount)}) nirapod payment link: {url}\nApnar PIN ba OTP kauke debena na."
    return f"Hi {first}, here is your secure payment link for order {no} ({taka(amount)}): {url}\nPlease never share your PIN or OTP with anyone."


# ---------------------------------------------------------------- creating a link
async def create_link(order_number: str, provider: str, by: str, base_url: str, send_in_chat: bool = True) -> dict:
    mod = PROVIDERS.get(provider)
    if not mod:
        _fail(400, "That payment provider is not available.")
    o = store.order(order_number)
    if not o:
        _fail(404, "No such order.")
    if o["pay_status"] in ("Paid", "Refunded"):
        _fail(409, "This order is already paid.")
    if o["fulfillment"] == "Cancelled":
        _fail(409, "This order was cancelled.")
    if not common.is_live(provider):
        _fail(409, f"Connect {NAMES[provider]} first (Connections, Payments).")
    cfg, creds = common.config(provider), common.creds(provider)
    if cfg.get("mode") == "live" and not base_url.startswith("https://"):
        _fail(400, "Live payments need a public https URL. Set it in Connections, Channels, Meta app (it is shared).")
    amount = store.order_total(o)[1]
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=20)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    ex = db.get("SELECT * FROM payments WHERE order_number=? AND provider=? AND status='pending' AND link_url IS NOT NULL AND created_at > ? AND amount=?", [order_number, provider, cutoff, amount])
    if ex:  # one live link per order and provider: do not spam the customer with new ones
        p, reused = ex, True
    else:
        pid, tran = db.uid("pay"), common.new_tran_id(order_number)
        db.run("INSERT INTO payments(id,order_number,provider,amount,currency,tran_id,status,mode,created_at,created_by,conversation_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
               [pid, order_number, provider, amount, "BDT", tran, "created", cfg.get("mode"), db.now(), by, _conv_for(o)])
        pay = f"{base_url}/pay{publicbiz.seg()}"          # this business's own return and IPN addresses
        urls = {
            "success": f"{pay}/{provider}/success", "fail": f"{pay}/{provider}/fail", "cancel": f"{pay}/{provider}/cancel",
            "ipn": f"{pay}/{provider}/ipn", "callback": f"{pay}/{provider}/callback",
        }
        try:
            kw = dict(tran_id=tran, amount=amount, order_number=order_number, payment_id=pid, customer=_customer_dict(o), urls=urls)
            res = await (mod.create(provider, creds, cfg, **kw) if provider == "bkash" else mod.create(creds, cfg, **kw))
        except ProviderError as e:
            db.run("UPDATE payments SET status='failed', note=? WHERE id=?", [e.message, pid])
            common.note_error(provider, e.message)
            _fail(502, e.message)
        db.run("UPDATE payments SET status='pending', link_url=?, provider_ref=? WHERE id=?", [res["url"], res.get("provider_ref"), pid])
        auth.audit("payment.link", f"{NAMES[provider]} {order_number}", taka(amount))
        _event(o, "cart", f"Payment link created ({NAMES[provider]})", f"{taka(amount)} · order {order_number}")
        p, reused = _row(pid), False
    sent, reason = False, None
    if send_in_chat:
        cid = _conv_for(o)
        if not cid:
            reason = "This customer has no conversation yet, so the link was not sent. Copy it and send it yourself."
        else:
            try:
                await domain.human_reply(cid, by, _link_text(o, store.customer(o["customer_id"]), p["link_url"]))
                sent = True
            except domain.HttpError as e:
                reason = e.message
    emit("orders")
    return {"payment": view(p), "url": p["link_url"], "reused": reused, "sent": sent, "notSentReason": reason}


# ---------------------------------------------------------------- settling (the safety core)
def _mark_order_paid(order, p, name: str) -> None:
    times = db.jl(order["times"], [])
    while len(times) < 2:
        times.append(db.now())
    times[1] = db.now()
    db.run("UPDATE orders SET pay_status='Paid', pay_method=?, pay_ref=?, stage=MAX(stage,1), times=? WHERE number=?", [name, p["trx_id"] or "", db.dumps(times), order["number"]])
    store.order_log(order["number"], "email", f"Payment of {taka(p['amount'])} received via {name}")


def settle(payment_id: str, v: Verified, source: str) -> str:
    """Apply a verified gateway answer. Returns: paid | already_paid | not_paid | mismatch | review | duplicate_paid."""
    p = _row(payment_id)
    o = store.order(p["order_number"])
    if p["status"] in _SETTLED:
        return "already_paid"
    if v.status != "paid":
        if v.status in ("failed", "cancelled") and p["status"] in ("created", "pending"):
            db.run("UPDATE payments SET status=?, note=? WHERE id=?", [v.status, v.reason, payment_id])
            _event(o, "alert", f"Payment {v.status} ({NAMES[p['provider']]})", v.reason, "warn")
            sms.fire(p["order_number"], "payment_failed", key=f"payfail:{payment_id}")
            emit("orders")
        return "not_paid"
    problems = []
    if v.tran_id and v.tran_id != p["tran_id"]:
        problems.append("transaction id")
    if v.amount is None or not same_amount(v.amount, p["amount"]):
        problems.append(f"amount (expected {taka(p['amount'])}, gateway says {v.amount})")
    if v.currency and v.currency.upper() != "BDT":
        problems.append(f"currency ({v.currency})")
    if problems:
        note = "Gateway data did not match: " + ", ".join(problems)
        db.run("UPDATE payments SET status='mismatch', note=?, trx_id=? WHERE id=?", [note, v.trx_id, payment_id])
        _event(o, "alert", "A payment did not match and was NOT counted", note, "warn")
        auth.audit("payment.mismatch", f"{NAMES[p['provider']]} {p['order_number']}", note)
        emit("orders")
        return "mismatch"
    if v.risk:
        db.run("UPDATE payments SET status='review', trx_id=?, note=? WHERE id=?", [v.trx_id, "The gateway flagged this payment as risky. Verify the customer before shipping.", payment_id])
        _event(o, "alert", "Payment held for review", "The gateway flagged it as risky. Verify the customer, then mark the order paid yourself.", "warn")
        emit("orders")
        return "review"
    name = NAMES[p["provider"]]
    with db.tx():
        fresh = store.order(p["order_number"])
        if fresh["pay_status"] in ("Paid", "Refunded") or db.get("SELECT 1 FROM payments WHERE order_number=? AND id!=? AND status IN ('paid','partially_refunded','refunded')", [p["order_number"], payment_id]):
            db.run("UPDATE payments SET status='duplicate_paid', trx_id=?, paid_at=?, note=? WHERE id=?",
                   [v.trx_id, db.now(), "The order was already paid. This customer paid twice: refund this payment.", payment_id])
            outcome = "duplicate_paid"
        else:
            db.run("UPDATE payments SET status='paid', trx_id=?, paid_at=?, note=NULL WHERE id=?", [v.trx_id, db.now(), payment_id])
            db.run("UPDATE payments SET status='superseded' WHERE order_number=? AND id!=? AND status IN ('created','pending')", [p["order_number"], payment_id])
            _mark_order_paid(fresh, _row(payment_id), name)
            outcome = "paid"
    if outcome == "paid":
        _event(o, "check", f"Payment received via {name}", f"{taka(p['amount'])} · {v.trx_id or ''}", "ok")
        auth.audit("payment.paid", f"{name} {p['order_number']}", f"{taka(p['amount'])} via {source}")
    else:
        _event(o, "alert", f"Customer paid twice via {name}", "Refund the second payment.", "warn")
        auth.audit("payment.duplicate", f"{name} {p['order_number']}", taka(p["amount"]))
    emit("orders")
    return outcome


async def _verify(p, *, val_id: str | None = None) -> Verified:
    prov, c, cfg = p["provider"], common.creds(p["provider"]), common.config(p["provider"])
    if not c:
        raise ProviderError("auth", f"{NAMES[prov]} is not connected any more.")
    if prov == "sslcommerz":
        return await sslcommerz.verify(c, cfg, tran_id=p["tran_id"], val_id=val_id)
    if prov == "aamarpay":
        return await aamarpay.verify(c, cfg, tran_id=p["tran_id"])
    return await bkash.verify(prov, c, cfg, p["provider_ref"])


async def handle_callback(provider: str, kind: str, params: dict) -> dict:
    """A customer's browser or the gateway's IPN arrived. Find the payment, ask the gateway, settle. Parameters are never trusted."""
    p = None
    if provider == "bkash":
        ref = params.get("paymentID") or params.get("paymentId")
        p = db.get("SELECT * FROM payments WHERE provider='bkash' AND provider_ref=?", [ref]) if ref else None
    else:
        tran = params.get("tran_id") or params.get("mer_txnid")
        p = db.get("SELECT * FROM payments WHERE provider=? AND tran_id=?", [provider, tran]) if tran else None
    if not p:
        return {"outcome": "unknown", "order": None}
    try:
        if provider == "bkash":
            c, cfg = common.creds("bkash"), common.config("bkash")
            if params.get("status") == "success" and p["status"] in ("created", "pending"):
                ex = db.jl(p["extra"], {}) or {}
                if not ex.get("executed"):
                    db.run("UPDATE payments SET extra=? WHERE id=?", [db.dumps({**ex, "executed": True}), p["id"]])  # an id can be executed once
                    await bkash.execute("bkash", c, cfg, p["provider_ref"])
            v = await _verify(p)
        else:
            v = await _verify(p, val_id=params.get("val_id") if kind in ("success", "ipn") else None)
    except ProviderError as e:
        common.note_error(provider, e.message)
        db.run("UPDATE payments SET note=? WHERE id=?", [f"Could not verify yet: {e.message}", p["id"]])
        return {"outcome": "pending", "order": p["order_number"], "payment": p["id"]}
    if v.status == "pending" and kind in ("cancel", "fail") or (provider == "bkash" and v.status == "pending" and params.get("status") in ("cancel", "failure")):
        v = Verified("cancelled" if kind == "cancel" or params.get("status") == "cancel" else "failed", reason="Customer did not complete the payment", raw=v.raw)
    out = settle(p["id"], v, kind)
    return {"outcome": out if out != "not_paid" else (v.status if v.status in ("failed", "cancelled") else "pending"), "order": p["order_number"], "payment": p["id"]}


async def refresh(payment_id: str, by: str) -> dict:
    """Staff pressed "Check status": ask the gateway again (useful when a callback never arrived)."""
    p = _row(payment_id)
    if p["status"] in ("refunded",):
        return {"outcome": "already_paid", "payment": view(p)}
    try:
        v = await _verify(p)
    except ProviderError as e:
        _fail(502, e.message)
    out = settle(payment_id, v, f"manual check by {by}")
    return {"outcome": out, "payment": view(_row(payment_id))}


# ---------------------------------------------------------------- refunds
def _apply_refund_done(p, refund_id: str, amount: int, by: str, manual: bool) -> None:
    db.run("UPDATE payment_refunds SET status='done' WHERE id=?", [refund_id])
    new = p["refunded"] + amount
    full = new >= p["amount"]
    db.run("UPDATE payments SET refunded=?, status=? WHERE id=?", [new, "refunded" if full else "partially_refunded", p["id"]])
    o = store.order(p["order_number"])
    if full:
        db.run("UPDATE orders SET pay_status='Refunded' WHERE number=?", [p["order_number"]])
    store.order_log(p["order_number"], "email", f"Refund of {taka(amount)} {'recorded' if manual else 'issued'}")
    sms.fire(p["order_number"], "refund", key=f"refund:{refund_id}", amount=amount)
    _event(o, "check", f"Refund of {taka(amount)} {'recorded' if manual else 'sent'}", NAMES.get(p["provider"], ""), "ok")
    auth.audit("order.refund", p["order_number"], f"{taka(amount)} via {'manual record' if manual else NAMES[p['provider']]}")
    emit("orders")


async def refund(order_number: str, amount: int | None, reason: str, by: str, manual: bool = False) -> dict:
    o = store.order(order_number)
    if not o:
        _fail(404, "No such order.")
    if o["pay_status"] != "Paid":
        _fail(409, "Only a paid order can be refunded.")
    p = db.get("SELECT * FROM payments WHERE order_number=? AND status IN ('paid','partially_refunded') ORDER BY paid_at DESC", [order_number])
    total = store.order_total(o)[1]
    remaining = (p["amount"] - p["refunded"]) if p else total
    amount = int(amount) if amount else remaining
    if amount < 1 or amount > remaining:
        _fail(400, f"The refund must be between {taka(1)} and {taka(remaining)}.")
    rid = db.uid("rf")
    if not p:  # paid by cash on delivery or marked paid by hand: there is no gateway to call
        db.run("UPDATE orders SET pay_status='Refunded' WHERE number=?", [order_number])
        store.order_log(order_number, "email", f"Refund of {taka(amount)} recorded")
        sms.fire(order_number, "refund", key=f"refund:{rid}", amount=amount)
        auth.audit("order.refund", order_number, f"{taka(amount)} (no gateway payment: recorded)")
        _event(o, "check", f"Refund of {taka(amount)} recorded", "No online payment to reverse", "ok")
        emit("orders")
        return {"status": "done", "message": "Recorded. Nothing was sent to a gateway because this order was not paid online.", "manual": True}
    prov = p["provider"]
    if manual:
        db.run("INSERT INTO payment_refunds(id,payment_id,amount,status,reason,created_by,created_at,manual,note) VALUES(?,?,?,?,?,?,?,1,?)",
               [rid, p["id"], amount, "pending", reason, by, db.now(), "Refund made outside Dakbox (gateway panel or bank) and recorded here."])
        _apply_refund_done(p, rid, amount, by, True)
        return {"status": "done", "message": "Recorded. Make sure the money was really returned in the gateway panel.", "manual": True}
    if prov == "aamarpay":
        _fail(409, "aamarPay has no refund API. Refund it in the aamarPay merchant panel, then record it here with “I already refunded it”.")
    recent = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    if db.get("SELECT 1 FROM payment_refunds WHERE payment_id=? AND amount=? AND status IN ('pending','processing','unknown','done') AND created_at > ?", [p["id"], amount, recent]):
        _fail(409, "A refund for this amount was just requested. Wait, or press “Check refund” on it. Do not send it twice.")
    db.run("INSERT INTO payment_refunds(id,payment_id,amount,status,reason,created_by,created_at,manual) VALUES(?,?,?,?,?,?,?,0)", [rid, p["id"], amount, "pending", reason, by, db.now()])
    c, cfg = common.creds(prov), common.config(prov)
    try:
        if prov == "sslcommerz":
            res = await sslcommerz.refund(c, cfg, bank_tran_id=p["trx_id"], amount=amount, remarks=reason, refund_trans_id=rid)
        else:
            res = await bkash.refund(prov, c, cfg, payment_id=p["provider_ref"], trx_id=p["trx_id"], amount=amount, reason=reason, sku=order_number)
    except ProviderError as e:
        res = {"status": "unknown" if e.kind == "network" else "failed", "ref": None, "message": e.message}
    db.run("UPDATE payment_refunds SET status=?, provider_ref=?, note=? WHERE id=?", [res["status"] if res["status"] != "done" else "pending", res.get("ref"), res.get("message"), rid])
    if res["status"] == "done":
        _apply_refund_done(_row(p["id"]), rid, amount, by, False)
    elif res["status"] == "failed":
        auth.audit("refund.failed", order_number, (res.get("message") or "")[:100])
    return {"status": res["status"], "message": res.get("message"), "refundId": rid, "manual": False}


async def refund_check(refund_id: str, by: str) -> dict:
    """Ask the gateway what became of a refund that is processing or whose outcome we never heard."""
    r = db.get("SELECT * FROM payment_refunds WHERE id=?", [refund_id])
    if not r:
        _fail(404, "No such refund.")
    if r["status"] == "done":
        return {"status": "done"}
    p = _row(r["payment_id"])
    c, cfg = common.creds(p["provider"]), common.config(p["provider"])
    try:
        if p["provider"] == "sslcommerz" and r["provider_ref"]:
            res = await sslcommerz.refund_status(c, cfg, r["provider_ref"])
        elif p["provider"] == "bkash":
            res = await bkash.refund_status("bkash", c, cfg, p["provider_ref"], p["trx_id"], r["amount"])
        else:
            return {"status": r["status"], "message": "Nothing to check at the gateway for this refund."}
    except ProviderError as e:
        _fail(502, e.message)
    if res["status"] == "done":
        _apply_refund_done(p, refund_id, r["amount"], by, False)
        return {"status": "done"}
    if res["status"] == "none":
        db.run("UPDATE payment_refunds SET status='failed', note=? WHERE id=?", ["The gateway has no record of this refund, so it can be requested again.", refund_id])
        return {"status": "failed", "message": "The gateway has no record of this refund. You can request it again."}
    return {"status": res["status"], "message": res.get("message")}
