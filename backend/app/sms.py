"""Order SMS to customers: shipped, delivered, refund, payment failed, and the "send status update" button.

Rules this module enforces, whatever the provider:
- Nothing is sent until a provider is connected AND its last check passed. With none connected the message is shown in the order's log as "Not sent".
- One automatic message per event (a unique key), so a repeated courier poll or a replayed webhook cannot text a customer twice.
- Quiet hours (default 22:00 to 08:00 Bangladesh time): automatic messages wait and go out at 08:00. A person pressing "Send" is not held.
- A per-number and a per-day cap, so a bug or a loop cannot run up the bill or spam a phone.
- A send whose outcome is unknown is recorded as "Unknown" and never repeated automatically (a person decides), except SSL Wireless where a
  repeat is made safe by its client reference id.
- Delivery is only reported "Delivered" when the provider says so; SSL Wireless documents no delivery report, so its messages stay "Accepted".
- Message text is built here from templates and order facts. Nothing a customer typed is ever put in an SMS.
"""
from __future__ import annotations

import asyncio
import math
import sqlite3
from datetime import datetime, timedelta, timezone

from . import db, store
from .agent.tools import agent_settings
from .events import emit
from .providers import alphasms, common, sslwireless
from .providers.common import ProviderError
from .util import taka

PROVIDERS = {"sslwireless": sslwireless, "alphasms": alphasms}
NAMES = {"sslwireless": "SSL Wireless", "alphasms": "Alpha SMS"}
BD = timezone(timedelta(hours=6))   # Bangladesh has no daylight saving

EVENTS = {"placed": "Order placed", "payment_failed": "Payment failed", "shipped": "Shipped", "out": "Out for delivery", "delivered": "Delivered", "refund": "Refund issued"}
DEFAULTS = {"quiet": True, "quietFrom": 22, "quietTo": 8, "perNumberDay": 6, "perDay": 500}

_tasks: set[asyncio.Task] = set()


def _now() -> datetime:
    """The clock for quiet hours; tests replace it."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- measuring (standard SMS rules)
_GSM = set("@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà")
_GSM_EXT = set("^{}\\[~]|€")


def measure(text: str) -> tuple[str, int, int]:
    """(encoding, length in units, number of SMS parts). Plain text is 160 per part (153 when joined); anything else, Bangla included, is 70 (67)."""
    if all(ch in _GSM or ch in _GSM_EXT for ch in text):
        units = sum(2 if ch in _GSM_EXT else 1 for ch in text)
        return "GSM-7", units, 1 if units <= 160 else math.ceil(units / 153)
    units = len(text.encode("utf-16-le")) // 2
    return "Unicode", units, 1 if units <= 70 else math.ceil(units / 67)


# ---------------------------------------------------------------- settings
def settings() -> dict:
    return {**DEFAULTS, **(db.get_setting("sms_settings", {}) or {})}


def live_provider() -> str | None:
    for pid in PROVIDERS:
        if common.is_live(pid):
            return pid
    return None


def event_enabled(event: str) -> bool:
    label = EVENTS.get(event)
    for row in db.get_setting("notifications", []) or []:
        if row.get("e") == label:
            return bool(row.get("sms"))
    return False


def next_allowed(now: datetime | None = None) -> datetime:
    """When an automatic message may go out: now, or 08:00 Bangladesh time if it is quiet hours."""
    s = settings()
    now = now or _now()
    if not s["quiet"]:
        return now
    local = now.astimezone(BD)
    h, a, b = local.hour, int(s["quietFrom"]), int(s["quietTo"])
    quiet = (h >= a or h < b) if a > b else (a <= h < b)
    if not quiet:
        return now
    wake = local.replace(hour=b, minute=0, second=0, microsecond=0)
    if wake <= local:
        wake += timedelta(days=1)
    return wake.astimezone(timezone.utc)


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# ---------------------------------------------------------------- wording
def compose(event: str, o, cust, **x) -> str:
    """Short, fixed templates in the customer's language. Order facts only; no free text from anyone."""
    lang = cust["lang"] if cust["lang"] in ("bn", "bl") else "en"
    n = o["number"]
    store_name = agent_settings().get("storeName") or ""
    cod = int(x.get("cod") or 0)
    tr = x.get("tracking") or ""
    amt = int(x.get("amount") or 0)
    if lang == "bn":
        body = {
            "placed": f"আপনার অর্ডার {n} পেয়েছি। ধন্যবাদ!",
            "payment_failed": f"অর্ডার {n}-এর পেমেন্ট সম্পন্ন হয়নি।" + (f" আবার চেষ্টা করুন: {x['link']}" if x.get("link") else ""),
            "shipped": f"আপনার অর্ডার {n} শিপ হয়েছে।" + (f" ট্র্যাকিং: {tr}।" if tr else "") + (f" ডেলিভারিতে {taka(cod)} দিতে হবে।" if cod else ""),
            "out": f"আপনার অর্ডার {n} আজ ডেলিভারির জন্য বের হয়েছে।",
            "delivered": f"আপনার অর্ডার {n} ডেলিভারি হয়েছে। ধন্যবাদ!",
            "refund": f"অর্ডার {n}-এর {taka(amt)} রিফান্ড করা হয়েছে।",
            "status": x.get("status_bn") or f"অর্ডার {n}-এর খবর আপডেট হয়েছে।",
        }[event]
    elif lang == "bl":
        body = {
            "placed": f"Apnar order {n} peyechi. Dhonnobad!",
            "payment_failed": f"Order {n} er payment complete hoyni." + (f" Abar chesta korun: {x['link']}" if x.get("link") else ""),
            "shipped": f"Apnar order {n} ship hoyeche." + (f" Tracking: {tr}." if tr else "") + (f" Delivery te Tk {cod:,} dite hobe." if cod else ""),
            "out": f"Apnar order {n} ajke delivery r jonno ber hoyeche.",
            "delivered": f"Apnar order {n} delivery hoyeche. Dhonnobad!",
            "refund": f"Order {n} er Tk {amt:,} refund kora hoyeche.",
            "status": x.get("status_bl") or f"Order {n} er status update hoyeche.",
        }[event]
    else:
        body = {
            "placed": f"We got your order {n}. Thank you!",
            "payment_failed": f"The payment for order {n} did not go through." + (f" Please try again: {x['link']}" if x.get("link") else ""),
            "shipped": f"Your order {n} has shipped." + (f" Tracking: {tr}." if tr else "") + (f" Please keep Tk {cod:,} ready to pay on delivery." if cod else ""),
            "out": f"Your order {n} is out for delivery today.",
            "delivered": f"Your order {n} was delivered. Thank you!",
            "refund": f"Tk {amt:,} was refunded for order {n}.",
            "status": x.get("status_en") or f"Your order {n} has an update.",
        }[event]
    return f"{store_name}: {body}" if store_name else body


