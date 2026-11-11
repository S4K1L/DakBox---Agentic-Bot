"""Tools the assistant can call. Shared by the Claude engine and the offline engine.

Read-only tools run immediately. Tools with side effects run immediately in Assistant mode and are
*staged* in Review mode, so nothing changes until a teammate approves the drafted reply.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .. import checkout, db, store
from ..events import emit
from ..util import is_dhaka, rates_for, taka


@dataclass
class ToolCtx:
    conversation_id: str
    customer_id: str
    channel_kind: str
    stage: bool = False  # True in Review mode
    staged: list[dict] = field(default_factory=list)
    after: list[dict] = field(default_factory=list)  # run after the reply is sent (a payment link must follow the order message)


@dataclass
class Outcome:
    result: Any
    ev: dict | None = None  # {"icon","label","detail"} shown as an activity line
    product: str | None = None


def _product_view(p) -> dict:
    return {
        "sku": p["sku"], "name": p["name"], "variant": p["variant"], "price": p["price"], "price_text": taka(p["price"]),
        "in_stock": p["stock"], "status": "out_of_stock" if p["stock"] == 0 else "low_stock" if p["stock"] <= 10 else "in_stock",
        "description": p["description"],
    }


def search_products_raw(query: str) -> list:
    q = query.lower().strip()
    if not q:
        return []
    words = [w for w in q.split() if len(w) > 2]
    scored = []
    for p in db.all("SELECT * FROM products"):
        hay = f"{p['name']} {p['variant'] or ''} {p['sku']} {p['keywords']}".lower()
        score = sum(1 for w in words if w in hay) + (2 if q in hay else 0)
        if score:
            scored.append((score, p))
    scored.sort(key=lambda x: -x[0])
    return [p for _, p in scored[:5]]


# ---------------------------------------------------------------- read-only tools
def search_products(c: ToolCtx, query: str) -> Outcome:
    rows = search_products_raw(query)
    return Outcome(
        {"count": len(rows), "products": [_product_view(p) for p in rows]},
        {"icon": "search", "label": "Searched the catalog", "detail": f"search_products · {len(rows)} result{'' if len(rows) == 1 else 's'} · 142 ms"},
        rows[0]["sku"] if rows else None,
    )


def get_product(c: ToolCtx, sku: str) -> Outcome:
    p = store.product(sku)
    if not p:
        return Outcome({"error": "not_found"}, {"icon": "search", "label": "Product not found", "detail": f"get_product · {sku}"})
    return Outcome(
        _product_view(p),
        {"icon": "package", "label": "Checked stock" if p["stock"] == 0 else "Checked a product", "detail": f"get_product · {p['stock']} in stock · 88 ms"},
        p["sku"],
    )


def get_order_status(c: ToolCtx, order_number: str, phone_last4: str | None = None) -> Outcome:
    o = store.order(order_number)
    if not o:
        return Outcome({"error": "order_not_found"}, {"icon": "truck", "label": "Looked up an order", "detail": f"get_order_status · {order_number} not found"})
    owner = store.customer(o["customer_id"])
    me = store.customer(c.customer_id)
    same = o["customer_id"] == c.customer_id and me["verified"] != "none"
    digits = "".join(ch for ch in (phone_last4 or "") if ch.isdigit())
    phone_ok = len(digits) >= 4 and bool(owner["phone"]) and "".join(ch for ch in owner["phone"] if ch.isdigit()).endswith(digits)
    if not same and not phone_ok:
        return Outcome(
            {"error": "verification_required", "hint": "Ask the customer for the last 4 digits of the phone number on the order. Do not share any order details until verified."},
            {"icon": "shield", "label": "Asked to verify the customer", "detail": "get_order_status · verification required"},
        )
    if phone_ok and not same:
        db.run("UPDATE customers SET verified='otp' WHERE id=? AND verified='none'", [c.customer_id])
    courier = db.jl(o["courier"], None)
    _, total = store.order_total(o)
    items = db.jl(o["items"], [])
    return Outcome(
        {
            "order": o["number"], "placed": o["created_at"], "payment": o["pay_status"], "fulfillment": o["fulfillment"], "total": total, "total_text": taka(total),
            "items": [f"{i['qty']} x {i['name']}" + (f" ({i['variant']})" if i.get("variant") else "") for i in items],
            "courier": {"name": courier["name"], "tracking": courier["track"], "eta": courier["eta"]} if courier else None,
        },
        {"icon": "truck", "label": f"Looked up order {o['number']}", "detail": "get_order_status · verified · 96 ms"},
    )


def get_policy(c: ToolCtx, topic: str) -> Outcome:
    t = topic.lower()
    rows = db.all("SELECT * FROM policies")
    hit = [r for r in rows if r["key"] in t or t in r["key"] or t in r["title"].lower()]
    use = hit or rows
    return Outcome(
        {"policies": [{"id": r["key"], "title": r["title"], "text": r["body"]} for r in use]},
        {"icon": "book", "label": f"Checked the {topic} policy", "detail": f"get_policy · {topic} · 70 ms"},
    )


def estimate_delivery(c: ToolCtx, district: str) -> Outcome:
    zone = "dhaka" if is_dhaka(district) else "out"
    rates = rates_for(zone)
    return Outcome(
        {
            "district": district, "zone": zone,
            "options": [{"courier": r["name"], "charge": r["price"], "charge_text": taka(r["price"]), "time": r["window"]} for r in rates],
            "note": "Example rates. Real rates are confirmed at checkout.",
        },
        {"icon": "truck", "label": f"Estimated delivery to {district}", "detail": f"estimate_delivery · {', '.join(r['name'] for r in rates[:2])} · 210 ms"},
    )


# ---------------------------------------------------------------- side-effect tools
def add_to_cart(c: ToolCtx, sku: str, qty: int = 1) -> Outcome:
    p = store.product(sku)
    qty = max(1, min(10, int(qty or 1)))
    if not p:
        return Outcome({"error": "not_found"})
    if p["stock"] < qty:
        return Outcome({"error": "insufficient_stock", "in_stock": p["stock"]})
    if c.stage:
        c.staged.append({"tool": "add_to_cart", "input": {"sku": p["sku"], "qty": qty}})
        return Outcome(
            {"status": "staged_for_approval", "line": f"{qty} x {p['name']}", "subtotal_after": taka(p["price"] * qty), "note": "A teammate approves this reply before the cart changes."},
            {"icon": "cart", "label": "Prepared a cart change", "detail": "add_to_cart · waiting for approval"},
        )
    apply_add_to_cart(c.conversation_id, p, qty)
    cart = db.jl(store.conversation(c.conversation_id)["cart"], [])
    subtotal = sum(l["price"] * l["qty"] for l in cart)
    return Outcome(
        {"status": "added", "line": f"{qty} x {p['name']}", "cart_subtotal": subtotal, "cart_subtotal_text": taka(subtotal)},
        {"icon": "cart", "label": "Updated the cart", "detail": f"add_to_cart · {qty} line · 120 ms"},
    )


def update_cart(c: ToolCtx, sku: str, qty: int) -> Outcome:
    """Set the quantity of one cart line (0 removes it)."""
    p = store.product(sku)
    if not p:
        return Outcome({"error": "not_found"})
    qty = max(0, min(10, int(qty)))
    if qty and p["stock"] < qty:
        return Outcome({"error": "insufficient_stock", "in_stock": p["stock"]})
    if c.stage:
        c.staged.append({"tool": "update_cart", "input": {"sku": p["sku"], "qty": qty}})
        return Outcome({"status": "staged_for_approval"}, {"icon": "cart", "label": "Prepared a cart change", "detail": "update_cart · waiting for approval"})
    apply_update_cart(c.conversation_id, p, qty)
    cart = db.jl(store.conversation(c.conversation_id)["cart"], [])
    sub = sum(l["price"] * l["qty"] for l in cart)
    return Outcome({"status": "updated", "cart": [f"{l['qty']} x {l['name']}" for l in cart], "cart_subtotal": sub, "cart_subtotal_text": taka(sub)},
                   {"icon": "cart", "label": "Updated the cart", "detail": f"update_cart · {p['sku']} → {qty}"})


def set_delivery_details(c: ToolCtx, name: str | None = None, phone: str | None = None, address: str | None = None, district: str | None = None, payment_method: str | None = None) -> Outcome:
    """Record what the customer said. Stores data only; nothing is ordered."""
    if not checkout.enabled():
        return Outcome({"error": "checkout_disabled", "hint": "Ordering in chat is switched off. Hand over to a person."})
    r = checkout.set_details(c.conversation_id, c.customer_id, name=name, phone=phone, address=address, district=district, payment_method=payment_method)
    return Outcome(r, {"icon": "package", "label": "Saved delivery details", "detail": "set_delivery_details · " + (f"{len(r['missing'])} still needed" if r["missing"] else "complete")})


def review_order(c: ToolCtx) -> Outcome:
    """Compute the order summary and its confirmation fingerprint."""
    if not checkout.enabled():
        return Outcome({"error": "checkout_disabled", "hint": "Ordering in chat is switched off. Hand over to a person."})
    s = checkout.propose(c.conversation_id, c.customer_id)
    return Outcome(s, {"icon": "cart", "label": "Prepared an order summary", "detail": f"review_order · {s['total_text']}" if s["ready"] else "review_order · not ready"})


def place_order(c: ToolCtx, confirm_hash: str) -> Outcome:
    """Create the order, only after the customer confirmed the exact summary."""
    try:
        if c.stage:
            checkout.place(c.conversation_id, c.customer_id, confirm_hash, dry=True)
            c.staged.append({"tool": "place_order", "input": {"confirm_hash": confirm_hash}})
            return Outcome({"status": "staged_for_approval", "note": "A teammate approves this reply before the order is created."}, {"icon": "package", "label": "Prepared an order", "detail": "place_order · waiting for approval"})
        res, after = checkout.place(c.conversation_id, c.customer_id, confirm_hash)
        c.after.extend(after)
        return Outcome(res)
    except checkout.CheckoutError as e:
        return Outcome(e.result(), {"icon": "alert", "label": "The order was not placed", "detail": f"place_order · {checkout.explain(e)}"})


def create_restock_alert(c: ToolCtx, sku: str) -> Outcome:
    p = store.product(sku)
    if not p:
        return Outcome({"error": "not_found"})
    if c.stage:
        c.staged.append({"tool": "create_restock_alert", "input": {"sku": p["sku"]}})
        return Outcome({"status": "staged_for_approval"}, {"icon": "bell", "label": "Prepared a restock alert", "detail": f"create_restock_alert · {p['sku']} · waiting for approval"})
    apply_restock(c.conversation_id, c.customer_id, p)
    return Outcome({"status": "saved", "sku": p["sku"]}, {"icon": "bell", "label": "Saved a restock alert", "detail": f"create_restock_alert · {p['sku']}"})


def request_return(c: ToolCtx, order_number: str, kind: str, reason: str) -> Outcome:
    o = store.order(order_number)
    if not o or o["customer_id"] != c.customer_id:
        return Outcome({"error": "order_not_found_for_customer"})
    inp = {"order_number": order_number, "kind": kind, "reason": reason}
    if c.stage:
        c.staged.append({"tool": "request_return", "input": inp})
        return Outcome({"status": "staged_for_approval"}, {"icon": "alert", "label": "Prepared a return request", "detail": f"request_return · {o['number']} · waiting for approval"})
    apply_return(c.conversation_id, c.customer_id, inp)
    return Outcome(
        {"status": "sent_to_team", "message": "A teammate reviews every return. Do not promise a refund or a decision."},
        {"icon": "alert", "label": "Handed to a person: return request", "detail": f"request_return · {o['number']} · needs approval"},
    )


def handoff_to_human(c: ToolCtx, reason: str) -> Outcome:
    if c.stage:
        c.staged.append({"tool": "handoff_to_human", "input": {"reason": reason}})
        return Outcome({"status": "staged_for_approval"}, {"icon": "user", "label": "Prepared a handoff", "detail": f"handoff_to_human · {reason}"})
    apply_handoff(c.conversation_id, reason)
    return Outcome({"status": "handed_off"})


def resolve_conversation(c: ToolCtx) -> Outcome:
    if c.stage:
        c.staged.append({"tool": "resolve_conversation", "input": {}})
        return Outcome({"status": "staged_for_approval"})
    apply_resolve(c.conversation_id)
    return Outcome({"status": "resolved"})


TOOLS: dict[str, Callable[..., Outcome]] = {
    f.__name__: f
    for f in (search_products, get_product, get_order_status, get_policy, estimate_delivery, add_to_cart, update_cart, set_delivery_details, review_order, place_order, create_restock_alert, request_return, handoff_to_human, resolve_conversation)
}


def call_tool(ctx: ToolCtx, tool: str, /, **kwargs: Any) -> Outcome:
    """Run a tool and record what it did as an activity line in the conversation."""
    out = TOOLS[tool](ctx, **kwargs)
    if out.ev:
        store.add_event(ctx.conversation_id, out.ev["icon"], out.ev["label"], out.ev.get("detail"))
    return out


# ---------------------------------------------------------------- effects (run now, or later on approval)
def apply_add_to_cart(conversation_id: str, p, qty: int) -> None:
    conv = store.conversation(conversation_id)
    cart = db.jl(conv["cart"], [])
    ex = next((l for l in cart if l["sku"] == p["sku"]), None)
    if ex:
        ex["qty"] += qty
    else:
        cart.append({"sku": p["sku"], "name": p["name"], "variant": p["variant"], "price": p["price"], "qty": qty})
    db.run("UPDATE conversations SET cart=? WHERE id=?", [db.dumps(cart), conversation_id])
    store.set_tag(conv["customer_id"], "Cart open")


def apply_update_cart(conversation_id: str, p, qty: int) -> None:
    conv = store.conversation(conversation_id)
    cart = [l for l in db.jl(conv["cart"], []) if l["sku"] != p["sku"]]
    if qty:
        cart.append({"sku": p["sku"], "name": p["name"], "variant": p["variant"], "price": p["price"], "qty": qty})
    db.run("UPDATE conversations SET cart=? WHERE id=?", [db.dumps(cart), conversation_id])
    store.set_tag(conv["customer_id"], "Cart open", bool(cart))


def apply_restock(conversation_id: str, customer_id: str, p) -> None:
    db.run("INSERT INTO alerts(product_id,customer_id,conversation_id,created_at) VALUES(?,?,?,?)", [p["id"], customer_id, conversation_id, db.now()])
    store.set_tag(customer_id, "Restock alert")


def apply_return(conversation_id: str, customer_id: str, inp: dict) -> None:
    o = store.order(inp["order_number"])
    pol = db.get("SELECT title, body FROM policies WHERE key = 'returns'")
    last = db.get("SELECT text, translation FROM messages WHERE conversation_id=? AND role='customer' ORDER BY id DESC LIMIT 1", [conversation_id])
    items = db.jl(o["items"], [])
    item = items[0] if items else None
    kind = "Exchange" if "exchange" in (inp.get("kind") or "").lower() else "Return"
    from datetime import timedelta
    due = (db.parse_ts(db.now()) + timedelta(hours=8)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    db.run(
        "INSERT INTO approvals(type,customer_id,conversation_id,order_number,item,amount,reason,said,said_tr,policy,status,due_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            kind, customer_id, conversation_id, o["number"], f"{item['name']}" + (f", {item['variant']}" if item.get("variant") else "") if item else o["number"],
            0 if kind == "Exchange" else (item["price"] * item["qty"] if item else 0), inp.get("reason"), last["text"] if last else inp.get("reason"),
            last["translation"] if last else None, f"{pol['title']}: {pol['body']}" if pol else None, "pending", due, db.now(),
        ],
    )
    db.run("UPDATE orders SET return_requested = 1 WHERE number = ?", [o["number"]])
    store.set_tag(customer_id, "Return request")
    apply_handoff(conversation_id, f"{kind.lower()} request")
    emit("approvals")
    emit("orders")


def apply_handoff(conversation_id: str, reason: str) -> None:
    db.run("UPDATE conversations SET mode='human', handoff_reason=? WHERE id=?", [reason, conversation_id])
    store.add_event(conversation_id, "alert", f"Handed to a person: {reason}", "Assistant paused on this conversation", "warn")


def apply_resolve(conversation_id: str) -> None:
    db.run("UPDATE conversations SET status='resolved' WHERE id=?", [conversation_id])
    store.add_event(conversation_id, "check", "Resolved by the assistant", None, "ok")


def apply_staged(conversation_id: str, customer_id: str, actions: list[dict]) -> list[dict]:
    """Run what a person just approved. Returns actions to run after the reply is sent. A refused order raises CheckoutError, so the draft stays pending."""
    after: list[dict] = []
    for a in actions:    # refuse before changing anything, so a refused order leaves no half-applied draft behind
        if a["tool"] == "place_order":
            checkout.place(conversation_id, customer_id, a["input"]["confirm_hash"], dry=True)
    for a in actions:
        t, i = a["tool"], a["input"]
        if t == "update_cart" and (p := store.product(i["sku"])):
            apply_update_cart(conversation_id, p, i["qty"])
        elif t == "place_order":
            _res, more = checkout.place(conversation_id, customer_id, i["confirm_hash"])
            after.extend(more)
        elif t == "add_to_cart" and (p := store.product(i["sku"])):
            apply_add_to_cart(conversation_id, p, i["qty"])
        elif t == "create_restock_alert" and (p := store.product(i["sku"])):
            apply_restock(conversation_id, customer_id, p)
        elif t == "request_return":
            apply_return(conversation_id, customer_id, i)
        elif t == "handoff_to_human":
            apply_handoff(conversation_id, i["reason"])
        elif t == "resolve_conversation":
            apply_resolve(conversation_id)
    return after


# ---------------------------------------------------------------- settings
DEFAULT_SETTINGS: dict[str, Any] = {
    "storeName": "Northwind Outdoor", "tone": "friendly", "replyLanguage": "match", "banglish": True, "bnDigits": True,
    "showTranslation": True, "confidence": 75, "maxOrder": 20000,
    "can": {"products": True, "carts": True, "orders": True, "returns": True, "checkout": True},
}


def agent_settings() -> dict[str, Any]:
    saved = db.get_setting("agent", {}) or {}
    out = {**DEFAULT_SETTINGS, **saved}
    out["can"] = {**DEFAULT_SETTINGS["can"], **(saved.get("can") or {})}
    return out


def allowed_tools() -> list[str]:
    s = agent_settings()
    out = ["get_policy", "estimate_delivery", "handoff_to_human", "resolve_conversation"]
    if s["can"]["products"]:
        out += ["search_products", "get_product", "create_restock_alert"]
    if s["can"]["carts"]:
        out += ["add_to_cart", "update_cart"]
        if s["can"].get("checkout", True):
            out += ["set_delivery_details", "review_order", "place_order"]
    if s["can"]["orders"]:
        out.append("get_order_status")
    if s["can"]["returns"]:
        out.append("request_return")
    return out


# JSON schemas for Claude tool use
def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or []}


TOOL_SCHEMAS: dict[str, dict] = {
    "search_products": {"description": "Search the store catalog by name, type, color or SKU. Returns live price and stock.", "input_schema": _obj({"query": {"type": "string", "description": 'What the customer is looking for, in English, e.g. "navy water bottle".'}}, ["query"])},
    "get_product": {"description": "Get one product by SKU with live price and stock.", "input_schema": _obj({"sku": {"type": "string"}}, ["sku"])},
    "get_order_status": {"description": "Look up an order. Only returns details when the customer is verified; otherwise returns verification_required and you must ask for the last 4 digits of the phone number on the order.", "input_schema": _obj({"order_number": {"type": "string", "description": "e.g. #1042"}, "phone_last4": {"type": "string", "description": "Last 4 digits of the phone on the order, if the customer gave them."}}, ["order_number"])},
    "get_policy": {"description": "Read the store policy for a topic: returns, exchange, shipping, pricing or payment. Always use this before answering a policy question.", "input_schema": _obj({"topic": {"type": "string", "enum": ["returns", "exchange", "shipping", "pricing", "payment"]}}, ["topic"])},
    "estimate_delivery": {"description": "Estimate delivery charge and time to a district or area in Bangladesh.", "input_schema": _obj({"district": {"type": "string"}}, ["district"])},
    "add_to_cart": {"description": "Add a product to the customer cart. Only call this after the customer clearly confirmed they want it in this conversation.", "input_schema": _obj({"sku": {"type": "string"}, "qty": {"type": "integer", "minimum": 1, "maximum": 10}}, ["sku"])},
    "update_cart": {"description": "Change the quantity of one line in the customer cart (qty 0 removes it). Only when the customer asked for the change.", "input_schema": _obj({"sku": {"type": "string"}, "qty": {"type": "integer", "minimum": 0, "maximum": 10}}, ["sku", "qty"])},
    "set_delivery_details": {"description": "Save delivery details the customer gave you in this conversation: recipient name, Bangladesh mobile number, full address, district and payment method. Pass only what the customer actually said; never invent or guess a value. Returns what is still missing and the payment methods that are available (do not offer others).", "input_schema": _obj({"name": {"type": "string"}, "phone": {"type": "string", "description": "e.g. 01712345678"}, "address": {"type": "string", "description": "House, road, area as the customer wrote it."}, "district": {"type": "string"}, "payment_method": {"type": "string", "description": "cod, bkash, sslcommerz or aamarpay, from the available list only."}})},
    "review_order": {"description": "Once the cart and all delivery details are complete, compute the order summary (live prices, delivery charge, total). Show every line, the delivery charge, the total, the recipient, phone, address and payment method to the customer and ask them to confirm. Never call place_order in the same turn.", "input_schema": _obj({})},
    "place_order": {"description": "Create the order. Only call this after review_order, after the summary was shown to the customer, and after the customer's NEXT message clearly confirmed it (yes, confirm, ok place it). Pass the confirm_hash from review_order. If anything changed since, it is refused: call review_order again. If it is refused for a limit, hand over to a person.", "input_schema": _obj({"confirm_hash": {"type": "string"}}, ["confirm_hash"])},
    "create_restock_alert": {"description": "Save a back-in-stock alert for an out-of-stock product. Only after the customer asked to be notified.", "input_schema": _obj({"sku": {"type": "string"}}, ["sku"])},
    "request_return": {"description": "Send a return, refund or exchange request to the human team for approval. You cannot approve it. Use when a delivered item is damaged or wrong and the customer asks for a refund, replacement or exchange.", "input_schema": _obj({"order_number": {"type": "string"}, "kind": {"type": "string", "enum": ["refund", "replacement", "exchange"]}, "reason": {"type": "string"}}, ["order_number", "kind", "reason"])},
    "handoff_to_human": {"description": "Hand the conversation to a person. Use for complaints, anger, legal topics, refund disputes, anything outside policy, or when the customer asks for a person.", "input_schema": _obj({"reason": {"type": "string", "description": 'Short reason shown to staff, e.g. "refund request".'}}, ["reason"])},
    "resolve_conversation": {"description": "Mark the conversation resolved once the customer confirmed they need nothing else (for example said thanks).", "input_schema": _obj({})},
}
