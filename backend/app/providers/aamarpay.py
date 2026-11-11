"""aamarPay. Built to the official aamarpay.readme.io pages.

Initiate (JSON) -> customer pays -> aamarPay POSTs to success/fail/cancel and (once set up with them) an IPN -> we confirm with
the Search Transaction API by our own tran_id. aamarPay publishes NO refund API: refunds are done in their merchant panel and recorded here.
"""
from __future__ import annotations

import secrets as pysecrets

from . import common
from .common import ProviderError, Verified, call, jbody, money, same_amount

ID = "aamarpay"
SANDBOX, LIVE = "https://sandbox.aamarpay.com", "https://secure.aamarpay.com"
FIELDS = [
    {"key": "store_id", "label": "Store ID", "secret": False, "help": "Sandbox: aamarpaytest. Live credentials come from aamarPay support."},
    {"key": "signature_key", "label": "Signature key", "secret": True, "help": "The signature key for the store."},
]
MODES = ["sandbox", "live"]


def _b(mode: str) -> str:
    return common.base(ID, mode, SANDBOX, LIVE)


async def _trx(c: dict, cfg: dict, tran_id: str) -> dict:
    r = await call(ID, "GET", f"{_b(cfg['mode'])}/api/v1/trxcheck/request.php",
                   params={"request_id": tran_id, "store_id": c["store_id"], "signature_key": c["signature_key"], "type": "json"})
    return jbody(r)


async def check(c: dict, cfg: dict) -> str:
    """Limited: aamarPay has no credential-check call. A reply that reads as JSON proves the address; wrong credentials surface on the first payment."""
    b = await _trx(c, cfg, "DBXCHECK-" + pysecrets.token_hex(4))
    if not b:
        raise ProviderError("other", "aamarPay did not answer with readable data. Check the mode.")
    return c["store_id"]


async def create(c: dict, cfg: dict, *, tran_id: str, amount: int, order_number: str, payment_id: str, customer: dict, urls: dict) -> dict:
    body = {
        "store_id": c["store_id"], "signature_key": c["signature_key"], "tran_id": tran_id[:32], "amount": money(amount), "currency": "BDT", "desc": f"Order {order_number}",
        "cus_name": customer["name"][:50] or "Customer", "cus_email": customer.get("email") or "noreply@dakbox.example", "cus_phone": customer.get("phone") or "01700000000",
        "cus_add1": (customer.get("address") or "Dhaka")[:50], "cus_city": customer.get("city") or "Dhaka", "cus_country": "Bangladesh",
        "success_url": urls["success"], "fail_url": urls["fail"], "cancel_url": urls["cancel"], "type": "json", "opt_a": order_number, "opt_b": payment_id,
    }
    r = await call(ID, "POST", f"{_b(cfg['mode'])}/jsonpost.php", json=body)
    b = jbody(r)
    if str(b.get("result")).lower() != "true" or not b.get("payment_url"):
        detail = b.get("result") or b.get("error") or b.get("message") or "no reason given"
        raise ProviderError("rejected", f"aamarPay refused the payment: {str(detail)[:140]}")
    return {"url": b["payment_url"], "provider_ref": None}


async def verify(c: dict, cfg: dict, *, tran_id: str) -> Verified:
    b = await _trx(c, cfg, tran_id)
    if not b:
        raise ProviderError("network", "aamarPay returned nothing readable.")
    st = str(b.get("pay_status") or "")
    if st == "Successful":
        amt = b.get("amount")
        cur = b.get("currency_merchant") or b.get("currency") or "BDT"
        return Verified("paid", float(amt) if amt not in (None, "") else None, cur, b.get("mer_txnid") or tran_id, b.get("pg_txnid"), None, False, b)
    if st in ("Failed", "Expired"):
        return Verified("failed", reason=st, raw=b)
    return Verified("pending", reason=st or None, raw=b)
