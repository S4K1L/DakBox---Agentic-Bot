"""Orders placed from a chat (by the assistant, after the customer confirmed).

The model never creates an order by itself. Code enforces, whatever engine is running:
- A *summary* (lines at live prices, delivery, total, payment method, recipient, address) is computed here and fingerprinted. An order can
  only be placed with that exact fingerprint, so any change to the cart, a price, the delivery charge or the details after the customer
  saw the summary invalidates it.
- The summary must have been SENT to the customer, and the customer must have written again after it. Asking and placing in one turn is refused.
- Stock is taken atomically at placement (never oversold); cancelling a chat order puts it back.
- Limits: total value (setting, default 20,000), units per order, orders per customer per day. Over a limit, the assistant hands over to a person.
- Cash on delivery is only an order in "Pending": staff still confirm by phone and book the courier. Online payment orders stay unpaid until the
  provider confirms; a payment link is sent in the chat after the confirmation message.
- Everything the customer typed (name, phone, address) is validated and only ever stored as data. It is never used as an instruction.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone

from . import db, store
from .events import emit
from .util import DISTRICTS, from_bn_digits, is_dhaka, taka

MAX_UNITS = 20
MAX_PER_DAY = 3
DEFAULT_MAX_ORDER = 20000

METHOD_WORDS = {
    "cod": ("cod", "cash on delivery", "cash", "ক্যাশ", "ক্যাশ অন ডেলিভারি", "হাতে হাতে"),
    "bkash": ("bkash", "bikash", "বিকাশ", "b-kash"),
    "sslcommerz": ("sslcommerz", "ssl commerz", "card", "কার্ড"),
    "aamarpay": ("aamarpay", "amarpay", "aamar pay"),
}


class CheckoutError(Exception):
    def __init__(self, code: str, **extra):
        self.code, self.extra = code, extra
        super().__init__(code)

    def result(self) -> dict:
        return {"error": self.code, **self.extra}


# ---------------------------------------------------------------- state on the conversation
def get(conversation_id: str) -> dict:
    c = store.conversation(conversation_id)
    return (db.jl(c["checkout"], {}) if c and c["checkout"] else {}) or {}


def _save(conversation_id: str, data: dict) -> None:
    db.run("UPDATE conversations SET checkout=? WHERE id=?", [db.dumps(data), conversation_id])


def _cfg() -> dict:
    from .agent.tools import agent_settings
    s = agent_settings()
    try:
        mx = int(s.get("maxOrder") or DEFAULT_MAX_ORDER)
    except (TypeError, ValueError):
        mx = DEFAULT_MAX_ORDER
    return {"enabled": bool(s["can"].get("checkout", True)) and bool(s["can"].get("carts", True)), "maxOrder": max(500, mx)}


def enabled() -> bool:
    return _cfg()["enabled"]


# ---------------------------------------------------------------- payment methods
def methods() -> list[dict]:
    from . import payments
    out = [{"id": "cod", "label": "Cash on delivery"}]
    out += [{"id": p, "label": payments.NAMES[p]} for p in payments.live_providers()]
    return out


def match_method(text: str | None) -> str | None:
    t = (text or "").lower().strip()
    if not t:
        return None
    for mid, words in METHOD_WORDS.items():
        if any(w in t for w in words):
            return mid
    return None


# ---------------------------------------------------------------- validating what the customer typed
def clean_phone(raw: str | None) -> str | None:
    d = re.sub(r"\D", "", from_bn_digits(raw or ""))
    if d.startswith("880"):
        d = d[3:]
    if d.startswith("0"):
        d = d[1:]
    return "0" + d if re.fullmatch(r"1[3-9]\d{8}", d) else None


def clean_text(raw: str | None, lo: int, hi: int) -> str | None:
    t = " ".join((raw or "").split())
    t = re.sub(r"[\x00-\x1f\x7f<>]", "", t)
    return t if lo <= len(t) <= hi else None


def find_district(*texts: str | None) -> str | None:
    hay = " ".join(t or "" for t in texts).lower()
    for d in DISTRICTS:
        if d.lower() in hay:
            return d.capitalize() if d.isascii() else d
    return None


def set_details(conversation_id: str, customer_id: str, *, name: str | None = None, phone: str | None = None, address: str | None = None,
                district: str | None = None, payment_method: str | None = None) -> dict:
    """Save what the customer told us. Partial updates are fine; every field that is given must be valid or nothing from it is kept."""
    ck = get(conversation_id)
    problems: list[dict] = []
    if name is not None:
        v = clean_text(name, 2, 100)
        ck["name"] = v if v else ck.get("name")
        if not v:
            problems.append({"field": "name", "problem": "Name must be 2 to 100 characters."})
    if phone is not None:
        v = clean_phone(phone)
        if v:
            ck["phone"] = v
        else:
            problems.append({"field": "phone", "problem": "Needs a Bangladesh mobile number like 01712345678."})
    if address is not None:
        v = clean_text(address, 10, 250)
        if v:
            ck["address"] = v
        else:
            problems.append({"field": "address", "problem": "Needs a full delivery address (house, road, area), 10 to 250 characters."})
    if district is not None or address is not None:
        d = find_district(district, address) if (district or address) else None
        if d:
            ck["district"] = d
    if payment_method is not None:
        m = match_method(payment_method)
        avail = {x["id"] for x in methods()}
        if m and m in avail:
            ck["method"] = m
        else:
            problems.append({"field": "payment_method", "problem": "That payment method is not available.", "available": methods()})
    ck.pop("proposal", None)               # any change invalidates a summary the customer may have seen
    _save(conversation_id, ck)
    if ck.get("phone") and not (store.customer(customer_id)["phone"] or "").strip():
        db.run("UPDATE customers SET phone=? WHERE id=?", [ck["phone"], customer_id])
    return {"saved": {k: v for k, v in ck.items() if k in ("name", "phone", "address", "district", "method")}, "problems": problems, "available_payment_methods": methods(), "missing": missing(ck)}


def missing(ck: dict) -> list[str]:
    return [f for f in ("name", "phone", "address", "district", "method") if not ck.get(f)]


# ---------------------------------------------------------------- the summary
def delivery_charge(zone: str) -> int:
    from . import couriers
    return min(int(o["price"]) for o in couriers.rate_options({"zone": zone}))


def summary(conversation_id: str, customer_id: str) -> dict:
    conv = store.conversation(conversation_id)
    cart = db.jl(conv["cart"], [])
    ck = get(conversation_id)
    cfg = _cfg()
    problems: list[dict] = []
    lines = []
    for l in cart:
        p = store.product(l["sku"])
        if not p:
            problems.append({"code": "unknown_product", "sku": l["sku"]})
            continue
        qty = int(l["qty"])
        if p["stock"] < qty:
            problems.append({"code": "insufficient_stock", "sku": p["sku"], "name": p["name"], "in_stock": p["stock"], "wanted": qty})
        lines.append({"sku": p["sku"], "name": p["name"], "variant": p["variant"], "price": p["price"], "qty": qty})
    if not lines:
        problems.append({"code": "cart_empty"})
    units = sum(l["qty"] for l in lines)
    if units > MAX_UNITS:
        problems.append({"code": "too_many_units", "limit": MAX_UNITS})
    miss = missing(ck)
    if miss:
        problems.append({"code": "missing_details", "fields": miss})
    zone = ("dhaka" if is_dhaka(ck["district"]) else "out") if ck.get("district") else None
    shipping = delivery_charge(zone) if zone else None
    sub = sum(l["price"] * l["qty"] for l in lines)
    total = sub + (shipping or 0)
    if total > cfg["maxOrder"]:
        problems.append({"code": "over_limit", "limit": cfg["maxOrder"], "hint": "Too large for the assistant to place. Hand over to a person."})
    if ck.get("method") and ck["method"] not in {m["id"] for m in methods()}:
        problems.append({"code": "method_unavailable", "available": methods()})
    label = next((m["label"] for m in methods() if m["id"] == ck.get("method")), None)
    fp = hashlib.sha256(db.dumps({"l": [(x["sku"], x["qty"], x["price"]) for x in lines], "s": shipping, "m": ck.get("method"), "p": ck.get("phone"), "a": ck.get("address"), "n": ck.get("name"), "z": zone}).encode()).hexdigest()[:12]
    return {"ready": not problems, "problems": problems, "lines": lines, "subtotal": sub, "subtotal_text": taka(sub), "delivery": shipping, "delivery_text": taka(shipping) if shipping is not None else None,
            "total": total, "total_text": taka(total), "payment_method": label, "method_id": ck.get("method"), "name": ck.get("name"), "phone": ck.get("phone"), "address": ck.get("address"),
            "district": ck.get("district"), "zone": zone, "confirm_hash": fp,
            "cod_note": "Cash on delivery: staff confirm by phone before the parcel is booked." if ck.get("method") == "cod" else None}


def propose(conversation_id: str, customer_id: str) -> dict:
    """Compute the summary and remember its fingerprint. The assistant must now show it to the customer and wait for a clear yes."""
    s = summary(conversation_id, customer_id)
    ck = get(conversation_id)
    if s["ready"]:
        ck["proposal"] = {"hash": s["confirm_hash"], "mid": db.get("SELECT COALESCE(MAX(id),0) m FROM messages WHERE conversation_id=?", [conversation_id])["m"]}
        _save(conversation_id, ck)
        s["instruction"] = "Show this summary to the customer and ask them to confirm. Do not call place_order in this turn."
    else:
        ck.pop("proposal", None)
        _save(conversation_id, ck)
    return s


def _confirmed_after(conversation_id: str, mid: int) -> bool:
    """The summary was SENT (a reply exists after message `mid`), and the customer wrote again after that reply."""
    a = db.get("SELECT MIN(id) m FROM messages WHERE conversation_id=? AND role IN ('assistant','human') AND id>?", [conversation_id, mid])["m"]
    c = db.get("SELECT MAX(id) m FROM messages WHERE conversation_id=? AND role='customer'", [conversation_id])["m"]
    return bool(a and c and c > a)


def _next_number() -> str:
    mx = 1000
    for r in db.all("SELECT number FROM orders"):
        d = re.sub(r"\D", "", r["number"])
        if d:
            mx = max(mx, int(d))
    return f"#{mx + 1}"


def place(conversation_id: str, customer_id: str, confirm_hash: str, *, dry: bool = False) -> tuple[dict, list[dict]]:
    """Create the order. Returns (result for the assistant, actions to run after the reply is sent). Raises CheckoutError when refused.
    With dry=True every check runs but nothing is written (used when the order is only being staged for a person to approve)."""
    if not enabled():
        raise CheckoutError("checkout_disabled", hint="This store has switched off ordering in chat. Hand over to a person.")
    ck = get(conversation_id)
    last = ck.get("last_order")
    if last and last.get("hash") == confirm_hash:
        return {"status": "already_placed", "order": last["number"]}, []
    s = summary(conversation_id, customer_id)
    if not s["ready"]:
        raise CheckoutError("not_ready", problems=s["problems"])
    prop = ck.get("proposal")
    if not prop or prop.get("hash") != confirm_hash or confirm_hash != s["confirm_hash"]:
        raise CheckoutError("summary_changed", hint="The cart, price or details changed since the customer saw a summary. Call review_order and ask them to confirm again.")
    if not _confirmed_after(conversation_id, int(prop.get("mid", 1 << 60))):
        raise CheckoutError("customer_has_not_confirmed", hint="Show the summary and wait for the customer's reply before placing the order.")
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    if db.get("SELECT COUNT(*) n FROM orders WHERE customer_id=? AND source='chat' AND created_at>?", [customer_id, since])["n"] >= MAX_PER_DAY:
        raise CheckoutError("too_many_orders", hint="This customer already placed several orders today. Hand over to a person.")
    if dry:
        return {"status": "checked"}, []
    method = ck["method"]
    label = s["payment_method"]
    number = None
    try:
        with db.tx():
            for l in s["lines"]:
                if db.run("UPDATE products SET stock = stock - ? WHERE sku=? AND stock >= ?", [l["qty"], l["sku"], l["qty"]]).rowcount != 1:
                    raise CheckoutError("insufficient_stock", sku=l["sku"], name=l["name"])
            number = _next_number()
            db.run("INSERT INTO orders(id,number,customer_id,channel_kind,items,shipping,zone,address,pay_status,pay_method,pay_ref,fulfillment,stage,times,created_at,source,ship_name,ship_phone) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   [number, number, customer_id, store.channel(store.conversation(conversation_id)["channel_id"])["kind"], db.dumps(s["lines"]), s["delivery"], s["zone"], s["address"],
                    "Pending", label, "", "Unfulfilled", 0, db.dumps([db.now()]), db.now(), "chat", s["name"], s["phone"]])
    except CheckoutError:
        raise
    db.run("UPDATE conversations SET cart='[]' WHERE id=?", [conversation_id])
    ck.pop("proposal", None)
    ck["last_order"] = {"hash": confirm_hash, "number": number}
    _save(conversation_id, ck)
    store.set_tag(customer_id, "Cart open", False)
    store.set_tag(customer_id, "Chat order")
    store.add_event(conversation_id, "check", f"Order {number} placed in chat", f"{label} · {s['total_text']} · {s['name']}, {s['phone']}", "ok")
    emit("orders")
    emit("products")
    from . import sms
    sms.fire(number, "placed", key=f"placed:{number}")
    after = [{"type": "payment_link", "order": number, "provider": method}] if method != "cod" else []
    return {"status": "placed", "order": number, "total": s["total"], "total_text": s["total_text"], "payment_method": label, "delivery_text": s["delivery_text"],
            "next": ("A secure payment link will be sent in this chat right after your reply." if method != "cod" else "Our team confirms by phone before the parcel ships. Pay the courier on delivery.")}, after


EXPLAIN = {
    "checkout_disabled": "Ordering in chat is switched off.",
    "not_ready": "The order is not complete (missing details, stock or over the limit).",
    "summary_changed": "The cart, a price or the details changed since the customer confirmed. Ask the assistant to confirm again.",
    "customer_has_not_confirmed": "The customer has not replied to the order summary yet.",
    "too_many_orders": "This customer already placed several orders today.",
    "insufficient_stock": "An item ran out of stock.",
}


def explain(e: CheckoutError) -> str:
    return EXPLAIN.get(e.code, e.code)


def cancel_restock(o) -> None:
    """Put a cancelled chat or staff order's units back on the shelf."""
    if o["source"] not in ("chat", "staff", "website"):     # older sample orders never took stock, so they give none back
        return
    for l in db.jl(o["items"], []):
        if o["source"] == "website" and not l.get("stock"):     # only the lines whose stock Dakbox actually took
            continue
        db.run("UPDATE products SET stock = stock + ? WHERE sku=?", [l["qty"], l["sku"]])
    emit("products")


