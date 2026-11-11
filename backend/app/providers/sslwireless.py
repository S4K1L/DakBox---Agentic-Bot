"""SSL Wireless ISMS Plus (smsplus.sslwireless.com/api/v3), built to the API page at ismsplus.sslwireless.com/api-documentation.

Documented and used: POST /send-sms with api_token, sid, msisdn, sms, csms_id (a unique client reference, 20 characters) answering
{status, status_code, error_message, smsinfo[{sms_status, msisdn, sms_type, csms_id, reference_id}]}. The csms_id makes a repeat of the same
request safe: a second send with the same id comes back DUPLICATE instead of texting twice, so a timed-out send is retried once with it.
NOT documented, so not built: any balance or status endpoint (so connecting needs a real test SMS, and delivery is never confirmed:
messages stay "Accepted"), a delivery-report callback, phone-number format rules (8801XXXXXXXXX is used, as in most of the page's
examples), Bangla part counting (counted with the standard 160/70 rules), and the secure-OTP signing (not needed here).
The page serves from ismsplus.sslwireless.com but states smsplus.sslwireless.com as the API host; that is the one used. The server's
IP address must be whitelisted in the SSL Wireless portal or every call fails with 4003.
"""
from __future__ import annotations

import os
import re

from . import common
from .common import ProviderError, call, jbody

ID = "sslwireless"
BASE = "https://smsplus.sslwireless.com/api/v3"
FIELDS = [
    {"key": "api_token", "label": "API token", "secret": True, "help": "ISMS Plus portal, API information."},
    {"key": "sid", "label": "Sender ID (SID)", "secret": False, "help": "The sender ID registered in ISMS Plus."},
]
CONFIG_FIELDS: list[dict] = []
MODES: list[str] = []
HAS_REPORT = False      # no delivery or balance endpoint is documented
HAS_BALANCE = False
MAX_PARTS = 6

CODES = {
    4001: ("auth", "SSL Wireless did not accept the API token."),
    4002: ("auth", "SSL Wireless says this sender ID is not permitted to send."),
    4003: ("auth", "SSL Wireless blocked this server's IP address. Add it to the whitelist in the ISMS Plus portal."),
    4004: ("param", "SSL Wireless could not read the request."),
    4005: ("other", "SSL Wireless does not know that endpoint."),
    4020: ("param", "SSL Wireless rejected the reference id."),
    4022: ("param", "SSL Wireless says a required value is missing."),
    4025: ("param", "SSL Wireless says that is not a valid mobile number."),
    4026: ("rejected", "SSL Wireless has blocked that mobile number."),
    4027: ("param", "SSL Wireless says the message is too long."),
    4028: ("param", "SSL Wireless says the message data is not valid."),
    4029: ("rate", "SSL Wireless says too many requests were sent. Try again shortly."),
    4031: ("rate", "SSL Wireless says the sending speed limit was exceeded. Try again shortly."),
    4032: ("param", "SSL Wireless says the message text is not valid."),
    5000: ("other", "SSL Wireless had an error on their side. Try again later."),
}


def _b() -> str:
    return os.environ.get("SSLWIRELESS_BASE", BASE).rstrip("/")


def msisdn(p: str | None) -> str:
    d = re.sub(r"\D", "", p or "")
    if d.startswith("880"):
        d = d[3:]
    if d.startswith("0"):
        d = d[1:]
    if not re.fullmatch(r"1[3-9]\d{8}", d):
        raise ProviderError("param", "That is not a Bangladesh mobile number (01XXXXXXXXX).")
    return "880" + d


def csms_id(seed: str) -> str:
    """The unique client reference: letters and digits only, at most 20 characters, stable for one message so a retry cannot double-send."""
    return re.sub(r"[^A-Za-z0-9]", "", seed)[:20]


def _code(b: dict) -> int | None:
    try:
        return int(b.get("status_code"))
    except (TypeError, ValueError):
        return None


async def check(c: dict, cfg: dict) -> str:
    # No documented call proves the token without sending a message, so connecting sends a test SMS (see routes/providers.py).
    raise ProviderError("other", "SSL Wireless has no balance or status call, so it can only be checked by sending a test SMS.")


async def _post(c: dict, to: str, text: str, ref: str):
    body = {"api_token": c["api_token"], "sid": c["sid"], "msisdn": msisdn(to), "sms": text, "csms_id": csms_id(ref)}
    return await call(ID, "POST", f"{_b()}/send-sms", json=body, headers={"Content-Type": "application/json", "Accept": "application/json"})


def _interpret(b: dict, retried: bool) -> dict:
    code = _code(b)
    info = (b.get("smsinfo") or [{}])[0] if isinstance(b.get("smsinfo"), list) else {}
    st = str(info.get("sms_status", "")).upper()
    if str(b.get("status", "")).upper() == "SUCCESS" and code == 200 and st == "SUCCESS":
        return {"ref": str(info.get("reference_id") or ""), "status": "Accepted"}
    if retried and (code == 4023 or st == "DUPLICATE"):
        return {"ref": "", "status": "Accepted"}           # our first attempt did arrive
    if code in CODES:
        kind, msg = CODES[code]
        raise ProviderError(kind, msg, str(code))
    if code == 4023 or st == "DUPLICATE":
        raise ProviderError("rejected", "SSL Wireless says this message reference was already used.", "4023")
    if st == "BLOCKED":
        raise ProviderError("rejected", "SSL Wireless has blocked that mobile number.", "blocked")
    if st == "INVALID":
        raise ProviderError("param", "SSL Wireless says that is not a valid mobile number.", "invalid")
    raise ProviderError("other", "SSL Wireless did not answer as expected.", str(code) if code else None)


async def send(c: dict, cfg: dict, *, to: str, text: str, ref: str) -> dict:
    """One message. A network failure is retried once with the same csms_id, which SSL Wireless de-duplicates."""
    try:
        r = await _post(c, to, text, ref)
        retried = False
    except ProviderError as e:
        if e.kind != "network":
            raise
        try:
            r = await _post(c, to, text, ref)
            retried = True
        except ProviderError:
            raise ProviderError("network", "SSL Wireless did not answer; the message may or may not have been sent.", "unclear") from None
    b = jbody(r)
    if not b:
        raise ProviderError("network", "SSL Wireless gave no usable answer; the message may or may not have been sent.", "unclear")
    return _interpret(b, retried)


async def report(c: dict, cfg: dict, ref: str) -> str | None:
    return None
