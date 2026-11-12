"""Orders that customers place on the shop's own website, pushed to Dakbox the moment they happen.

Shopify and WooCommerce can POST every order to a web address (a webhook). Any other site, plugin or tool (Zapier, a form) can
POST a small JSON order in Dakbox's own format. Every request must carry an HMAC-SHA256 signature of the raw body made with the secret
shared with that website, or it is refused (routes/shop_orders.py). Payload shapes below are written from the public documentation of
Shopify and WooCommerce and have never been checked against a real shop.

What Dakbox does with an order:
- It is created once. The shop retries and sends several events per order (created, paid, updated, cancelled), so the order is keyed by
  (website, the website's order id) and later events only move it forward: unpaid to paid, to cancelled. Staff edits are never overwritten.
- The customer is matched by phone number, or created. The order shows as "From website", with the website's own order number.
- Product lines are linked to the imported catalogue (same product id the import used, else by SKU). Linked lines take stock off Dakbox's own
  count so it does not drift from the shop; an order is never refused for stock, because the website already sold it.
- What the customer was charged is kept (discounts and tax included): that is the total shown, and the cash-on-delivery amount to collect.
- Prices in a currency other than Taka are not imported unless the owner accepted that currency when connecting the website.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from . import checkout, db, store
from .catalog_import import parse_price
from .events import emit
from .util import is_dhaka


BAD_SIGNATURE = "A request arrived with a wrong signature. Check that the secret in the shop matches the one here."


class ShopOrderError(Exception):
    """Something about the order that staff should hear about; shown on the connected website's card."""


@dataclass
class Line:
    name: str
    qty: int
    unit: int                       # price per unit actually charged (after the line's discount)
    sku: str | None = None
    variant: str | None = None
    key: str | None = None          # the product id the catalogue import used: shopify:<variant id> or woo:<product id>


@dataclass
class Parsed:
    platform: str                   # shopify | woo | generic
    ext_id: str
    number: str | None
    lines: list[Line]
    currency: str | None = None
    shipping: int = 0
    total: int | None = None
    paid: bool = False
    failed: bool = False
    refunded: bool = False
    cancelled: bool = False
    cod: bool = False
    gateway: str | None = None
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    cust_key: str | None = None
    ignore: str | None = None       # a reason this event is not an order (a ping, a draft)


def _s(v) -> str | None:
    return v.strip() if isinstance(v, str) and v.strip() else None


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _join(*parts) -> str:
    return ", ".join(p for p in (_s(x) for x in parts) if p)


# ---------------------------------------------------------------- Shopify
def parse_shopify(o: dict) -> Parsed:
    lines = []
    for li in o.get("line_items") or []:
        qty = int(_num(li.get("quantity")))
        if qty <= 0:
            continue
        line_total = _num(li.get("price")) * qty - _num(li.get("total_discount"))
        vid = li.get("variant_id")
        vt = _s(li.get("variant_title"))
        lines.append(Line(name=_s(li.get("title")) or _s(li.get("name")) or "Item", qty=qty, unit=max(0, int(line_total / qty + 0.5)), sku=_s(li.get("sku")),
                          variant=vt if vt and vt.lower() != "default title" else None, key=f"shopify:{vid}" if vid else None))
    ship = o.get("shipping_address") or o.get("billing_address") or {}
    cust = o.get("customer") or {}
    sset = ((o.get("total_shipping_price_set") or {}).get("shop_money") or {}).get("amount")
    shipping = _num(sset) if sset is not None else sum(_num(x.get("price")) for x in (o.get("shipping_lines") or []))
    fin = (o.get("financial_status") or "").lower()
    gws = [g for g in (o.get("payment_gateway_names") or [o.get("gateway")]) if isinstance(g, str) and g.strip()]
    cod = any(re.search(r"cash on delivery|\bcod\b", g, re.I) for g in gws)
    name = _s(ship.get("name")) or _s(_join(cust.get("first_name"), cust.get("last_name")).replace(", ", " "))
    return Parsed(
        platform="shopify", ext_id=str(o.get("id") or ""), number=_s(o.get("name")) or (f"#{o['order_number']}" if o.get("order_number") else None), lines=lines,
        currency=_s(o.get("currency")), shipping=int(shipping + 0.5), total=parse_price(o.get("total_price")), paid=fin in ("paid", "partially_refunded"),
        failed=fin == "voided", refunded=fin == "refunded", cancelled=bool(o.get("cancelled_at")), cod=cod, gateway=gws[0] if gws else None, name=name,
        phone=_s(ship.get("phone")) or _s(o.get("phone")) or _s(cust.get("phone")) or _s((o.get("billing_address") or {}).get("phone")),
        email=_s(o.get("email")) or _s(cust.get("email")), address=_join(ship.get("address1"), ship.get("address2"), ship.get("city"), ship.get("province"), ship.get("zip")),
        cust_key=str(cust.get("id") or o.get("email") or o.get("id") or ""))


