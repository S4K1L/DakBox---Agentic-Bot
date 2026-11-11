"""Steadfast Courier.

!! NOT VERIFIED AGAINST STEADFAST'S OFFICIAL DOCUMENTATION. Their API reference is only available to logged-in merchants, so the
paths, header names and status values here come from community SDKs and recall. Safety rails compensate: connecting requires a
successful live balance call (so a wrong address or key fails immediately), every booking is confirmed by staff with the COD
amount shown, tracking re-queries Steadfast instead of trusting a webhook body, and unknown statuses never change an order.
Check this file against the docs in your Steadfast merchant dashboard before relying on it.
"""
from __future__ import annotations

import re

from . import common
from .common import ProviderError, call, jbody

ID = "steadfast"
BASE = "https://portal.packzy.com/api/v1"
FIELDS = [
    {"key": "api_key", "label": "API key", "secret": True, "help": "Steadfast merchant dashboard, API settings."},
    {"key": "secret_key", "label": "Secret key", "secret": True, "help": "Shown next to the API key."},
]
CONFIG_FIELDS = [
    {"key": "charge_dhaka", "label": "Delivery charge inside Dhaka (৳)", "default": "70", "help": "Steadfast bills you under your agreement; this is only what Dakbox shows staff and customers as the charge."},
    {"key": "charge_out", "label": "Delivery charge outside Dhaka (৳)", "default": "130", "help": ""},
]
MODES: list[str] = []   # one environment

# Delivery status -> (Dakbox fulfillment, stage, label, final?)
STATUS = {
    "pending": ("In transit", 3, "Booked, waiting for pickup", False),
    "in_review": ("In transit", 3, "Booked, in review by Steadfast", False),
    "hold": ("In transit", 3, "On hold at Steadfast", False),
    "delivered_approval_pending": ("In transit", 4, "Delivered, awaiting Steadfast approval", False),
    "partial_delivered_approval_pending": ("In transit", 4, "Partly delivered, awaiting approval", False),
    "cancelled_approval_pending": ("In transit", 3, "Cancellation awaiting approval", False),
    "unknown_approval_pending": ("In transit", 3, "Status awaiting approval", False),
    "delivered": ("Delivered", 5, "Delivered", True),
    "partial_delivered": ("Delivered", 5, "Partly delivered", True),
    "cancelled": ("Returned", 3, "Cancelled / returned by Steadfast", True),
}


def _b() -> str:
    import os
    return os.environ.get("STEADFAST_BASE", BASE).rstrip("/")


def _h(c: dict) -> dict:
    return {"Api-Key": c["api_key"], "Secret-Key": c["secret_key"], "Content-Type": "application/json", "Accept": "application/json"}


def bd_phone(p: str | None) -> str:
    d = re.sub(r"\D", "", p or "")
    if d.startswith("880"):
        d = "0" + d[3:]
    if not re.fullmatch(r"01[3-9]\d{8}", d):
        raise ProviderError("param", "The customer's phone must be an 11-digit Bangladesh mobile number (01XXXXXXXXX).")
    return d


def map_status(s: str | None):
    return STATUS.get((s or "").lower())


async def check(c: dict, cfg: dict) -> str:
    r = await call(ID, "GET", f"{_b()}/get_balance", headers=_h(c))
    b = jbody(r)
    if r.status_code in (401, 403) or (b.get("status") not in (200, "200", None) and "current_balance" not in b):
        raise ProviderError("auth", "Steadfast rejected the API key or secret key.")
    if "current_balance" not in b:
        raise ProviderError("other", "Steadfast did not answer as expected. Check the keys, and see the note about unverified docs.")
    return f"Steadfast (balance ৳{b['current_balance']})"


async def book(c: dict, *, invoice: str, name: str, phone: str, address: str, cod: int, note: str) -> dict:
    addr = " ".join(address.split())
    if not (10 <= len(addr) <= 250):
        raise ProviderError("param", "The delivery address must be between 10 and 250 characters.")
    body = {"invoice": invoice, "recipient_name": name[:100], "recipient_phone": bd_phone(phone), "recipient_address": addr,
            "cod_amount": int(cod), "note": note[:200]}
    r = await call(ID, "POST", f"{_b()}/create_order", headers=_h(c), json=body, timeout=35)
    b = jbody(r)
    con = b.get("consignment") or {}
    if b.get("status") != 200 or not con.get("consignment_id"):
        msg = b.get("message") or "Steadfast did not create the parcel."
        if isinstance(b.get("errors"), dict) and b["errors"]:
            msg = "; ".join(f"{k}: {', '.join(map(str, v)) if isinstance(v, list) else v}" for k, v in list(b["errors"].items())[:3])
        raise ProviderError("rejected", f"Steadfast said: {str(msg)[:200]}")
    if int(float(con.get("cod_amount", cod))) != int(cod):
        raise ProviderError("rejected", "Steadfast recorded a different COD amount than requested. Check this parcel in the Steadfast dashboard before going on.")
    return {"consignment_id": str(con["consignment_id"]), "tracking_code": con.get("tracking_code"), "status": con.get("status") or "in_review"}


async def status(c: dict, consignment_id: str) -> str | None:
    if not re.fullmatch(r"\d{1,15}", str(consignment_id)):
        raise ProviderError("param", "That consignment id is not valid.")
    r = await call(ID, "GET", f"{_b()}/status_by_cid/{consignment_id}", headers=_h(c))
    b = jbody(r)
    if r.status_code in (401, 403):
        raise ProviderError("auth", "Steadfast rejected the keys.")
    return b.get("delivery_status")