# ---------------------------------------------------------------- sending
def view(r) -> dict:
    return {"id": r["id"], "order": r["order_number"], "event": r["event"], "to": r["to_phone"], "body": r["body"], "encoding": r["encoding"], "parts": r["parts"],
            "provider": r["provider"], "providerName": NAMES.get(r["provider"] or "", ""), "status": r["status"], "error": r["error"], "createdAt": r["created_at"],
            "sendAfter": r["send_after"], "sentAt": r["sent_at"], "by": r["by_user"], "manual": bool(r["manual"]),
            "canResend": r["status"] in ("Failed", "Unknown")}


def _log_status(r) -> str:
    st = r["status"]
    name = NAMES.get(r["provider"] or "", "provider")
    if st == "Queued":
        return "Waiting for 08:00" if (r["send_after"] or "") > _iso(_now()) else "Queued"
    if st == "Accepted":
        return f"Accepted by {name}"
    if st == "Failed":
        return f"Failed: {r['error']}" if r["error"] else "Failed"
    if st == "Unknown":
        return "Unknown, check with the provider"
    return st


def _sync_log(mid: str) -> None:
    r = db.get("SELECT * FROM sms_messages WHERE id=?", [mid])
    if r and r["order_number"]:
        store.order_log_status(r["order_number"], mid, _log_status(r))


def _set(mid: str, status: str, error: str | None = None, **cols) -> None:
    sets = ["status=?", "error=?", "updated_at=?"] + [f"{k}=?" for k in cols]
    db.run(f"UPDATE sms_messages SET {', '.join(sets)} WHERE id=?", [status, error, db.now(), *cols.values(), mid])
    _sync_log(mid)