# ---------------------------------------------------------------- WooCommerce
def parse_woo(o: dict) -> Parsed:
    status = (o.get("status") or "").lower()
    lines = []
    for li in o.get("line_items") or []:
        qty = int(_num(li.get("quantity")))
        if qty <= 0:
            continue
        lines.append(Line(name=_s(li.get("name")) or "Item", qty=qty, unit=max(0, int(_num(li.get("total")) / qty + 0.5)), sku=_s(li.get("sku")),
                          key=f"woo:{li.get('product_id')}" if li.get("product_id") else None))
    bill, ship = o.get("billing") or {}, o.get("shipping") or {}
    addr_src = ship if _s(ship.get("address_1")) else bill
    name = _s(_join(ship.get("first_name"), ship.get("last_name")).replace(", ", " ")) or _s(_join(bill.get("first_name"), bill.get("last_name")).replace(", ", " "))
    cod = (o.get("payment_method") or "").lower() == "cod"
    return Parsed(
        platform="woo", ext_id=str(o.get("id") or ""), number=f"#{o['number']}" if o.get("number") else None, lines=lines, currency=_s(o.get("currency")),
        shipping=int(_num(o.get("shipping_total")) + _num(o.get("shipping_tax")) + 0.5), total=parse_price(o.get("total")),
        paid=bool(o.get("date_paid") or o.get("date_paid_gmt")), failed=status == "failed", refunded=status == "refunded", cancelled=status == "cancelled", cod=cod,
        gateway=_s(o.get("payment_method_title")) or _s(o.get("payment_method")), name=name, phone=_s(ship.get("phone")) or _s(bill.get("phone")), email=_s(bill.get("email")),
        address=_join(addr_src.get("address_1"), addr_src.get("address_2"), addr_src.get("city"), addr_src.get("state"), addr_src.get("postcode")),
        cust_key=str(o.get("customer_id") or bill.get("email") or o.get("id") or ""),
        ignore="draft" if status in ("auto-draft", "checkout-draft", "trash") else None)


# ---------------------------------------------------------------- Dakbox's own format (any other site, a plugin, Zapier)
def parse_generic(o: dict) -> Parsed:
    lines = []
    for li in o.get("lines") or []:
        qty = int(_num(li.get("qty")))
        if qty > 0:
            lines.append(Line(name=_s(li.get("name")) or _s(li.get("sku")) or "Item", qty=qty, unit=max(0, int(_num(li.get("price")) + 0.5)), sku=_s(li.get("sku")), variant=_s(li.get("variant"))))
    return Parsed(
        platform="generic", ext_id=str(o.get("id") or ""), number=_s(str(o.get("number") or "")), lines=lines, currency=_s(o.get("currency")),
        shipping=int(_num(o.get("shipping")) + 0.5), total=parse_price(o.get("total")), paid=bool(o.get("paid")), failed=bool(o.get("failed")), refunded=bool(o.get("refunded")),
        cancelled=bool(o.get("cancelled")), cod=bool(re.search(r"cash on delivery|\bcod\b", str(o.get("payment_method") or ""), re.I)), gateway=_s(o.get("payment_method")),
        name=_s(o.get("name")), phone=_s(o.get("phone")), email=_s(o.get("email")), address=_join(o.get("address"), o.get("city")), cust_key=str(o.get("customer_id") or o.get("email") or o.get("phone") or o.get("id") or ""))