# ---------------------------------------------------------------- after the reply is sent
async def run_after(conversation_id: str, actions: list[dict]) -> None:
    """Things that must come AFTER the assistant's confirmation message (a payment link sent first would arrive before the order number)."""
    import os
    from . import domain, metacfg, payments
    for a in actions:
        if a.get("type") != "payment_link":
            continue
        o = store.order(a["order"])
        try:
            base = metacfg.public_url() or os.environ.get("DAKBOX_LOCAL_URL", "http://localhost:4000")
            res = await payments.create_link(a["order"], a["provider"], "Assistant", base, send_in_chat=False)
            conv = store.conversation(conversation_id)
            await domain._send_assistant(conv, payments._link_text(o, store.customer(o["customer_id"]), res["url"]), None)
        except Exception as e:     # the order stands; a person sends the link
            msg = getattr(e, "message", None) or str(e)
            store.add_event(conversation_id, "alert", f"Payment link for {a['order']} could not be sent", str(msg)[:160], "warn")
            from .agent.tools import apply_handoff
            apply_handoff(conversation_id, f"payment link for {a['order']}")
            emit("conversation", id=conversation_id)


# ---------------------------------------------------------------- orders made by staff
# A person is accountable for these, so there is no summary/confirm dance and no per-day limit. What stays: live prices, stock taken
# atomically (never oversold), validated contact details, and the same order, payment and courier flow afterwards.
MAX_STAFF_UNITS = 500
MAX_STAFF_TOTAL = 10_000_000


