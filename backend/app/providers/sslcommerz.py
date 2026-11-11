"""SSLCommerz (cards, mobile wallets, internet banking). Built to the official v4 documentation.

Flow: create a session (POST) -> customer pays on the hosted page -> we verify with the Order Validation API using val_id
(never from the redirect alone) -> check tran_id, amount and currency against our own record. Refunds use bank_tran_id.
"""
from __future__ import annotations

import secrets as pysecrets

from . import common
from .common import ProviderError, Verified, call, jbody, money, same_amount

ID = "sslcommerz"
SANDBOX, LIVE = "https://sandbox.sslcommerz.com", "https://securepay.sslcommerz.com"
FIELDS = [
    {"key": "store_id", "label": "Store ID", "secret": False, "help": "From your SSLCOMMERZ merchant panel (sandbox and live stores have different IDs)."},
    {"key": "store_passwd", "label": "Store password", "secret": True, "help": "The store password (API credential), not your panel login."},
]
MODES = ["sandbox", "live"]


def _b(mode: str) -> str:
    return common.base(ID, mode, SANDBOX, LIVE)


async def check(c: dict, cfg: dict) -> str:
    """No login endpoint exists, so ask for a transaction that cannot exist: a valid store answers DONE with zero found."""
    r = await call(ID, "GET", f"{_b(cfg['mode'])}/validator/api/merchantTransIDvalidationAPI.php",
                   params={"tran_id": "DBXCHECK-" + pysecrets.token_hex(4), "store_id": c["store_id"], "store_passwd": c["store_passwd"], "format": "json"})
    b = jbody(r)
    st = b.get("APIConnect")
    if st == "DONE":
        return c["store_id"]
    if st == "FAILED":
        raise ProviderError("auth", "SSLCOMMERZ rejected the store ID or password.")
    if st == "INACTIVE":
        raise ProviderError("auth", "This SSLCOMMERZ store is inactive.")
    raise ProviderError("other", "SSLCOMMERZ did not answer as expected. Check the store ID and mode.")


async def create(c: dict, cfg: dict, *, tran_id: str, amount: int, order_number: str, payment_id: str, customer: dict, urls: dict) -> dict:
    data = {
        "store_id": c["store_id"], "store_passwd": c["store_passwd"], "total_amount": money(amount), "currency": "BDT", "tran_id": tran_id,
        "success_url": urls["success"], "fail_url": urls["fail"], "cancel_url": urls["cancel"], "ipn_url": urls["ipn"],
        "cus_name": customer["name"][:50] or "Customer", "cus_email": customer.get("email") or "noreply@dakbox.example", "cus_add1": (customer.get("address") or "Dhaka")[:50],
        "cus_city": customer.get("city") or "Dhaka", "cus_postcode": customer.get("postcode") or "1200", "cus_country": "Bangladesh", "cus_phone": customer.get("phone") or "01700000000",
        "shipping_method": "NO", "num_of_item": 1, "product_name": f"Order {order_number}", "product_category": "General", "product_profile": "general", "emi_option": 0,
        "value_a": order_number, "value_b": payment_id,
    }
    if not (10 <= amount <= 500000):
        raise ProviderError("param", "SSLCOMMERZ accepts amounts from ৳10 to ৳5,00,000.")
    r = await call(ID, "POST", f"{_b(cfg['mode'])}/gwprocess/v4/api.php", data=data)
    b = jbody(r)
    if b.get("status") != "SUCCESS" or not b.get("GatewayPageURL"):
        raise ProviderError("rejected", f"SSLCOMMERZ refused the payment session: {str(b.get('failedreason') or 'no reason given')[:140]}")
    return {"url": b["GatewayPageURL"], "provider_ref": b.get("sessionkey")}


async def _validate(c: dict, cfg: dict, val_id: str) -> dict:
    r = await call(ID, "GET", f"{_b(cfg['mode'])}/validator/api/validationserverAPI.php",
                   params={"val_id": val_id, "store_id": c["store_id"], "store_passwd": c["store_passwd"], "format": "json"})
    return jbody(r)


