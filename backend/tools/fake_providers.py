"""Stand-ins for SSLCommerz, bKash, aamarPay, Steadfast, SSL Wireless ISMS Plus and Alpha SMS, for tests and local development. NOT the real services.

They enforce the request shapes in the providers' published documentation (SSLCommerz v4, bKash tokenized checkout v2, aamarPay
readme.io), including bKash's two-grants-per-hour limit and its duplicate-refund rule. Steadfast follows what Dakbox assumes
(its real docs are not public), so those tests prove consistency, not correctness. SSL Wireless and Alpha SMS follow their public API pages,
which leave gaps (no SSL Wireless balance or delivery endpoint; Alpha's delivery statuses beyond "Sent"); the stand-ins do not invent those.
Test credentials: SSLCommerz teststore / testpass@ssl · bKash merchant / pw / appkey / appsecret · aamarPay aamarpaytest / testkey · Steadfast sfkey / sfsecret · SSL Wireless ssl-token-0001 / NORTHWIND · Alpha SMS alpha-key-0001.
"""
from __future__ import annotations

import json
import re
import time
from urllib.parse import parse_qs, urlparse

import httpx

SSL = {"store_id": "teststore", "store_passwd": "testpass@ssl"}
BK = {"username": "merchant", "password": "pw", "app_key": "appkey", "app_secret": "appsecret"}
AAM = {"store_id": "aamarpaytest", "signature_key": "testkey"}
SF = {"Api-Key": "sfkey", "Secret-Key": "sfsecret"}
SSLW = {"api_token": "ssl-token-0001", "sid": "NORTHWIND"}
ALPHA = {"api_key": "alpha-key-0001"}


def _ok(d: dict, s: int = 200):
    return s, d


