"""bKash Tokenized Checkout (v2). Built to the official developer.bka.sh pages.

Flow: grant token (max 2 per hour, so tokens are cached) -> create payment -> customer approves in bKash -> bKash redirects to our
callback with status=success -> we EXECUTE once, then confirm with QUERY. Money is only counted when Query says Completed
and the amount and invoice match ours. A paymentId can be executed only once and is valid 24 hours.
"""
from __future__ import annotations

import time
from urllib.parse import urlparse

from .. import db
from ..secrets_store import seal, unseal
from . import common
from .common import ProviderError, Verified, call, jbody, money, same_amount

ID = "bkash"
SANDBOX = "https://tokenized.sandbox.bka.sh/v2/tokenized-checkout"
FIELDS = [
    {"key": "username", "label": "Merchant username", "secret": False, "help": "Provided by bKash."},
    {"key": "password", "label": "Merchant password", "secret": True, "help": "Provided by bKash."},
    {"key": "app_key", "label": "App key", "secret": False, "help": "Provided by bKash."},
    {"key": "app_secret", "label": "App secret", "secret": True, "help": "Provided by bKash."},
]
EXTRA = {"base_url": {"label": "Production base URL (live mode only)", "help": "bKash's pages do not publish the production address; they give it to you at onboarding. It must be an https://….bka.sh address."}}
MODES = ["sandbox", "live"]
_ALREADY_DONE = {"2062", "2117", "2068"}


def _b(cfg: dict) -> str:
    import os
    if os.environ.get("BKASH_BASE"):
        return os.environ["BKASH_BASE"].rstrip("/")
    if cfg.get("mode") == "sandbox":
        return SANDBOX
    u = (cfg.get("base_url") or "").rstrip("/")
    p = urlparse(u)
    if p.scheme != "https" or not (p.hostname or "").endswith(".bka.sh"):
        raise ProviderError("param", "Live mode needs the production base URL from bKash (https://….bka.sh).")
    return u


def _err(b: dict, r_status: int) -> ProviderError | None:
    code = b.get("externalCode") or b.get("statusCode")
    msg = b.get("errorMessageEn") or b.get("statusMessage")
    if code and str(code) != "0000" and (b.get("externalCode") or "paymentId" not in b and "id_token" not in b):
        return ProviderError("rejected", f"bKash said: {str(msg)[:140] or 'error'} ({code})", str(code))
    if r_status >= 400:
        return ProviderError("rejected", f"bKash returned HTTP {r_status}.", str(r_status))
    return None


# ---------------------------------------------------------------- tokens (two grants per hour at most)
def _cached(pid: str) -> str | None:
    d = db.jl(unseal(db.get_setting(f"bkash_token_{pid}", None)), None)
    return d["id_token"] if d and d["exp"] - 120 > time.time() else None


async def token(pid: str, c: dict, cfg: dict, force: bool = False) -> str:
    if not force and (t := _cached(pid)):
        return t
    grants = [g for g in (db.get_setting(f"bkash_grants_{pid}", []) or []) if time.time() - g < 3600]
    if len(grants) >= 2:
        raise ProviderError("rate", "bKash allows only two token requests per hour and both were used. Try again later.", "rate")
    r = await call(ID, "POST", f"{_b(cfg)}/auth/grant-token", headers={"username": c["username"], "password": c["password"], "Content-Type": "application/json"},
                   json={"app_key": c["app_key"], "app_secret": c["app_secret"]}, timeout=30)
    grants.append(time.time())
    db.set_setting(f"bkash_grants_{pid}", grants)
    b = jbody(r)
    if not b.get("id_token"):
        raise ProviderError("auth", f"bKash rejected the credentials: {str(b.get('statusMessage') or b.get('errorMessageEn') or 'invalid')[:100]}", str(b.get("statusCode") or ""))
    db.set_setting(f"bkash_token_{pid}", seal(db.dumps({"id_token": b["id_token"], "exp": time.time() + int(b.get("expires_in") or 3600)})))
    return b["id_token"]


