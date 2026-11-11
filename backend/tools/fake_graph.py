"""A stand-in for Meta's Graph API, for tests and local development.

It is NOT Meta: it only knows the calls Dakbox makes, and it enforces the request shapes from Meta's published docs
(WhatsApp, Messenger and Instagram messaging), so a payload bug shows up here before it shows up in production.
Token rules: "good*" is valid, "expiring*" is valid but ends in 3 days, "revoked*" fails /debug_token, anything else is
rejected with error 190. A message whose text starts with [[FAIL:<code>]] is rejected with that Graph error code.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

TEMPLATES = [
    {"name": "order_update", "language": "en", "status": "APPROVED", "category": "UTILITY", "parameter_format": "positional",
     "components": [{"type": "BODY", "text": "Hello {{1}}, your order {{2}} is on its way."}]},
    {"name": "return_update", "language": "bn", "status": "APPROVED", "category": "UTILITY", "parameter_format": "named",
     "components": [{"type": "BODY", "text": "আসসালামু আলাইকুম {{name}}, আপনার {{order}} অর্ডারের রিটার্ন রিভিউ চলছে।"}]},
    {"name": "promo_draft", "language": "en", "status": "PENDING", "category": "MARKETING", "parameter_format": "positional",
     "components": [{"type": "BODY", "text": "Big sale {{1}}!"}]},
]


def sign(raw: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def err(code: int, message: str, status: int = 400, subcode: int | None = None, details: str | None = None) -> tuple[int, dict]:
    e: dict[str, Any] = {"message": message, "type": "OAuthException", "code": code, "fbtrace_id": "FAKE"}
    if subcode:
        e["error_subcode"] = subcode
    if details:
        e["error_data"] = {"messaging_product": "whatsapp", "details": details}
    return status, {"error": e}


class FakeGraph:
    def __init__(self) -> None:
        self.accounts: dict[str, dict] = {}   # id -> {"kind": "wa|page|ig", "name": ..., "phone": ...}
        self.outbox: list[dict] = []          # every message request we accepted
        self.calls: list[dict] = []           # every request, accepted or not
        self.templates = list(TEMPLATES)
        self._n = 0

    # -- registry
    def add_wa(self, phone_id: str, name: str = "Northwind Outdoor", phone: str = "+880 1700-000000") -> None:
        self.accounts[phone_id] = {"kind": "wa", "name": name, "phone": phone}

    def add_page(self, page_id: str, name: str = "Northwind Outdoor") -> None:
        self.accounts[page_id] = {"kind": "page", "name": name}

    def add_ig(self, ig_id: str, username: str = "northwind.outdoor") -> None:
        self.accounts[ig_id] = {"kind": "ig", "name": username}

    # -- request handling
    def handler(self, request: httpx.Request) -> httpx.Response:
        u = urlparse(str(request.url))
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        auth = request.headers.get("authorization", "")
        token = auth[7:] if auth.lower().startswith("bearer ") else q.get("access_token")
        body = None
        if request.content:
            try:
                body = json.loads(request.content)
            except ValueError:
                body = None
        status, data = self.handle(request.method, u.netloc, u.path, q, token, "bearer" if auth else "query", body)
        self.calls.append({"method": request.method, "host": u.netloc, "path": u.path, "query": q, "token": token, "token_in": "bearer" if auth else "query", "body": body, "status": status})
        return httpx.Response(status, json=data)

    def _next(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}{self._n:06d}"

    def handle(self, method: str, host: str, path: str, q: dict, token: str | None, token_in: str, body: Any) -> tuple[int, dict]:
        parts = [p for p in path.split("/") if p]
        if not parts or not re.match(r"^v\d+\.\d+$", parts[0]):
            return err(100, "Unsupported request: missing or invalid API version")
        rest = parts[1:]
        if rest == ["debug_token"]:
            tok = q.get("input_token", "")
            if tok.startswith("revoked"):
                return 200, {"data": {"is_valid": False}}
            exp = int(time.time()) + (3 * 86400 if tok.startswith("expiring") else 30 * 86400) if tok.startswith(("good", "expiring")) else 0
            return 200, {"data": {"is_valid": tok.startswith(("good", "expiring")), "expires_at": exp, "scopes": ["pages_messaging"]}}
        if not token or not token.startswith(("good", "expiring", "revoked")):
            return err(190, "Invalid OAuth access token - Cannot parse access token", 401)
        if len(rest) == 1 and method == "GET":
            return self._get_node(rest[0], q, host)
        if len(rest) == 2 and rest[1] == "messages" and method == "POST":
            return self._messages(rest[0], host, token_in, body)
        if len(rest) == 2 and rest[1] == "subscribed_apps" and method == "POST":
            return 200, {"success": True}
        if len(rest) == 2 and rest[1] == "message_templates" and method == "GET":
            return 200, {"data": self.templates, "paging": {}}
        return err(100, f"Unsupported {method} request: {path}", 400)

    def _get_node(self, node: str, q: dict, host: str) -> tuple[int, dict]:
        if node == "me":  # Instagram Login: who does this token belong to
            ig = next(((i, a) for i, a in self.accounts.items() if a["kind"] == "ig"), None)
            if not ig:
                return err(100, "No Instagram account")
            return 200, {"user_id": ig[0], "id": ig[0], "username": ig[1]["name"]}
        a = self.accounts.get(node)
        if not a:
            if re.fullmatch(r"\d{5,}", node) and q.get("fields") == "name":  # a PSID asking for a profile name
                return 200, {"name": f"Customer {node[-4:]}", "id": node}
            return err(100, f"Unsupported get request. Object with ID '{node}' does not exist, cannot be loaded due to missing permissions, or does not support this operation.")
        if a["kind"] == "wa":
            return 200, {"id": node, "verified_name": a["name"], "display_phone_number": a["phone"]}
        return 200, {"id": node, "name": a["name"]}

    def _messages(self, node: str, host: str, token_in: str, b: Any) -> tuple[int, dict]:
        if not isinstance(b, dict):
            return err(100, "Missing body")
        text = ""
        if b.get("messaging_product") == "whatsapp":
            if node not in self.accounts or self.accounts[node]["kind"] != "wa":
                return err(100, "Unsupported post request: phone number does not exist")
            if b.get("status") == "read":
                return 200, {"success": True}
            if not (b.get("to") or b.get("recipient")):
                return err(131008, "Required parameter is missing", details="to")
            t = b.get("type")
            if t == "text":
                text = (b.get("text") or {}).get("body", "")
                if not text or len(text) > 4096:
                    return err(131009, "Parameter value is not valid", details="text.body must be 1 to 4096 characters")
            elif t == "template":
                tpl = b.get("template") or {}
                known = next((x for x in self.templates if x["name"] == tpl.get("name") and x["language"] == (tpl.get("language") or {}).get("code") and x["status"] == "APPROVED"), None)
                if not known:
                    return err(132001, "Template name does not exist in the translation", details="template not found or not approved")
                need = len(set(re.findall(r"\{\{\s*(\w+)\s*\}\}", known["components"][0]["text"])))
                got = sum(len(c.get("parameters", [])) for c in tpl.get("components", []) if c.get("type") == "body")
                if need != got:
                    return err(132000, "Number of parameters does not match the expected number of params", details=f"expected {need}, got {got}")
                text = f"[template {tpl['name']}]"
            else:
                return err(131051, "Unsupported message type")
            m = re.match(r"^\[\[FAIL:(\d+)\]\]", text)
            if m:
                return self._injected(int(m.group(1)))
            mid = "wamid." + self._next("FAKE")
            self.outbox.append({"channel": "wa", "node": node, "to": b.get("to") or b.get("recipient"), "text": text, "id": mid, "body": b})
            return 200, {"messaging_product": "whatsapp", "contacts": [{"input": b.get("to"), "wa_id": str(b.get("to", "")).lstrip("+")}], "messages": [{"id": mid}]}
        # Messenger / Instagram
        rec = (b.get("recipient") or {}).get("id")
        if not rec:
            return err(100, "Param recipient[id] must be non-empty")
        if b.get("sender_action"):
            return 200, {"recipient_id": rec}
        text = (b.get("message") or {}).get("text", "")
        ig = "instagram" in host or self.accounts.get(node, {}).get("kind") == "ig"
        if not text:
            return err(100, "Param message must be non-empty")
        if ig and len(text.encode()) > 1000:
            return err(100, "Message text must be 1000 bytes or less")
        if not ig and len(text) > 2000:
            return err(100, "Message too long")
        if not ig and b.get("messaging_type") not in ("RESPONSE", "UPDATE", "MESSAGE_TAG"):
            return err(100, "Param messaging_type is required")
        m = re.match(r"^\[\[FAIL:(\d+)(?::(\d+))?\]\]", text)
        if m:
            return self._injected(int(m.group(1)), int(m.group(2)) if m.group(2) else None)
        mid = "m_" + self._next("FAKE")
        self.outbox.append({"channel": "ig" if ig else "ms", "node": node, "to": rec, "text": text, "id": mid, "body": b, "host": host, "token_in": token_in})
        return 200, {"recipient_id": rec, "message_id": mid}

    def _injected(self, code: int, sub: int | None = None) -> tuple[int, dict]:
        msgs = {190: "Error validating access token", 131047: "Re-engagement message", 10: "This message is sent outside of allowed window.", 131026: "Message undeliverable", 4: "Application request limit reached"}
        return err(code, msgs.get(code, "Injected failure"), subcode=sub, details="injected")


# ---------------------------------------------------------------- webhook payload builders (shapes from Meta's docs)
def wa_text(phone_id: str, sender: str, text: str, wamid: str = "wamid.IN1", name: str | None = "Sheena Nelson", ts: int = 1749416383) -> dict:
    return {"object": "whatsapp_business_account", "entry": [{"id": "102290129340398", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp", "metadata": {"display_phone_number": "15550783881", "phone_number_id": phone_id},
        "contacts": [{"profile": {"name": name}, "wa_id": sender}] if name else [],
        "messages": [{"from": sender, "id": wamid, "timestamp": str(ts), "type": "text", "text": {"body": text}}]}}]}]}


def wa_media(phone_id: str, sender: str, kind: str = "image", caption: str = "", wamid: str = "wamid.IN2") -> dict:
    blob = {"id": "MEDIA1", "mime_type": "image/jpeg", "sha256": "x", **({"caption": caption} if caption else {})}
    p = wa_text(phone_id, sender, "")
    p["entry"][0]["changes"][0]["value"]["messages"] = [{"from": sender, "id": wamid, "timestamp": "1749416383", "type": kind, kind: blob}]
    return p


def wa_reaction(phone_id: str, sender: str, wamid: str = "wamid.IN3") -> dict:
    p = wa_text(phone_id, sender, "")
    p["entry"][0]["changes"][0]["value"]["messages"] = [{"from": sender, "id": wamid, "timestamp": "1", "type": "reaction", "reaction": {"message_id": "wamid.X", "emoji": "👍"}}]
    return p


def wa_status(phone_id: str, wamid: str, status: str, recipient: str = "8801712340042", error: dict | None = None) -> dict:
    st = {"id": wamid, "status": status, "timestamp": "1751142888", "recipient_id": recipient}
    if error:
        st["errors"] = [error]
    return {"object": "whatsapp_business_account", "entry": [{"id": "1", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp", "metadata": {"display_phone_number": "15550783881", "phone_number_id": phone_id}, "statuses": [st]}}]}]}


def page_text(page_id: str, psid: str, text: str, mid: str = "mid.IN1", obj: str = "page", ts: int = 1458692752478, echo: bool = False) -> dict:
    ev = {"sender": {"id": psid}, "recipient": {"id": page_id}, "timestamp": ts, "message": {"mid": mid, "text": text}}
    if echo:
        ev = {"sender": {"id": page_id}, "recipient": {"id": psid}, "timestamp": ts, "message": {"mid": mid, "text": text, "is_echo": True}}
    return {"object": obj, "entry": [{"id": page_id, "time": ts, "messaging": [ev]}]}


def page_attachment(page_id: str, psid: str, kind: str = "image", mid: str = "mid.IN9", obj: str = "page") -> dict:
    return {"object": obj, "entry": [{"id": page_id, "time": 1, "messaging": [{"sender": {"id": psid}, "recipient": {"id": page_id}, "timestamp": 1,
            "message": {"mid": mid, "attachments": [{"type": kind, "payload": {"url": "https://example.test/x.jpg"}}]}}]}]}


def page_delivery(page_id: str, psid: str, watermark: int, mids: list[str] | None = None) -> dict:
    d: dict[str, Any] = {"watermark": watermark}
    if mids:
        d["mids"] = mids
    return {"object": "page", "entry": [{"id": page_id, "time": 1, "messaging": [{"sender": {"id": psid}, "recipient": {"id": page_id}, "delivery": d}]}]}


def page_read(page_id: str, psid: str, watermark: int) -> dict:
    return {"object": "page", "entry": [{"id": page_id, "time": 1, "messaging": [{"sender": {"id": psid}, "recipient": {"id": page_id}, "timestamp": watermark, "read": {"watermark": watermark}}]}]}