def _merge(lines: list[dict]) -> list[dict]:
    merged: dict[str, int] = {}
    for l in lines:
        merged[l["sku"]] = merged.get(l["sku"], 0) + int(l["qty"])
    return [{"sku": k, "qty": v} for k, v in merged.items()]


def staff_quote(lines: list[dict], zone: str, shipping: int | None = None) -> dict:
    """Live prices, stock problems and delivery for a cart a person is building. Writes nothing."""
    out, problems = [], []
    for l in _merge(lines):
        p = store.product(l["sku"])
        if not p:
            problems.append({"code": "unknown_product", "sku": l["sku"]})
            continue
        ok = p["stock"] >= l["qty"]
        if not ok:
            problems.append({"code": "insufficient_stock", "sku": p["sku"], "name": p["name"], "in_stock": p["stock"], "wanted": l["qty"]})
        out.append({"sku": p["sku"], "name": p["name"], "variant": p["variant"], "price": p["price"], "qty": l["qty"], "stock": p["stock"], "ok": ok})
    if not out:
        problems.append({"code": "cart_empty"})
    if sum(x["qty"] for x in out) > MAX_STAFF_UNITS:
        problems.append({"code": "too_many_units", "limit": MAX_STAFF_UNITS})
    auto = delivery_charge(zone)
    delivery = auto if shipping is None else shipping
    sub = sum(x["price"] * x["qty"] for x in out)
    return {"lines": out, "subtotal": sub, "delivery": delivery, "autoDelivery": auto, "total": sub + delivery, "zone": zone, "problems": problems, "methods": methods()}