def parse(body: dict, headers: dict) -> Parsed:
    h = {k.lower(): v for k, v in headers.items()}
    shop_topic, woo_topic = h.get("x-shopify-topic", ""), h.get("x-wc-webhook-topic", "")
    if shop_topic and not shop_topic.startswith("orders/"):
        return Parsed("shopify", "", None, [], ignore=f"not an order event ({shop_topic})")
    if woo_topic and not woo_topic.startswith("order."):
        return Parsed("woo", "", None, [], ignore=f"not an order event ({woo_topic})")
    if woo_topic == "order.deleted":
        return Parsed("woo", "", None, [], ignore="deleted orders are left as they are")
    if shop_topic or ("financial_status" in body and "line_items" in body):
        p = parse_shopify(body)
    elif woo_topic or ("line_items" in body and "payment_method" in body):
        p = parse_woo(body)
    elif "lines" in body:
        p = parse_generic(body)
    else:
        raise ShopOrderError("The order was not in a format Dakbox understands (no line items).")
    if not p.ignore and not p.ext_id:
        raise ShopOrderError("The order has no id, so it cannot be recognised if the shop sends it again.")
    if not p.ignore and not p.lines:
        p.ignore = "no items"
    return p


# ---------------------------------------------------------------- saving
def _match_product(host: str, line: Line):
    if line.key:
        p = db.get("SELECT * FROM products WHERE source=? AND source_id=?", [host, line.key])
        if p:
            return p
    if line.sku:
        return db.get("SELECT * FROM products WHERE lower(sku)=lower(?)", [line.sku])
    return None


def _customer(host: str, p: Parsed):
    phone = checkout.clean_phone(p.phone)
    if phone:
        for r in db.all("SELECT * FROM customers WHERE phone IS NOT NULL AND phone != ''"):
            if checkout.clean_phone(r["phone"]) == phone:
                return r, phone
    name = checkout.clean_text(p.name, 2, 100) or (p.email.split("@")[0] if p.email else None) or "Website customer"
    return store.find_or_create_customer(f"site_{host}_{p.cust_key or p.ext_id}", "site", name, phone), phone


def _pay(p: Parsed) -> tuple[str, str]:
    if p.cod:
        return ("Paid", "Cash on delivery (collected)") if p.paid else ("Pending", "Cash on delivery")
    label = f"{p.gateway} (website)" if p.gateway else "Paid on website"
    if p.refunded:
        return "Refunded", label
    return ("Paid" if p.paid else ("Failed" if p.failed else "Pending")), label


def ingest(src, p: Parsed) -> dict:
    """Create the order, or move an existing one forward. `src` is the catalog_sources row of the website."""
    host = src["host"]
    if p.currency and p.currency.upper() not in ("BDT", (src["currency"] or "").upper()):
        raise ShopOrderError(f"Order {p.number or p.ext_id} is in {p.currency.upper()}, not Taka, so it was not imported. "
                             "To accept it, import the website's products again and confirm the currency.")
    existing = db.get("SELECT * FROM orders WHERE ext_source=? AND ext_id=?", [host, p.ext_id])
    if existing:
        return _advance(existing, p)
    if p.cancelled:
        return {"ignored": "cancelled before it reached Dakbox"}

    cust, phone = _customer(host, p)
    items, short = [], []
    for ln in p.lines:
        prod = _match_product(host, ln)
        it = {"sku": prod["sku"] if prod else (ln.sku or f"WEB-{hashlib.sha1((ln.key or ln.name).encode()).hexdigest()[:8].upper()}"), "name": ln.name[:100],
              "variant": ln.variant, "price": ln.unit, "qty": ln.qty}
        if prod:
            it["stock"] = True            # Dakbox took this line's stock, so a cancellation gives it back
            if prod["stock"] < ln.qty:
                short.append(prod["name"])
        items.append(it)
    sub = sum(i["price"] * i["qty"] for i in items)
    site_total = p.total if p.total is not None and p.total != sub + p.shipping else None
    addr = checkout.clean_text(p.address, 1, 250) or "Not given"
    zone = "dhaka" if is_dhaka(p.address or "") else "out"
    pay_status, pay_method = _pay(p)
    paid = pay_status == "Paid"
    times = [db.now()] + ([db.now()] if paid else [])
    with db.tx():
        for it in items:
            if it.get("stock"):
                db.run("UPDATE products SET stock = MAX(0, stock - ?) WHERE sku=?", [it["qty"], it["sku"]])
        number = checkout._next_number()
        db.run("INSERT INTO orders(id,number,customer_id,channel_kind,items,shipping,zone,address,pay_status,pay_method,pay_ref,fulfillment,stage,times,created_at,source,ship_name,ship_phone,ext_source,ext_id,ext_number,site_total) "
               "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               [number, number, cust["id"], "site", db.dumps(items), p.shipping, zone, addr, pay_status, pay_method, "", "Unfulfilled", 1 if paid else 0, db.dumps(times), db.now(),
                "website", checkout.clean_text(p.name, 2, 100) or cust["name"], phone, host, p.ext_id, p.number, site_total])
    if not (cust["phone"] or "").strip() and phone:
        db.run("UPDATE customers SET phone=? WHERE id=?", [phone, cust["id"]])
    store.set_tag(cust["id"], "Website order")
    note = f"from {host}, website order {p.number or p.ext_id}" + (f" · stock short for {', '.join(short)}" if short else "")
    from . import auth
    auth.audit("order.website", number, note)
    emit("orders")
    emit("products")
    if src["order_sms"]:
        from . import sms
        sms.fire(number, "placed", key=f"placed:{number}")
    return {"created": number, "total": store.order_total(store.order(number))[1], "stockShort": short}