def _caps_reason(phone: str) -> str | None:
    s = settings()
    since = _iso(datetime.now(timezone.utc) - timedelta(hours=24))
    live = "status NOT IN ('Failed','Held')"
    if db.get(f"SELECT COUNT(*) n FROM sms_messages WHERE to_phone=? AND created_at>? AND {live}", [phone, since])["n"] >= int(s["perNumberDay"]):
        return f"This number already received {s['perNumberDay']} messages in 24 hours."
    if db.get(f"SELECT COUNT(*) n FROM sms_messages WHERE created_at>? AND {live}", [since])["n"] >= int(s["perDay"]):
        return f"The daily limit of {s['perDay']} messages was reached."
    return None


async def submit(order_number: str, event: str, text: str, *, key: str | None = None, manual: bool = False, by: str | None = None) -> dict:
    """Queue one SMS for an order's customer and send it now unless it is quiet hours. Returns {status, ...}; never raises for provider trouble."""
    o = store.order(order_number)
    if not o:
        return {"status": "error", "error": "No such order."}
    cust = store.customer(o["customer_id"])
    pid = live_provider()
    if not pid:
        store.order_log(order_number, "sms", text, "Not sent: no SMS provider connected")
        return {"status": "not_sent", "error": "No SMS provider is connected (Connections, SMS)."}
    if not manual and not event_enabled(event):
        return {"status": "off"}
    try:
        phone = PROVIDERS[pid].msisdn(o["ship_phone"] or cust["phone"])
    except ProviderError:
        store.order_log(order_number, "sms", text, "Not sent: no valid mobile number")
        return {"status": "not_sent", "error": "This customer has no valid Bangladesh mobile number."}
    enc, _units, parts = measure(text)
    if parts > PROVIDERS[pid].MAX_PARTS:
        return {"status": "error", "error": f"That message would use {parts} SMS parts. Shorten it."}
    reason = _caps_reason(phone)
    if reason:
        store.order_log(order_number, "sms", text, f"Held: {reason}")
        return {"status": "held", "error": reason}
    mid = db.uid("sm")
    send_after = _iso(_now() if manual else next_allowed())
    try:
        db.run("INSERT INTO sms_messages(id,order_number,event,to_phone,body,encoding,parts,provider,status,created_at,send_after,by_user,manual,dedupe_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               [mid, order_number, event, phone, text, enc, parts, pid, "Queued", db.now(), send_after, by, int(manual), key])
    except sqlite3.IntegrityError:
        old = db.get("SELECT * FROM sms_messages WHERE dedupe_key=?", [key])
        return {"status": "duplicate", "message": view(old) if old else None}
    store.order_log(order_number, "sms", text, "Queued", mid=mid)
    _sync_log(mid)
    emit("orders")
    if send_after <= _iso(_now()):
        await deliver(mid)
    return {"status": "queued", "message": view(db.get("SELECT * FROM sms_messages WHERE id=?", [mid]))}


async def deliver(mid: str) -> None:
    """Send one queued message. Claims it first, so two workers can never send it twice."""
    if db.run("UPDATE sms_messages SET status='Sending', updated_at=? WHERE id=? AND status='Queued'", [db.now(), mid]).rowcount != 1:
        return
    r = db.get("SELECT * FROM sms_messages WHERE id=?", [mid])
    pid = r["provider"]
    mod = PROVIDERS.get(pid)
    if not mod or not common.is_live(pid):
        _set(mid, "Failed", f"{NAMES.get(pid, 'The SMS provider')} is not connected or needs attention.")
        emit("orders")
        return
    try:
        res = await mod.send(common.creds(pid), common.config(pid), to=r["to_phone"], text=r["body"], ref=mid)
        _set(mid, res["status"], None, provider_ref=res.get("ref") or None, sent_at=db.now())
        common.note_error(pid, None)
    except ProviderError as e:
        if e.kind == "network":
            _set(mid, "Unknown", e.message)
        else:
            _set(mid, "Failed", e.message)
            if e.kind in ("auth", "rejected") and e.code not in ("blocked", "4026", "420"):
                common.note_error(pid, e.message)
                if e.kind == "auth":
                    db.run("UPDATE integrations SET status='warn' WHERE id=?", [pid])   # fail closed: nothing sends until it is checked again
    emit("orders")


async def notify(order_number: str, event: str, *, key: str | None = None, **extra) -> dict:
    """An automatic message for an order event (shipped, delivered, refund, payment failed)."""
    o = store.order(order_number)
    if not o:
        return {"status": "error"}
    cust = store.customer(o["customer_id"])
    if event == "payment_failed" and not extra.get("link"):
        p = db.get("SELECT link_url FROM payments WHERE order_number=? AND status IN ('created','pending') AND link_url IS NOT NULL ORDER BY created_at DESC", [order_number])
        if p:
            extra["link"] = p["link_url"]
    return await submit(order_number, event, compose(event, o, cust, **extra), key=key or f"{event}:{order_number}")


def fire(order_number: str, event: str, *, key: str | None = None, **extra) -> None:
    """Start notify() in the background from synchronous code. Failures are logged, never raised into the caller's work."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    async def run() -> None:
        try:
            await notify(order_number, event, key=key, **extra)
        except Exception as e:      # an SMS problem must never break shipping or refunds
            print("[sms]", repr(e))

    t = loop.create_task(run())
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


async def drain() -> None:
    while _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)


async def resend(mid: str, by: str) -> dict:
    r = db.get("SELECT * FROM sms_messages WHERE id=?", [mid])
    if not r or r["status"] not in ("Failed", "Unknown"):
        return {"status": "error", "error": "Only a failed or unknown message can be sent again."}
    return await submit(r["order_number"], r["event"], r["body"], manual=True, by=by)


# ---------------------------------------------------------------- background work
async def process_due() -> int:
    n = 0
    for r in db.all("SELECT id FROM sms_messages WHERE status='Queued' AND send_after<=? ORDER BY send_after LIMIT 50", [_iso(_now())]):
        await deliver(r["id"])
        n += 1
    stuck = _iso(datetime.now(timezone.utc) - timedelta(minutes=5))
    for r in db.all("SELECT id FROM sms_messages WHERE status='Sending' AND updated_at<?", [stuck]):
        _set(r["id"], "Unknown", "The server stopped while sending; the message may or may not have gone out.")   # never resend automatically
    return n


async def poll_reports() -> int:
    """Ask providers that publish delivery reports what happened to messages they accepted (last 48 hours)."""
    n = 0
    since = _iso(datetime.now(timezone.utc) - timedelta(hours=48))
    cool = _iso(datetime.now(timezone.utc) - timedelta(minutes=4))
    for r in db.all("SELECT * FROM sms_messages WHERE status IN ('Accepted','Sent') AND provider_ref IS NOT NULL AND created_at>? AND (last_report_at IS NULL OR last_report_at<?) LIMIT 40", [since, cool]):
        mod = PROVIDERS.get(r["provider"])
        if not mod or not mod.HAS_REPORT or not common.is_live(r["provider"]):
            continue
        db.run("UPDATE sms_messages SET last_report_at=? WHERE id=?", [db.now(), r["id"]])
        try:
            st = await mod.report(common.creds(r["provider"]), common.config(r["provider"]), r["provider_ref"])
        except ProviderError:
            continue
        if st and st != r["status"]:
            _set(r["id"], st, "The provider reported this message as undelivered." if st == "Failed" else None)
            n += 1
    if n:
        emit("orders")
    return n


def recent(limit: int = 50) -> list[dict]:
    return [view(r) for r in db.all("SELECT * FROM sms_messages ORDER BY created_at DESC LIMIT ?", [limit])]


def usage() -> dict:
    since = _iso(datetime.now(timezone.utc) - timedelta(hours=24))
    q = lambda w: db.get(f"SELECT COUNT(*) n, COALESCE(SUM(parts),0) p FROM sms_messages WHERE created_at>? AND {w}", [since])   # noqa: E731
    sent = q("status NOT IN ('Failed','Held','Queued')")
    return {"sent24h": sent["n"], "parts24h": sent["p"], "queued": q("status='Queued'")["n"], "failed24h": q("status='Failed'")["n"]}


async def send_test(pid: str, to: str, by: str) -> dict:
    """A real message to one number, to prove the credentials work. Not tied to an order and not subject to quiet hours."""
    mod = PROVIDERS[pid]
    phone = mod.msisdn(to)
    text = f"{agent_settings().get('storeName') or 'Dakbox'}: SMS test. Your order updates will be sent from this sender."
    ref = db.uid("t")
    res = await mod.send(common.creds(pid), common.config(pid), to=phone, text=text, ref=ref)
    enc, _u, parts = measure(text)
    db.run("INSERT INTO sms_messages(id,order_number,event,to_phone,body,encoding,parts,provider,provider_ref,status,created_at,send_after,sent_at,by_user,manual) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)",
           [db.uid("sm"), None, "test", phone, text, enc, parts, pid, res.get("ref") or None, res["status"], db.now(), db.now(), db.now(), by])
    return res
