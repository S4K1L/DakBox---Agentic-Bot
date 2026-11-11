"""Alpha SMS (api.sms.net.bd), built to the public API page at alpha.net.bd/SMS/API.

What that page documents, and what this module does with it:
- POST /sendsms with api_key, msg, to (we only ever send ONE number per call), optional sender_id. JSON answer {error, msg, data:{request_id}}.
- GET /user/balance/ for the balance (used to verify the key when connecting).
- GET /report/request/{request_id}/ for delivery status.
What it does NOT document, and how that is handled: the full list of delivery statuses (only "Sent" and "Complete" are shown, so an
unfamiliar status is never reported as delivered), message-length and Bangla part counting (counted here with the standard 160/70
rules), rate limits, and whether the key may go in a header (it goes in the form body / query as in the examples).
There is no client reference id, so a send that times out cannot be safely repeated: it is recorded as "Unknown" and left to a person.
"""
from __future__ import annotations

import os
import re

from . import common
from .common import ProviderError, call, jbody

ID = "alphasms"
BASE = "https://api.sms.net.bd"
FIELDS = [
    {"key": "api_key", "label": "API key", "secret": True, "help": "Alpha SMS panel, API page."},
    {"key": "sender_id", "label": "Sender ID (optional)", "secret": False, "optional": True, "help": "Only if Alpha SMS has approved one for you. Leave empty to use their default."},
]
CONFIG_FIELDS: list[dict] = []
MODES: list[str] = []
HAS_REPORT = True       # delivery reports can be polled
HAS_BALANCE = True      # connecting verifies the key without sending anything
MAX_PARTS = 6

ERRORS = {
    "400": ("param", "Alpha SMS rejected the request (a missing or invalid value)."),
    "403": ("auth", "Alpha SMS says this key may not do that."),
    "405": ("auth", "Alpha SMS did not accept the API key."),
    "409": ("other", "Alpha SMS had an error on their side. Try again later."),
    "410": ("rejected", "The Alpha SMS account has expired."),
    "411": ("rejected", "The Alpha SMS reseller account is expired or suspended."),
    "412": ("param", "Alpha SMS says the schedule is invalid."),
    "413": ("param", "Alpha SMS says the sender ID is not valid or not approved."),
    "414": ("param", "The message was empty."),
    "415": ("param", "Alpha SMS says the message is too long."),
    "416": ("param", "Alpha SMS found no valid phone number."),
    "417": ("rejected", "Alpha SMS balance is too low to send. Top it up."),
    "420": ("rejected", "Alpha SMS blocked the message content."),
}


def _b() -> str:
    return os.environ.get("ALPHASMS_BASE", BASE).rstrip("/")


def msisdn(p: str | None) -> str:
    """Bangladesh mobile in the 8801XXXXXXXXX form the page's example uses."""
    d = re.sub(r"\D", "", p or "")
    if d.startswith("880"):
        d = d[3:]
    if d.startswith("0"):
        d = d[1:]
    if not re.fullmatch(r"1[3-9]\d{8}", d):
        raise ProviderError("param", "That is not a Bangladesh mobile number (01XXXXXXXXX).")
    return "880" + d


def _err(b: dict) -> ProviderError | None:
    code = str(b.get("error", "")).strip()   # the page shows a number; one of its own samples compares to a string
    if code == "0":
        return None
    kind, msg = ERRORS.get(code, ("other", "Alpha SMS did not answer as expected."))
    return ProviderError(kind, msg, code or None)


async def check(c: dict, cfg: dict) -> str:
    r = await call(ID, "GET", f"{_b()}/user/balance/", params={"api_key": c["api_key"]})
    b = jbody(r)
    if not b:
        raise ProviderError("other", "Alpha SMS did not answer as expected.")
    e = _err(b)
    if e:
        raise e
    bal = (b.get("data") or {}).get("balance")
    return f"Alpha SMS (balance {bal})" if bal is not None else "Alpha SMS"


async def send(c: dict, cfg: dict, *, to: str, text: str, ref: str) -> dict:
    """Returns {"ref": request_id, "status": "Accepted"}. A timeout raises ProviderError(kind="network"): the caller must NOT retry."""
    data = {"api_key": c["api_key"], "msg": text, "to": msisdn(to)}
    if c.get("sender_id"):
        data["sender_id"] = c["sender_id"]
    r = await call(ID, "POST", f"{_b()}/sendsms", data=data)
    b = jbody(r)
    if not b:
        raise ProviderError("network", "Alpha SMS gave no usable answer; the message may or may not have been sent.", "unclear")
    e = _err(b)
    if e:
        raise e
    rid = (b.get("data") or {}).get("request_id")
    if rid in (None, ""):
        raise ProviderError("network", "Alpha SMS accepted the request but gave no request id; the message may have been sent.", "no_id")
    return {"ref": str(rid), "status": "Accepted"}


async def report(c: dict, cfg: dict, ref: str) -> str | None:
    """Delivery state for one request: Delivered | Sent | Failed, or None when Alpha SMS says nothing we recognise."""
    if not re.fullmatch(r"\w{1,40}", ref):
        return None
    r = await call(ID, "GET", f"{_b()}/report/request/{ref}/", params={"api_key": c["api_key"]})
    b = jbody(r)
    if _err(b):
        return None
    d = b.get("data") or {}
    rec = d.get("recipients") or []
    if not rec:
        return None
    s = str((rec[0] or {}).get("status", "")).strip().lower()
    if s in ("delivered",):
        return "Delivered"
    if s in ("failed", "rejected", "undelivered", "expired", "error"):
        return "Failed"
    if s == "sent":
        return "Sent"          # handed to the operator; the page never calls this "delivered"
    return None