def _advance(o, p: Parsed) -> dict:
    """The shop sent the same order again (paid, updated, cancelled). Move it forward, never back, and never touch what staff changed."""
    did = []
    if p.cancelled and o["fulfillment"] != "Cancelled":
        if o["stage"] >= 3:
            did.append("cancelled on the website, but already shipped: check it")
            from . import auth
            auth.audit("order.website", o["number"], "cancelled on the website after shipping; left as it was")
        else:
            db.run("UPDATE orders SET fulfillment='Cancelled' WHERE number=?", [o["number"]])
            checkout.cancel_restock(o)
            did.append("cancelled")
    pay_status, pay_method = _pay(p)
    if o["pay_status"] == "Pending" and pay_status in ("Paid", "Failed", "Refunded"):
        times = db.jl(o["times"], [])
        if pay_status == "Paid":
            while len(times) < 2:
                times.append(db.now())
            times[1] = db.now()
        db.run("UPDATE orders SET pay_status=?, pay_method=?, stage=MAX(stage,?), times=? WHERE number=?", [pay_status, pay_method, 1 if pay_status == "Paid" else 0, db.dumps(times), o["number"]])
        did.append(pay_status.lower())
    elif o["pay_status"] == "Paid" and pay_status == "Refunded":
        db.run("UPDATE orders SET pay_status='Refunded' WHERE number=?", [o["number"]])
        did.append("refunded")
    if did:
        emit("orders")
        emit("products")
    return {"updated": o["number"], "changes": did}


# ---------------------------------------------------------------- the shared secret and the signature
def webhook_path(src) -> str:
    from . import publicbiz
    return f"/webhooks/shop{publicbiz.seg()}/{src['id']}"


def secret_of(src) -> str | None:
    from .secrets_store import unseal
    return unseal(src["order_secret"])


def ensure_secret(src) -> str | None:
    """Woo and other sites use a secret Dakbox makes. Shopify makes its own: the owner pastes it, so none is made here (the webhook stays shut until then)."""
    sec = secret_of(src)
    if sec or src["kind"] == "shopify":
        return sec
    import secrets as pysecrets
    from .secrets_store import seal
    sec = pysecrets.token_urlsafe(24)
    db.run("UPDATE catalog_sources SET order_secret=? WHERE id=?", [seal(sec), src["id"]])
    return sec


def verify(secret: str, raw: bytes, headers: dict) -> bool:
    """Shopify (X-Shopify-Hmac-Sha256) and WooCommerce (X-WC-Webhook-Signature) send base64(HMAC-SHA256(secret, body)); Dakbox's own format may send
    hex, optionally written sha256=<hex>, in X-Dakbox-Signature."""
    import base64
    import hmac
    h = {k.lower(): v for k, v in headers.items()}
    mac = hmac.new(secret.encode(), raw, hashlib.sha256).digest()
    b64, hx = base64.b64encode(mac).decode(), mac.hex()
    got = [(h.get("x-shopify-hmac-sha256"), b64), (h.get("x-wc-webhook-signature"), b64), ((h.get("x-dakbox-signature") or "").removeprefix("sha256="), hx)]
    return any(g and hmac.compare_digest(g.encode(), want.encode()) for g, want in got)


def note_result(src, error: str | None) -> None:
    """What the connected website's card shows: when the last order came and what went wrong, if anything."""
    if error is None:
        db.run("UPDATE catalog_sources SET orders_at=?, orders_count=orders_count+1, orders_error=NULL WHERE id=?", [db.now(), src["id"]])
    else:
        db.run("UPDATE catalog_sources SET orders_error=? WHERE id=?", [error[:300], src["id"]])
