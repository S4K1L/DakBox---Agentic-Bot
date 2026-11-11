"""Data access shared by the API, the agent and the channel adapters."""
from __future__ import annotations

import sqlite3
from typing import Any

from . import db
from .events import emit
from .util import hue_for, initials


def product(sku_or_id: str) -> sqlite3.Row | None:
    return db.get("SELECT * FROM products WHERE sku = ? OR id = ?", [sku_or_id, sku_or_id])


def customer(cid: str) -> sqlite3.Row | None:
    return db.get("SELECT * FROM customers WHERE id = ?", [cid])


def channel(cid: str) -> sqlite3.Row | None:
    return db.get("SELECT * FROM channels WHERE id = ?", [cid])


def conversation(cid: str) -> sqlite3.Row | None:
    return db.get("SELECT * FROM conversations WHERE id = ?", [cid])


def order(number: str) -> sqlite3.Row | None:
    n = number.strip()
    return db.get("SELECT * FROM orders WHERE number = ?", [n if n.startswith("#") else f"#{n}"])


def order_total(o: sqlite3.Row) -> tuple[int, int]:
    items = db.jl(o["items"], [])
    subtotal = sum(i["price"] * i["qty"] for i in items)
    return subtotal, subtotal + o["shipping"]


def add_message(
    conversation_id: str,
    role: str,
    text: str = "",
    *,
    author: str | None = None,
    translation: str | None = None,
    meta: dict | None = None,
    delivery: str | None = None,
    created_at: str | None = None,
    external_id: str | None = None,
) -> int | None:
    """Returns the new message id, or None when external_id was already stored (a duplicate webhook delivery)."""
    at = created_at or db.now()
    try:
        cur = db.run(
            "INSERT INTO messages(conversation_id,role,author,text,translation,meta,delivery,created_at,external_id) VALUES(?,?,?,?,?,?,?,?,?)",
            [conversation_id, role, author, text, translation, db.dumps(meta) if meta else None, delivery, at, external_id],
        )
    except __import__("sqlite3").IntegrityError:
        return None
    if role != "event":
        conv = conversation(conversation_id)
        unread = conv["unread"] + 1 if role == "customer" else 0
        window = (db.parse_ts(at) + __import__("datetime").timedelta(hours=24)).isoformat(timespec="milliseconds").replace("+00:00", "Z") if role == "customer" else conv["window_expires_at"]
        db.run(
            "UPDATE conversations SET preview=?, last_message_at=?, unread=?, window_expires_at=?, status=CASE WHEN ?='customer' THEN 'open' ELSE status END WHERE id=?",
            [text[:140], at, unread, window, role, conversation_id],
        )
        db.run("UPDATE channels SET last_message_at=? WHERE id=?", [at, conv["channel_id"]])
    emit("conversation", id=conversation_id)
    return cur.lastrowid


def add_event(conversation_id: str, icon: str, label: str, detail: str | None = None, tone: str | None = None) -> int:
    return add_message(conversation_id, "event", label, meta={"icon": icon, "detail": detail, "tone": tone})


def _link(kind: str, external_id: str, customer_id: str) -> None:
    db.run("INSERT OR IGNORE INTO identities(kind, external_id, customer_id) VALUES(?,?,?)", [kind, external_id, customer_id])


def find_or_create_customer(external_id: str, channel_kind: str, name: str, phone: str | None = None, lang: str = "en") -> sqlite3.Row:
    """One customer can have one identity per channel (a WhatsApp number, a Messenger PSID, ...). A phone match links them."""
    ident = db.get("SELECT customer_id FROM identities WHERE kind=? AND external_id=?", [channel_kind, external_id])
    if ident:
        return customer(ident["customer_id"])
    if phone:
        by_phone = db.get("SELECT * FROM customers WHERE phone = ?", [phone])
        if by_phone:
            _link(channel_kind, external_id, by_phone["id"])
            if channel_kind == "wa":
                db.run("UPDATE customers SET verified=CASE WHEN verified='none' THEN 'phone' ELSE verified END WHERE id=?", [by_phone["id"]])
            return customer(by_phone["id"])
    cid = db.uid("cus")
    db.run(
        "INSERT INTO customers(id,name,phone,lang,area,verified,tags,hue,external_id,channel_kind,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        [cid, name, phone, lang, None, "phone" if phone and channel_kind == "wa" else "none", db.dumps(["Prospect"]), hue_for(name), external_id, channel_kind, db.now()],
    )
    _link(channel_kind, external_id, cid)
    return customer(cid)


def recipient_id(cust, channel_kind: str) -> str | None:
    """The ID to address this customer by on a given channel."""
    r = db.get("SELECT external_id FROM identities WHERE customer_id=? AND kind=?", [cust["id"], channel_kind])
    return r["external_id"] if r else (cust["external_id"] if cust["channel_kind"] == channel_kind else None)


def find_or_create_conversation(customer_id: str, channel_id: str) -> sqlite3.Row:
    ex = db.get(
        "SELECT * FROM conversations WHERE customer_id = ? AND channel_id = ? ORDER BY last_message_at DESC LIMIT 1", [customer_id, channel_id]
    )
    if ex:
        return ex
    cid = db.uid("cv")
    db.run(
        "INSERT INTO conversations(id,customer_id,channel_id,mode,status,unread,preview,last_message_at,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        [cid, customer_id, channel_id, "agent", "open", 0, "", db.now(), db.now()],
    )
    return conversation(cid)


def customer_view(c: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": c["id"], "name": c["name"], "initials": initials(c["name"]), "hue": c["hue"], "phone": c["phone"], "lang": c["lang"],
        "area": c["area"], "verified": c["verified"], "tags": db.jl(c["tags"], []), "since": c["created_at"],
    }


def customer_stats(customer_id: str) -> dict[str, Any]:
    rows = db.all("SELECT * FROM orders WHERE customer_id = ? AND fulfillment != 'Cancelled' ORDER BY created_at DESC", [customer_id])
    spent = sum(order_total(o)[1] for o in rows if o["pay_status"] == "Paid")
    return {"orders": len(rows), "spent": spent, "last": rows[0]["created_at"] if rows else None}


def set_tag(customer_id: str, tag: str, on: bool = True) -> None:
    c = customer(customer_id)
    if not c:
        return
    tags = list(dict.fromkeys(db.jl(c["tags"], [])))
    if on and tag not in tags:
        tags.append(tag)
    if not on and tag in tags:
        tags.remove(tag)
    db.run("UPDATE customers SET tags=? WHERE id=?", [db.dumps(tags), customer_id])


def order_log(number: str, channel: str, text: str, status: str = "Delivered", mid: str | None = None) -> None:
    """Add a line to an order's customer-message log (shown under Messages to the customer). `mid` ties a line to an SMS row."""
    o = order(number)
    if not o:
        return
    log = db.jl(o["log"], [])
    line = {"c": channel, "x": text, "s": status, "t": db.now()}
    if mid:
        line["m"] = mid
    log.insert(0, line)
    db.run("UPDATE orders SET log=? WHERE number=?", [db.dumps(log), number])


def order_log_status(number: str, mid: str, status: str) -> None:
    o = order(number)
    if not o:
        return
    log = db.jl(o["log"], [])
    for line in log:
        if line.get("m") == mid:
            line["s"] = status
    db.run("UPDATE orders SET log=? WHERE number=?", [db.dumps(log), number])