async def _post(pid: str, c: dict, cfg: dict, path: str, body: dict) -> dict:
    tok = await token(pid, c, cfg)
    for style in ("raw", "bearer"):  # the docs' samples send the bare id_token; the table says Bearer. Try the sample form first.
        headers = {"Content-Type": "application/json", "X-App-Key": c["app_key"], "Authorization": tok if style == "raw" else f"Bearer {tok}"}
        r = await call(ID, "POST", f"{_b(cfg)}{path}", headers=headers, json=body, timeout=35)
        b = jbody(r)
        if r.status_code == 401 and style == "raw":
            continue
        e = _err(b, r.status_code)
        if e:
            raise e
        return b
    raise ProviderError("auth", "bKash did not accept the token.")


async def check(pid: str, c: dict, cfg: dict) -> str:
    await token(pid, c, cfg, force=False)
    return c["username"]


async def create(pid: str, c: dict, cfg: dict, *, tran_id: str, amount: int, order_number: str, payment_id: str, customer: dict, urls: dict) -> dict:
    b = await _post(pid, c, cfg, "/payment/create", {
        "payerReference": (customer.get("phone") or order_number)[:60].replace("<", "").replace(">", "").replace("&", ""),
        "callbackURL": urls["callback"], "amount": money(amount), "currency": "BDT", "intent": "sale", "merchantInvoiceNumber": tran_id})
    if not b.get("paymentId") or not (b.get("bkashURL") or b.get("bKashURL")):
        raise ProviderError("rejected", "bKash did not return a payment link.")
    return {"url": b.get("bkashURL") or b.get("bKashURL"), "provider_ref": b["paymentId"]}


async def execute(pid: str, c: dict, cfg: dict, payment_id: str) -> dict:
    try:
        return await _post(pid, c, cfg, "/payment/execute", {"paymentId": payment_id})
    except ProviderError as e:
        if e.code in _ALREADY_DONE:
            return {}  # someone (a retry, the customer) already completed it: the Query below is the source of truth
        raise


async def verify(pid: str, c: dict, cfg: dict, payment_id: str) -> Verified:
    b = await _post(pid, c, cfg, "/query/payment", {"paymentId": payment_id})
    st = b.get("transactionStatus")
    if st == "Completed":
        return Verified("paid", float(b["amount"]) if b.get("amount") not in (None, "") else None, b.get("currency"), b.get("merchantInvoice") or b.get("merchantInvoiceNumber"),
                        b.get("trxId"), None, False, b)
    return Verified("pending", reason=st, raw=b)


async def refund(pid: str, c: dict, cfg: dict, *, payment_id: str, trx_id: str, amount: int, reason: str, sku: str) -> dict:
    try:
        b = await _post(pid, c, cfg, "/refund/payment/transaction", {"paymentId": payment_id, "refundAmount": money(amount), "sku": sku[:255], "reason": reason[:255] or "Refund", "trxId": trx_id})
    except ProviderError as e:
        if e.kind == "network":
            return {"status": "unknown", "ref": None, "message": "bKash did not answer. Check the refund status before trying again."}
        return {"status": "failed", "ref": None, "message": e.message}
    if b.get("refundTransactionStatus") == "Completed":
        return {"status": "done", "ref": b.get("refundTrxId"), "message": None}
    return {"status": "processing", "ref": b.get("refundTrxId"), "message": f"bKash status: {b.get('refundTransactionStatus')}"}


async def refund_status(pid: str, c: dict, cfg: dict, payment_id: str, trx_id: str, amount: int) -> dict:
    b = await _post(pid, c, cfg, "/refund/payment/status", {"paymentId": payment_id, "trxId": trx_id})
    for t in b.get("refundTransactions") or []:
        if same_amount(t.get("refundAmount"), amount) and t.get("refundTransactionStatus") == "Completed":
            return {"status": "done", "ref": t.get("refundTrxId")}
    return {"status": "none"}