class FakeProviders:
    def __init__(self, gw_base: str = "https://fakegw.test") -> None:
        self.gw_base = gw_base
        self.calls: list[dict] = []
        # SSLCommerz
        self.ssl_sessions: dict[str, dict] = {}
        self.ssl_txns: dict[str, dict] = {}       # val_id -> txn
        self.ssl_refunds: dict[str, dict] = {}
        self.ssl_risk = "0"
        self.ssl_refund_mode = "success"           # success | processing | fail
        # bKash
        self.bk_tokens: dict[str, float] = {}
        self.bk_grants: list[float] = []
        self.bk_payments: dict[str, dict] = {}
        self.bk_refunds: list[dict] = []
        self.bk_bearer_only = False
        self.bk_refund_timeout = False
        self._n = 0
        # aamarPay
        self.aam_txns: dict[str, dict] = {}
        # Steadfast
        self.sf: dict[str, dict] = {}
        self.sf_invoices: set[str] = set()
        # SMS
        self.sms_net: str | None = None            # "before": the request never arrives; "after": it is processed, then the connection times out (one shot)
        self.sslw_sent: list[dict] = []
        self.sslw_csms: set[str] = set()
        self.sslw_error: int | None = None         # force a documented status_code, e.g. 4003 (IP not whitelisted)
        self.alpha_sent: list[dict] = []
        self.alpha_status: dict[str, str] = {}
        self.alpha_balance = 100.0
        self.alpha_error: int | None = None

    def _id(self, p: str) -> str:
        self._n += 1
        return f"{p}{self._n:06d}"

    # ------------------------------------------------------------ dispatch (by path, so it also works behind a local server)
    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.sms_net == "before" and "send" in request.url.path:
            self.sms_net = None
            raise httpx.ConnectTimeout("stand-in: request never arrived")
        u = urlparse(str(request.url))
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        body: dict = {}
        ct = request.headers.get("content-type", "")
        if request.content:
            if "json" in ct:
                body = json.loads(request.content)
            else:
                body = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        status, data = self.handle(request.method, u.path, q, body, dict(request.headers))
        self.calls.append({"method": request.method, "path": u.path, "query": q, "body": body, "status": status, "headers": {k.lower(): v for k, v in request.headers.items()}})
        if self.sms_net == "after" and "send" in u.path:
            self.sms_net = None
            raise httpx.ReadTimeout("stand-in: processed, then the connection dropped")
        return httpx.Response(status, json=data)

    def handle(self, method: str, path: str, q: dict, body: dict, headers: dict):
        h = {k.lower(): v for k, v in headers.items()}
        if "/gwprocess/" in path or "/validator/" in path:
            return self._ssl(method, path, q, body)
        if "/tokenized-checkout/" in path:
            return self._bkash(method, path, body, h)
        if path.endswith("/jsonpost.php") or "/trxcheck/" in path:
            return self._aam(method, path, q, body)
        if "/api/v3/" in path:
            return self._sslw(method, path, body)
        if path.rstrip("/").endswith("/sendsms") or "/user/balance" in path or "/report/request/" in path:
            return self._alpha(method, path, q, body)
        return self._sf(method, path, body, h)

    # ------------------------------------------------------------ SSLCommerz (official v4 shapes)
    def _ssl_auth(self, d: dict) -> bool:
        return d.get("store_id") == SSL["store_id"] and d.get("store_passwd") == SSL["store_passwd"]

    def _ssl(self, method: str, path: str, q: dict, body: dict):
        if path.endswith("/gwprocess/v4/api.php"):
            need = ["store_id", "store_passwd", "total_amount", "currency", "tran_id", "product_category", "success_url", "fail_url", "cancel_url", "cus_name", "cus_email",
                    "cus_add1", "cus_city", "cus_postcode", "cus_country", "cus_phone", "shipping_method", "num_of_item", "product_name", "product_profile", "emi_option"]
            missing = [k for k in need if body.get(k) in (None, "")]
            if missing:
                return _ok({"status": "FAILED", "failedreason": f"{missing[0]} is mandatory"})
            if not self._ssl_auth(body):
                return _ok({"status": "FAILED", "failedreason": "Store Credential Error Or Store is De-activated"})
            amt = float(body["total_amount"])
            if not (10 <= amt <= 500000) or not re.fullmatch(r"\d+\.\d{2}", body["total_amount"]):
                return _ok({"status": "FAILED", "failedreason": "total_amount must be from 10.00 BDT to 500000.00 BDT"})
            key = self._id("SK")
            self.ssl_sessions[key] = {"tran_id": body["tran_id"], "amount": amt, "urls": {k: body[k] for k in ("success_url", "fail_url", "cancel_url")}, "ipn_url": body.get("ipn_url"), "form": body}
            return _ok({"status": "SUCCESS", "failedreason": "", "sessionkey": key, "GatewayPageURL": f"{self.gw_base}/gw/ssl/{key}", "gw": {}, "desc": []})
        if path.endswith("/validationserverAPI.php"):
            if not self._ssl_auth(q):
                return _ok({"status": "INVALID_TRANSACTION"})
            t = self.ssl_txns.get(q.get("val_id", ""))
            if not t:
                return _ok({"status": "INVALID_TRANSACTION"})
            first = not t.get("validated")
            t["validated"] = True
            return _ok({"status": "VALID" if first else "VALIDATED", "tran_id": t["tran_id"], "val_id": t["val_id"], "amount": f"{t['amount']:.2f}", "currency_type": "BDT",
                        "currency": "BDT", "bank_tran_id": t["bank_tran_id"], "risk_level": t["risk"], "risk_title": "Safe" if t["risk"] == "0" else "Risky"})
        if path.endswith("/merchantTransIDvalidationAPI.php"):
            if not self._ssl_auth(q):
                return _ok({"APIConnect": "FAILED"})
            if "refund_ref_id" in q:
                r = self.ssl_refunds.get(q["refund_ref_id"])
                return _ok({"APIConnect": "DONE", "status": "refunded" if r and r["state"] == "refunded" else "processing", "refund_ref_id": q["refund_ref_id"]})
            if "bank_tran_id" in q:
                need = ["refund_trans_id", "refund_amount", "refund_remarks"]
                if any(not q.get(k) for k in need):
                    return _ok({"APIConnect": "INVALID_REQUEST", "status": "failed", "errorReason": "missing parameters"})
                t = next((x for x in self.ssl_txns.values() if x["bank_tran_id"] == q["bank_tran_id"]), None)
                if not t:
                    return _ok({"APIConnect": "DONE", "status": "failed", "errorReason": "bank_tran_id not found"})
                if any(r["refund_trans_id"] == q["refund_trans_id"] for r in self.ssl_refunds.values()):
                    return _ok({"APIConnect": "DONE", "status": "failed", "errorReason": "duplicate refund_trans_id"})
                done = sum(r["amount"] for r in self.ssl_refunds.values() if r["bank_tran_id"] == t["bank_tran_id"] and r["state"] != "cancelled")
                if float(q["refund_amount"]) + done > t["amount"] + 0.001:
                    return _ok({"APIConnect": "DONE", "status": "failed", "errorReason": "refund amount exceeds the transaction amount"})
                if self.ssl_refund_mode == "fail":
                    return _ok({"APIConnect": "DONE", "status": "failed", "errorReason": "refund declined"})
                ref = self._id("RF")
                self.ssl_refunds[ref] = {"bank_tran_id": t["bank_tran_id"], "amount": float(q["refund_amount"]), "refund_trans_id": q["refund_trans_id"], "state": "refunded" if self.ssl_refund_mode == "success" else "processing"}
                return _ok({"APIConnect": "DONE", "bank_tran_id": t["bank_tran_id"], "status": "success" if self.ssl_refund_mode == "success" else "processing", "refund_ref_id": ref, "errorReason": ""})
            if "tran_id" in q:
                els = [{"status": "VALID", "tran_id": t["tran_id"], "val_id": t["val_id"], "amount": f"{t['amount']:.2f}", "bank_tran_id": t["bank_tran_id"]} for t in self.ssl_txns.values() if t["tran_id"] == q["tran_id"]]
                return _ok({"APIConnect": "DONE", "no_of_trans_found": len(els), "element": els})
        return _ok({"APIConnect": "INVALID_REQUEST"}, 400)

    def ssl_pay(self, tran_id: str, risk: str | None = None, amount: float | None = None) -> dict:
        """The customer pays on the hosted page. Returns the form the gateway would POST to success_url / the IPN."""
        s = next(v for v in self.ssl_sessions.values() if v["tran_id"] == tran_id)
        val = self._id("VAL")
        txn = {"val_id": val, "tran_id": tran_id, "amount": s["amount"] if amount is None else amount, "bank_tran_id": self._id("BNK"), "risk": risk or self.ssl_risk}
        self.ssl_txns[val] = txn
        return {"status": "VALID", "tran_id": tran_id, "val_id": val, "amount": f"{txn['amount']:.2f}", "currency": "BDT", "bank_tran_id": txn["bank_tran_id"], "store_id": SSL["store_id"],
                "risk_level": txn["risk"], "verify_sign": "x", "verify_key": "a,b"}

    # ------------------------------------------------------------ bKash (official v2 shapes)
    def _bk_err(self, code: str, msg: str, status: int = 200):
        return status, {"externalCode": code, "errorMessageEn": msg}

    def _bkash(self, method: str, path: str, body: dict, h: dict):
        tail = path.split("/tokenized-checkout")[-1]
        if tail == "/auth/grant-token":
            if h.get("username") != BK["username"] or h.get("password") != BK["password"] or body.get("app_key") != BK["app_key"] or body.get("app_secret") != BK["app_secret"]:
                return _ok({"statusCode": "9999", "statusMessage": "Invalid or unrecognized access credentials"})
            now = time.time()
            self.bk_grants = [g for g in self.bk_grants if now - g < 3600]
            if len(self.bk_grants) >= 2:
                return _ok({"statusCode": "2079", "statusMessage": "Too many token requests. Blocked for one hour."})
            self.bk_grants.append(now)
            tok = "idtok-" + self._id("T")
            self.bk_tokens[tok] = now + 3600
            return _ok({"statusCode": "0000", "statusMessage": "Successful", "id_token": tok, "token_type": "Bearer", "expires_in": 3600, "refresh_token": "rt-" + tok})
        auth = h.get("authorization", "")
        raw = auth.removeprefix("Bearer ") if auth.startswith("Bearer ") else auth
        if self.bk_bearer_only and not auth.startswith("Bearer "):
            return 401, {"message": "Unauthorized"}
        if h.get("x-app-key", h.get("x-app-key")) != BK["app_key"]:
            return self._bk_err("2001", "Invalid App Key")
        if raw not in self.bk_tokens or self.bk_tokens[raw] < time.time():
            return 401, {"message": "Unauthorized"}
        if tail == "/payment/create":
            need = ["payerReference", "callbackURL", "amount", "currency", "intent", "merchantInvoiceNumber"]
            if any(not body.get(k) for k in need):
                return self._bk_err("2003", "Missing required field")
            if body["currency"] != "BDT":
                return self._bk_err("2007", "Invalid currency.")
            if body["intent"] != "sale":
                return self._bk_err("2005", "Invalid intent")
            pid = "TR" + self._id("0011")
            self.bk_payments[pid] = {"amount": float(body["amount"]), "invoice": body["merchantInvoiceNumber"], "callback": body["callbackURL"], "approved": False, "executed": False, "trx": None, "refunded": 0.0}
            return _ok({"paymentId": pid, "bkashURL": f"{self.gw_base}/gw/bkash/{pid}", "callbackURL": body["callbackURL"], "amount": body["amount"], "intent": "sale", "currency": "BDT",
                        "transactionStatus": "Initiated", "merchantInvoiceNumber": body["merchantInvoiceNumber"], "paymentCreateTime": "now"})
        p = self.bk_payments.get(body.get("paymentId", ""))
        if tail == "/payment/execute":
            if not p:
                return self._bk_err("2002", "Invalid Payment ID")
            if p["executed"]:
                return self._bk_err("2062", "The payment has already been completed")
            if not p["approved"]:
                return self._bk_err("2056", "Customer has not approved the payment")
            p["executed"], p["trx"] = True, self._id("TRX")
            return _ok({"paymentId": body["paymentId"], "trxId": p["trx"], "transactionStatus": "Completed", "amount": f"{p['amount']:.2f}", "currency": "BDT", "intent": "sale",
                        "merchantInvoiceNumber": p["invoice"], "maxRefundableAmount": f"{p['amount']:.2f}"})
        if tail == "/query/payment":
            if not p:
                return self._bk_err("2002", "Invalid Payment ID")
            return _ok({"paymentId": body["paymentId"], "transactionStatus": "Completed" if p["executed"] else "Initiated", "trxId": p["trx"], "amount": f"{p['amount']:.2f}", "currency": "BDT",
                        "merchantInvoice": p["invoice"], "verificationStatus": "Complete" if p["approved"] else "Incomplete"})
        if tail == "/refund/payment/transaction":
            need = ["paymentId", "refundAmount", "sku", "reason", "trxId"]
            if not p or any(not body.get(k) for k in need):
                return self._bk_err("2003", "Missing or invalid field")
            if body["trxId"] != p["trx"]:
                return self._bk_err("3045", "Invalid TrxID")
            amt = float(body["refundAmount"])
            if amt + p["refunded"] > p["amount"] + 0.001:
                return self._bk_err("2072", "Refund amount not valid")
            if any(r["paymentId"] == body["paymentId"] and r["amount"] == amt and time.time() - r["at"] < 600 for r in self.bk_refunds):
                return self._bk_err("2073", "Duplicate refund within 10 minutes")
            if len([r for r in self.bk_refunds if r["paymentId"] == body["paymentId"]]) >= 10:
                return self._bk_err("2074", "Refund limit reached")
            if self.bk_refund_timeout:
                self.bk_refunds.append({"paymentId": body["paymentId"], "amount": amt, "at": time.time(), "trx": self._id("RFD")})  # it DID happen, but we never hear back
                p["refunded"] += amt
                raise httpx.ReadTimeout("slow")
            p["refunded"] += amt
            rt = self._id("RFD")
            self.bk_refunds.append({"paymentId": body["paymentId"], "amount": amt, "at": time.time(), "trx": rt})
            return _ok({"originalTrxId": p["trx"], "refundTrxId": rt, "refundTransactionStatus": "Completed", "originalTrxAmount": f"{p['amount']:.2f}", "refundAmount": f"{amt:.2f}", "currency": "BDT"})
        if tail == "/refund/payment/status":
            if not p or body.get("trxId") != p["trx"]:
                return self._bk_err("3045", "Invalid TrxID")
            return _ok({"originalTrxId": p["trx"], "originalTrxAmount": f"{p['amount']:.2f}",
                        "refundTransactions": [{"refundTrxId": r["trx"], "refundTransactionStatus": "Completed", "refundAmount": f"{r['amount']:.2f}"} for r in self.bk_refunds if r["paymentId"] == body["paymentId"]]})
        return _ok({"statusCode": "9999"}, 404)

    def bk_pay(self, payment_id: str) -> str:
        """The customer approves in the bKash app. Returns the callback URL bKash would redirect the browser to."""
        p = self.bk_payments[payment_id]
        p["approved"] = True
        return f"{p['callback']}?paymentID={payment_id}&status=success&signature=sig"

    # ------------------------------------------------------------ aamarPay (official readme.io shapes)
    def _aam(self, method: str, path: str, q: dict, body: dict):
        if path.endswith("/jsonpost.php"):
            need = ["store_id", "signature_key", "tran_id", "amount", "currency", "desc", "cus_name", "cus_email", "cus_phone", "success_url", "fail_url", "cancel_url", "type"]
            miss = [k for k in need if not body.get(k)]
            if miss or body["type"] != "json":
                return _ok({"result": "false", "error": f"missing {miss[0] if miss else 'type'}"})
            if body["store_id"] != AAM["store_id"] or body["signature_key"] != AAM["signature_key"]:
                return _ok({"result": "false", "error": "Invalid Store ID or Signature"})
            if len(body["tran_id"]) > 32:
                return _ok({"result": "false", "error": "tran_id too long"})
            self.aam_txns[body["tran_id"]] = {"amount": float(body["amount"]), "pay_status": "", "pg": None, "urls": {k: body[k] for k in ("success_url", "fail_url", "cancel_url")}}
            return _ok({"result": "true", "payment_url": f"{self.gw_base}/gw/aamarpay/{body['tran_id']}"})
        if q.get("store_id") != AAM["store_id"] or q.get("signature_key") != AAM["signature_key"]:
            return _ok({"status": "error", "message": "invalid credentials"})
        t = self.aam_txns.get(q.get("request_id", ""))
        if not t:
            return _ok({"pay_status": "", "status_code": "0"})
        return _ok({"pay_status": t["pay_status"], "status_code": "2" if t["pay_status"] == "Successful" else "0", "amount": f"{t['amount']:.2f}", "mer_txnid": q["request_id"], "pg_txnid": t["pg"], "currency": "BDT"})

    def aam_pay(self, tran_id: str, amount: float | None = None) -> dict:
        t = self.aam_txns[tran_id]
        t["pay_status"], t["pg"] = "Successful", self._id("AAM")
        if amount is not None:
            t["amount"] = amount
        return {"pay_status": "Successful", "mer_txnid": tran_id, "pg_txnid": t["pg"], "amount": f"{t['amount']:.2f}", "status_code": "2"}

    # ------------------------------------------------------------ Steadfast (what Dakbox assumes; not verified against their docs)
    def _sf(self, method: str, path: str, body: dict, h: dict):
        if h.get("api-key") != SF["Api-Key"] or h.get("secret-key") != SF["Secret-Key"]:
            return 401, {"status": 401, "message": "Unauthorized"}
        if path.endswith("/get_balance"):
            return _ok({"status": 200, "current_balance": 1250})
        if path.endswith("/create_order"):
            errs = {}
            if not re.fullmatch(r"\d{11}", str(body.get("recipient_phone", ""))):
                errs["recipient_phone"] = ["The recipient phone must be 11 digits."]
            if not (10 <= len(body.get("recipient_address", "")) <= 250):
                errs["recipient_address"] = ["The recipient address must be 10 to 250 characters."]
            if not body.get("invoice"):
                errs["invoice"] = ["The invoice field is required."]
            elif body["invoice"] in self.sf_invoices:
                errs["invoice"] = ["The invoice has already been taken."]
            if not isinstance(body.get("cod_amount"), (int, float)) or body["cod_amount"] < 0:
                errs["cod_amount"] = ["The cod amount must be at least 0."]
            if errs:
                return _ok({"status": 400, "errors": errs}, 400)
            cid = str(1424000 + len(self.sf) + 1)
            self.sf_invoices.add(body["invoice"])
            self.sf[cid] = {"status": "in_review", "body": body}
            return _ok({"status": 200, "message": "Consignment has been created successfully.", "consignment": {
                "consignment_id": int(cid), "invoice": body["invoice"], "tracking_code": "TRK" + cid, "recipient_phone": body["recipient_phone"], "cod_amount": body["cod_amount"], "status": "in_review"}})
        m = re.search(r"/status_by_cid/(\d+)$", path)
        if m:
            c = self.sf.get(m.group(1))
            return _ok({"status": 200, "delivery_status": c["status"]}) if c else _ok({"status": 404, "message": "Not found"}, 404)
        return _ok({"status": 404}, 404)

    def sf_set(self, consignment_id: str, status: str) -> None:
        self.sf[str(consignment_id)]["status"] = status

    # ------------------------------------------------------------ SSL Wireless ISMS Plus (public API page)
    def _sslw(self, method: str, path: str, body: dict):
        def fail(code: int, msg: str, info: list | None = None):
            return _ok({"status": "FAILED", "status_code": code, "error_message": msg, "smsinfo": info or []})
        if not path.endswith("/send-sms"):
            return fail(4005, "End point not found")
        if method != "POST" or not isinstance(body, dict) or not body:
            return fail(4004, "Invalid request format")
        if self.sslw_error:
            return fail(self.sslw_error, "forced error")
        for f in ("api_token", "sid", "msisdn", "sms", "csms_id"):
            if not body.get(f):
                return fail(4022, f"Required parameter missing: {f}")
        if body["api_token"] != SSLW["api_token"]:
            return fail(4001, "Unauthorized")
        if body["sid"] != SSLW["sid"]:
            return fail(4002, "SID not permitted")
        if not re.fullmatch(r"[A-Za-z0-9]{1,20}", str(body["csms_id"])):
            return fail(4020, "Invalid CSMS ID")
        ms = str(body["msisdn"])
        if not re.fullmatch(r"8801[3-9]\d{8}", ms):
            return fail(4025, "Invalid MSISDN", [{"sms_status": "INVALID", "status_message": "Invalid MSISDN", "msisdn": ms, "csms_id": body["csms_id"]}])
        if len(str(body["sms"])) > 1000:
            return fail(4027, "Message length exceeded")
        if body["csms_id"] in self.sslw_csms:
            return fail(4023, "Duplicate CMS ID", [{"sms_status": "DUPLICATE", "status_message": "Duplicated CSMS ID", "msisdn": ms, "csms_id": body["csms_id"]}])
        self.sslw_csms.add(body["csms_id"])
        ref = self._id("SSLW")
        uni = any(ord(ch) > 127 for ch in str(body["sms"]))
        self.sslw_sent.append({"to": ms, "text": body["sms"], "csms_id": body["csms_id"], "ref": ref, "type": "BN" if uni else "EN"})
        return _ok({"status": "SUCCESS", "status_code": 200, "error_message": "", "smsinfo": [{
            "sms_status": "SUCCESS", "status_message": "Success", "msisdn": ms, "sms_type": "BN" if uni else "EN", "csms_id": body["csms_id"], "reference_id": ref, "sms_body": body["sms"]}]})

    # ------------------------------------------------------------ Alpha SMS (public API page)
    def _alpha(self, method: str, path: str, q: dict, body: dict):
        p = {**q, **body}
        if p.get("api_key") != ALPHA["api_key"]:
            return _ok({"error": 405, "msg": "Authorization required"})
        if self.alpha_error:
            return _ok({"error": self.alpha_error, "msg": "forced error"})
        if "/user/balance" in path:
            return _ok({"error": 0, "msg": "Success", "data": {"balance": f"{self.alpha_balance:.4f}"}})
        m = re.search(r"/report/request/(\w+)/?$", path)
        if m:
            rec = next((s for s in self.alpha_sent if s["request_id"] == m.group(1)), None)
            if not rec:
                return _ok({"error": 404, "msg": "Not found"})
            st = self.alpha_status.get(rec["request_id"], "Sent")
            return _ok({"error": 0, "msg": "Success", "data": {"request_id": int(rec["request_id"]), "request_status": "Complete", "request_charge": "0.2500", "recipients": [{"number": rec["to"], "charge": "0.2500", "status": st}]}})
        if not p.get("msg"):
            return _ok({"error": 414, "msg": "Message is empty"})
        to = str(p.get("to", ""))
        if "," in to or not re.fullmatch(r"(8801|01)[3-9]\d{8}", to):
            return _ok({"error": 416, "msg": "No valid number found"})
        if len(str(p["msg"])) > 800:
            return _ok({"error": 415, "msg": "Message is too long"})
        if p.get("sender_id") and p["sender_id"] != "NORTHWIND":
            return _ok({"error": 413, "msg": "Invalid Sender ID"})
        if self.alpha_balance <= 0:
            return _ok({"error": 417, "msg": "Insufficient balance"})
        rid = str(7000 + len(self.alpha_sent) + 1)
        self.alpha_sent.append({"request_id": rid, "to": to if to.startswith("880") else "880" + to[1:], "text": p["msg"], "sender_id": p.get("sender_id")})
        return _ok({"error": 0, "msg": "Request successfully submitted", "data": {"request_id": int(rid)}})

    def alpha_set(self, request_id: str, status: str) -> None:
        self.alpha_status[str(request_id)] = status