def _customer_for_staff(customer_id: str | None, name: str | None, phone: str | None):
    """An existing customer (by id, or the one with this number), or a new one for a walk-in or phone order."""
    if customer_id:
        c = store.customer(customer_id)
        if not c:
            raise CheckoutError("unknown_customer")
        return c
    for r in db.all("SELECT * FROM customers WHERE phone IS NOT NULL AND phone != ''"):
        if clean_phone(r["phone"]) == phone:
            return r
    return store.find_or_create_customer(f"store_{phone}", "store", name or "Customer", phone)


def staff_place(*, lines: list[dict], zone: str, name: str | None, phone: str | None, address: str | None, method: str, customer_id: str | None = None,
                shipping: int | None = None, conversation_id: str | None = None, by: str = "Staff") -> dict:
    conv = None
    if conversation_id:
        conv = store.conversation(conversation_id)
        if not conv:
            raise CheckoutError("unknown_conversation")
        if customer_id and customer_id != conv["customer_id"]:
            raise CheckoutError("customer_mismatch", hint="That conversation belongs to another customer.")
        customer_id = conv["customer_id"]
    existing = store.customer(customer_id) if customer_id else None
    nm = clean_text(name, 2, 100) if name else (existing["name"] if existing else None)
    ph = clean_phone(phone) if phone else (clean_phone(existing["phone"]) if existing and existing["phone"] else None)
    addr = clean_text(address, 10, 250)
    bad = [f for f, v in (("name", nm), ("phone", ph), ("address", addr)) if not v]
    if bad:
        raise CheckoutError("invalid_details", fields=bad, hint={"name": "Name must be 2 to 100 characters.", "phone": "Needs a Bangladesh mobile number like 01712345678.",
                                                                "address": "Needs a full delivery address (house, road, area), 10 to 250 characters."}[bad[0]])
    if method not in {m["id"] for m in methods()}:
        raise CheckoutError("method_unavailable", hint="That payment method is not connected.")
    q = staff_quote(lines, zone, shipping)
    if q["problems"]:
        raise CheckoutError("not_ready", problems=q["problems"])
    if q["total"] > MAX_STAFF_TOTAL:
        raise CheckoutError("over_limit", limit=MAX_STAFF_TOTAL)
    cust = _customer_for_staff(customer_id, nm, ph)
    label = next(m["label"] for m in methods() if m["id"] == method)
    kind = store.channel(conv["channel_id"])["kind"] if conv else "store"
    try:
        with db.tx():
            for l in q["lines"]:
                if db.run("UPDATE products SET stock = stock - ? WHERE sku=? AND stock >= ?", [l["qty"], l["sku"], l["qty"]]).rowcount != 1:
                    raise CheckoutError("insufficient_stock", sku=l["sku"], name=l["name"])
            number = _next_number()
            items = [{"sku": l["sku"], "name": l["name"], "variant": l["variant"], "price": l["price"], "qty": l["qty"]} for l in q["lines"]]
            db.run("INSERT INTO orders(id,number,customer_id,channel_kind,items,shipping,zone,address,pay_status,pay_method,pay_ref,fulfillment,stage,times,created_at,source,ship_name,ship_phone) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   [number, number, cust["id"], kind, db.dumps(items), q["delivery"], zone, addr, "Pending", label, "", "Unfulfilled", 0, db.dumps([db.now()]), db.now(), "staff", nm, ph])
    except CheckoutError:
        raise
    if not (cust["phone"] or "").strip():
        db.run("UPDATE customers SET phone=? WHERE id=?", [ph, cust["id"]])
    store.set_tag(cust["id"], "Cart open", False)
    if conv:                                # the cart became this order: empty it, and drop any summary the assistant was waiting on
        db.run("UPDATE conversations SET cart='[]' WHERE id=?", [conv["id"]])
        ck = get(conv["id"])
        ck.pop("proposal", None)
        ck["last_order"] = {"hash": None, "number": number}
        _save(conv["id"], ck)
        store.add_event(conv["id"], "check", f"Order {number} created by {by}", f"{label} · {taka(q['total'])} · {nm}, {ph}", "ok")
        emit("conversation", id=conv["id"])
    emit("orders")
    emit("products")
    from . import sms
    sms.fire(number, "placed", key=f"placed:{number}")
    return {"order": number, "total": q["total"], "payment_method": label, "delivery": q["delivery"], "customerId": cust["id"],
            "needsPaymentLink": method != "cod"}
