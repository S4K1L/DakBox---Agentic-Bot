"""Shared plumbing for courier and payment providers.

Rules every provider follows:
- Secrets are stored encrypted on the integrations row and never returned, logged, or put in an error message.
- Requests only go to the provider's own domains (checked), so a typo'd or malicious "base URL" cannot receive credentials.
- Errors are turned into ProviderError with a message that is safe to show staff.
"""
from __future__ import annotations

import os
import re
import secrets as pysecrets
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from .. import db
from ..secrets_store import seal, unseal

_transport: httpx.AsyncBaseTransport | None = None


def set_transport(t: httpx.AsyncBaseTransport | None) -> None:
    """Tests inject a stand-in for every provider here."""
    global _transport
    _transport = t


@dataclass
class ProviderError(Exception):
    kind: str          # auth | param | network | rejected | rate | other
    message: str
    code: str | None = None

    def __str__(self) -> str:
        return self.message


ALLOWED_DOMAINS = {
    "sslcommerz": ("sslcommerz.com",),
    "bkash": ("bka.sh",),
    "aamarpay": ("aamarpay.com",),
    "steadfast": ("packzy.com", "steadfast.com.bd"),
    "sslwireless": ("sslwireless.com",),
    "alphasms": ("sms.net.bd",),
}


def check_host(provider: str, url: str) -> None:
    host = (urlparse(url).hostname or "").lower()
    if os.environ.get(f"{provider.upper()}_BASE"):  # local stand-in, set by whoever runs the server
        return
    if not any(host == d or host.endswith("." + d) for d in ALLOWED_DOMAINS[provider]):
        raise ProviderError("param", "That address does not belong to this provider.")


async def call(provider: str, method: str, url: str, *, headers: dict | None = None, params: dict | None = None,
               json: dict | None = None, data: dict | None = None, timeout: float = 25.0) -> httpx.Response:
    check_host(provider, url)
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=_transport, follow_redirects=False) as c:
            return await c.request(method, url, headers=headers, params=params, json=json, data=data)
    except httpx.TimeoutException:
        raise ProviderError("network", "The provider did not answer in time.", "timeout") from None
    except httpx.HTTPError:
        raise ProviderError("network", "Could not reach the provider.", "unreachable") from None  # no URL: it may carry secrets


def jbody(r: httpx.Response) -> dict:
    try:
        d = r.json()
    except ValueError:
        return {}
    return d if isinstance(d, dict) else {}


@dataclass
class Verified:
    """What a gateway told us, server to server, about one payment. Nothing here comes from the customer's browser."""
    status: str                    # paid | pending | failed | cancelled
    amount: float | None = None
    currency: str | None = None
    tran_id: str | None = None     # our transaction id, as echoed by the gateway
    trx_id: str | None = None      # the gateway's / bank's transaction id (needed for refunds)
    reason: str | None = None
    risk: bool = False             # gateway flagged it: hold for a person to look at
    raw: dict | None = None


def money(n: float | int) -> str:
    return f"{float(n):.2f}"


def same_amount(a: object, b: float | int) -> bool:
    try:
        return abs(float(a) - float(b)) < 0.005
    except (TypeError, ValueError):
        return False


def new_tran_id(order_number: str) -> str:
    digits = re.sub(r"\D", "", order_number) or "0"
    return f"DBX{digits}-{pysecrets.token_hex(4)}"   # unique per attempt, 20 characters or fewer for most orders


# ---------------------------------------------------------------- stored credentials
def row(pid: str):
    return db.get("SELECT * FROM integrations WHERE id=?", [pid])


def creds(pid: str) -> dict:
    r = row(pid)
    return (db.jl(unseal(r["credentials"]), {}) if r and r["credentials"] else {}) or {}


def config(pid: str) -> dict:
    r = row(pid)
    return (db.jl(r["config"], {}) if r else {}) or {}


def is_live(pid: str) -> bool:
    r = row(pid)
    return bool(r and r["live"] and r["credentials"] and r["status"] == "ok")


def save(pid: str, secrets: dict, cfg: dict, name: str | None) -> None:
    db.run("UPDATE integrations SET credentials=?, config=?, live=1, status='ok', note=?, last_error=NULL, last_check_at=?, verified_name=? WHERE id=?",
           [seal(db.dumps(secrets)), db.dumps(cfg), f"Connected ({cfg.get('mode', 'live')}).", db.now(), name, pid])


def wipe(pid: str) -> None:
    db.run("UPDATE integrations SET credentials=NULL, config=NULL, live=0, status='off', note='Not connected.', last_error=NULL, verified_name=NULL WHERE id=?", [pid])


def note_error(pid: str, message: str | None) -> None:
    db.run("UPDATE integrations SET last_error=? WHERE id=?", [f"{message} ({db.now()[:16].replace('T', ' ')} UTC)" if message else None, pid])


def base(provider: str, mode: str, sandbox: str, live: str) -> str:
    env = os.environ.get(f"{provider.upper()}_BASE")
    if env:
        return env.rstrip("/")
    return (sandbox if mode == "sandbox" else live).rstrip("/")
