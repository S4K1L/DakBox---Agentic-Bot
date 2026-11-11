"""Booking parcels with a real courier and following them to the door.

Safety rails: a parcel is booked only for an order that is ready (COD, or already paid); the COD amount is computed here and the
person booking must confirm that exact number; an order can have one parcel; tracking re-asks the courier (a webhook body is
never believed); an unrecognised status never changes an order.
"""
from __future__ import annotations

from . import auth, db, domain, sms, store
from .events import emit
from .providers import common, steadfast
from .providers.common import ProviderError
from .util import rates_for, taka

COURIERS = {"steadfast": steadfast}
NAMES = {"steadfast": "Steadfast"}


def live_couriers() -> list[str]:
    return [c for c in COURIERS if common.is_live(c)]


def cod_amount(o) -> int:
    """What the courier must collect: the whole total for unpaid COD orders, nothing for prepaid ones."""
    method = (o["pay_method"] or "").lower()
    return store.order_total(o)[1] if (o["pay_status"] == "Pending" and "cash on delivery" in method) else 0


def rate_options(o) -> list[dict]:
    zone = "dhaka" if o["zone"] == "dhaka" else "out"
    out = []
    for cid in live_couriers():
        cfg = common.config(cid)
        price = int(cfg.get("charge_dhaka" if zone == "dhaka" else "charge_out", 70 if zone == "dhaka" else 130) or 0)
        out.append({"id": cid, "name": NAMES[cid], "price": price, "window": "", "live": True, "note": "Charge as set in Dakbox; the courier bills you per your agreement."})
    if not out:  # nothing connected: clearly-labelled demo options so the screen still works
        out = [{**r, "id": "demo-" + r["id"], "live": False, "demo": True, "note": "Demo only: nothing is booked with a real courier."} for r in rates_for(zone)]
    return out


async def book(order_number: str, courier: str, by: str, expected_cod: int, note: str = "") -> dict:
    mod = COURIERS.get(courier)
    if not mod or not common.is_live(courier):
        raise domain.HttpError(409, f"Connect {NAMES.get(courier, courier)} first (Connections, Couriers).")
    o = store.order(order_number)
    if not o:
        raise domain.HttpError(404, "No such order.")
    if o["fulfillment"] != "Unfulfilled" or db.jl(o["courier"], None):
        raise domain.HttpError(409, "This order already has a parcel or has been shipped.")
    if o["pay_status"] == "Failed" or (o["pay_status"] == "Pending" and "cash on delivery" not in (o["pay_method"] or "").lower()):
        raise domain.HttpError(409, "Payment has not been received for this order yet.")
    cod = cod_amount(o)
    if int(expected_cod) != cod:
        raise domain.HttpError(409, f"The amount to collect is {taka(cod)}, not {taka(int(expected_cod))}. Review the booking and confirm again.")
    cust = store.customer(o["customer_id"])
    digits = "".join(ch for ch in o["number"] if ch.isdigit())
    try:
        res = await mod.book(common.creds(courier), invoice=digits, name=o["ship_name"] or cust["name"], phone=o["ship_phone"] or cust["phone"] or "", address=o["address"] or "", cod=cod, note=note or f"Dakbox order {o['number']}")
    except ProviderError as e:
        common.note_error(courier, e.message)
        raise domain.HttpError(502 if e.kind in ("network", "rejected") else 400, e.message)
    fee = int(common.config(courier).get("charge_dhaka" if o["zone"] == "dhaka" else "charge_out", 0) or 0)
    info = {"name": NAMES[courier], "id": courier, "consignment_id": res["consignment_id"], "track": res["tracking_code"], "eta": "Tomorrow" if o["zone"] == "dhaka" else "In 3 days",
            "status": res["status"], "cod": cod, "fee": fee}
    times = db.jl(o["times"], [])
    while len(times) < 4:
        times.append(db.now())
    times[2] = times[3] = db.now()
    db.run("UPDATE orders SET courier=?, fulfillment='In transit', stage=3, times=?, scans=? WHERE number=?",
           [db.dumps(info), db.dumps(times), db.dumps([{"x": f"Booked with {NAMES[courier]}", "t": db.now()}]), o["number"]])
    sms.fire(o["number"], "shipped", key=f"shipped:{o['number']}", tracking=res["tracking_code"], cod=cod)
    auth.audit("order.ship", f"{o['number']} via {NAMES[courier]}", f"COD {taka(cod)}")
    cid = db.get("SELECT id FROM conversations WHERE customer_id=? ORDER BY last_message_at DESC LIMIT 1", [o["customer_id"]])
    if cid:
        store.add_event(cid["id"], "truck", f"Parcel booked with {NAMES[courier]}", f"Tracking {res['tracking_code']} · COD {taka(cod)}", "ok")
    emit("orders")
    return {"tracking": res["tracking_code"], "consignment": res["consignment_id"], "cod": cod}