async def _query(c: dict, cfg: dict, tran_id: str) -> dict:
    r = await call(ID, "GET", f"{_b(cfg['mode'])}/validator/api/merchantTransIDvalidationAPI.php",
                   params={"tran_id": tran_id, "store_id": c["store_id"], "store_passwd": c["store_passwd"], "format": "json"})
    return jbody(r)


def _interpret(b: dict) -> Verified:
    st = b.get("status")
    if st in ("VALID", "VALIDATED"):
        return Verified("paid", float(b["amount"]) if b.get("amount") not in (None, "") else None, b.get("currency_type") or b.get("currency"),
                        b.get("tran_id"), b.get("bank_tran_id"), None, str(b.get("risk_level")) == "1", b)
    if st == "FAILED":
        return Verified("failed", reason=b.get("error") or st, raw=b)
    if st == "INVALID_TRANSACTION":  # an unknown val_id says nothing about the real payment: leave it as it was
        return Verified("pending", reason="The gateway does not know that validation id", raw=b)
    if st in ("CANCELLED", "EXPIRED"):
        return Verified("cancelled", reason=st, raw=b)
    return Verified("pending", raw=b)


async def verify(c: dict, cfg: dict, *, tran_id: str, val_id: str | None = None) -> Verified:
    """Ask SSLCOMMERZ. With a val_id (from the IPN or redirect) use the validation API; otherwise look the payment up by tran_id."""
    if not val_id:
        q = await _query(c, cfg, tran_id)
        if q.get("APIConnect") != "DONE":
            raise ProviderError("auth", "SSLCOMMERZ rejected the store credentials.")
        els = q.get("element") or []
        good = next((e for e in els if e.get("status") in ("VALID", "VALIDATED") and e.get("val_id")), None)
        if not good:
            st = (els[0].get("status") if els else None)
            return Verified("failed" if st == "FAILED" else ("cancelled" if st == "CANCELLED" else "pending"), reason=st, raw=q)
        val_id = good["val_id"]
    b = await _validate(c, cfg, val_id)
    if not b:
        raise ProviderError("network", "SSLCOMMERZ returned nothing readable.")
    return _interpret(b)


async def refund(c: dict, cfg: dict, *, bank_tran_id: str, amount: int, remarks: str, refund_trans_id: str) -> dict:
    r = await call(ID, "GET", f"{_b(cfg['mode'])}/validator/api/merchantTransIDvalidationAPI.php",
                   params={"bank_tran_id": bank_tran_id, "refund_trans_id": refund_trans_id[:30], "store_id": c["store_id"], "store_passwd": c["store_passwd"],
                           "refund_amount": money(amount), "refund_remarks": remarks[:100] or "Refund", "format": "json"})
    b = jbody(r)
    if b.get("APIConnect") not in ("DONE", None) and not b.get("status"):
        raise ProviderError("auth", "SSLCOMMERZ would not accept the refund request (credentials, or your server's IP is not registered with them).")
    st = b.get("status")
    if st == "success":
        return {"status": "done", "ref": b.get("refund_ref_id"), "message": None}
    if st == "processing":
        return {"status": "processing", "ref": b.get("refund_ref_id"), "message": "SSLCOMMERZ is processing the refund."}
    return {"status": "failed", "ref": b.get("refund_ref_id"), "message": str(b.get("errorReason") or "SSLCOMMERZ refused the refund")[:160]}


async def refund_status(c: dict, cfg: dict, ref: str) -> dict:
    r = await call(ID, "GET", f"{_b(cfg['mode'])}/validator/api/merchantTransIDvalidationAPI.php",
                   params={"refund_ref_id": ref, "store_id": c["store_id"], "store_passwd": c["store_passwd"], "format": "json"})
    b = jbody(r)
    st = b.get("status")
    return {"status": {"refunded": "done", "processing": "processing"}.get(st, "failed" if st == "cancelled" else "processing"), "message": b.get("errorReason")}