async def track(order_number: str) -> dict:
    """Ask the courier where the parcel is and bring the order up to date. Safe to call any time, any number of times."""
    o = store.order(order_number)
    info = db.jl(o["courier"], None) if o else None
    if not o or not info or not info.get("consignment_id") or info.get("id") not in COURIERS:
        return {"changed": False, "message": "This order has no parcel booked through a connected courier."}
    cid = info["id"]
    if not common.is_live(cid):
        return {"changed": False, "message": f"{NAMES[cid]} is not connected, so tracking cannot be refreshed."}
    try:
        raw = await COURIERS[cid].status(common.creds(cid), info["consignment_id"])
    except ProviderError as e:
        common.note_error(cid, e.message)
        return {"changed": False, "message": e.message}
    mapped = COURIERS[cid].map_status(raw)
    if not mapped:
        return {"changed": False, "message": f"The courier reported “{raw}”, which Dakbox does not recognise, so the order was left as it is."}
    fulfillment, stage, label, final = mapped
    if raw == info.get("status"):
        return {"changed": False, "message": label, "status": raw}
    info["status"] = raw
    scans = db.jl(o["scans"], [])
    scans.insert(0, {"x": label, "t": db.now()})
    times = db.jl(o["times"], [])
    while len(times) <= stage:
        times.append(db.now())
    times[stage] = db.now()
    db.run("UPDATE orders SET courier=?, fulfillment=?, stage=MAX(stage,?), scans=?, times=? WHERE number=?",
           [db.dumps(info), fulfillment, stage, db.dumps(scans), db.dumps(times), order_number])
    if fulfillment == "Delivered":
        if info.get("cod", 0) > 0 and o["pay_status"] == "Pending":
            db.run("UPDATE orders SET pay_status='Paid', pay_method='Cash on delivery (collected by courier)', pay_ref=? WHERE number=?", [f"{NAMES[cid]} {info['consignment_id']}", order_number])
        sms.fire(order_number, "delivered", key=f"delivered:{order_number}")
    conv = db.get("SELECT id FROM conversations WHERE customer_id=? ORDER BY last_message_at DESC LIMIT 1", [o["customer_id"]])
    if conv:
        store.add_event(conv["id"], "truck", f"Parcel update: {label}", f"{NAMES[cid]} · {info.get('track') or ''}", "ok" if final and fulfillment == "Delivered" else ("warn" if fulfillment == "Returned" else None))
    emit("orders")
    return {"changed": True, "message": label, "status": raw}


async def poll_all() -> int:
    """Refresh every parcel still on its way. Run on a timer so orders move even when no webhook arrives."""
    n = 0
    for o in db.all("SELECT number FROM orders WHERE fulfillment='In transit' AND courier IS NOT NULL"):
        try:
            if (await track(o["number"]))["changed"]:
                n += 1
        except Exception as e:  # one bad parcel must not stop the rest
            print("[courier poll]", repr(e))
    return n
