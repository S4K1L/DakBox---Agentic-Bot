"""Connect, check and disconnect courier and payment providers. Secrets are checked against the provider, stored encrypted,
and never returned (only the last four characters)."""
from __future__ import annotations

import secrets as pysecrets

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import auth, db, metacfg, sms
from ..providers import aamarpay, alphasms, bkash, common, sslcommerz, sslwireless, steadfast
from ..providers.common import ProviderError
from ..secrets_store import mask

router = APIRouter(prefix="/api", dependencies=[Depends(auth.current_user)])
WRITE = Depends(auth.require("connections.write"))

SPECS = {
    "sslcommerz": {"mod": sslcommerz, "kind": "payment", "official": True},
    "bkash": {"mod": bkash, "kind": "payment", "official": True},
    "aamarpay": {"mod": aamarpay, "kind": "payment", "official": True},
    "steadfast": {"mod": steadfast, "kind": "courier", "official": False},
    "alphasms": {"mod": alphasms, "kind": "sms", "official": True},
    "sslwireless": {"mod": sslwireless, "kind": "sms", "official": True},
}
BUILT_IN = {"cod"}  # needs no provider account: the courier collects cash and Dakbox records it on delivery
NOT_BUILT = {
    "pathao": "Not built: Pathao's official API documentation could not be read, and guessing at endpoints that book real parcels is not safe. Ask Pathao for the Merchant API docs and sandbox credentials.",
    "redx": "Not built: RedX's official API documentation could not be read. Ask RedX for the developer API docs and a sandbox token.",
    "paperfly": "Not built: Paperfly publishes no public API reference.",
    "ecourier": "Not built yet.",
    "gp": "Not built: Grameenphone's corporate messaging API documentation is not public. Ask them for it, or use an aggregator that is built.",
    "banglalink": "Not built: the Robi / Banglalink corporate SMS API documentation is not public (Robi's manual says to request it by email).",
    "nagad": "Not built: Nagad's merchant API documentation is not public. Ask Nagad for it.",
}


GUIDES = {
    "sslcommerz": {"where": "SSLCOMMERZ merchant panel (sandbox: developer.sslcommerz.com)", "steps": [
        "Create an SSLCOMMERZ account. For testing, register a sandbox account: it gives you a test Store ID and Store password straight away. For real payments, apply for a live merchant account and wait for approval.",
        "Copy the Store ID and Store password from the panel and paste them here. Start with Sandbox; switch to Live only when you are ready to take real money.",
        "Set your public https address under Connections, Channels, Meta app (it is shared by every provider). Gateways cannot reach localhost.",
        "After connecting, press Setup URLs and paste the IPN listener address into the SSLCOMMERZ panel (IPN Settings). The success, fail and cancel addresses are sent with each payment.",
        "Pay a small test order, then check the order shows Paid. Refunds from Dakbox only work if this server's public IP is registered with SSLCOMMERZ."]},
    "bkash": {"where": "bKash merchant onboarding (tokenized checkout)", "steps": [
        "Ask bKash for tokenized checkout access. They give you a username, password, app key and app secret, plus the base URL to use for sandbox and for production.",
        "Paste the four values here. For Live, also paste the production base URL bKash gave you (Dakbox never guesses it, and only accepts https addresses on bKash's own domain).",
        "Set your public https address under Connections, Channels, Meta app. bKash sends the customer back to it after payment; nothing needs configuring in the bKash portal.",
        "Test in Sandbox first with a sandbox wallet, then reconnect in Live mode."]},
    "aamarpay": {"where": "aamarPay merchant panel", "steps": [
        "Create an aamarPay account (they provide a sandbox for testing) and copy the Store ID and the Signature key.",
        "Paste both here and press Verify and connect. aamarPay has no way to prove the keys without a payment, so the card shows a limited check.",
        "Set your public https address under Connections, Channels, Meta app, then press Setup URLs and give the IPN address to aamarPay support.",
        "aamarPay has no refund API: refunds are recorded by hand in Dakbox and you send the money from their panel."]},
    "steadfast": {"where": "Steadfast merchant dashboard, API settings", "steps": [
        "Log in to your Steadfast merchant dashboard and open the API settings. Copy the API key and the Secret key.",
        "Paste them here. Dakbox checks them by reading your balance, so wrong keys fail immediately.",
        "Enter your usual delivery charge inside and outside Dhaka (this is what Dakbox shows; Steadfast bills you under your agreement).",
        "Optional: press Setup URLs and paste the webhook address into Steadfast with the secret shown as the Bearer token. Tracking also refreshes by itself every 20 minutes.",
        "Steadfast's documentation could not be verified. Book ONE real test parcel and compare it with your dashboard before relying on it."]},
    "sslwireless": {"where": "SSL Wireless ISMS Plus portal", "steps": [
        "In the ISMS Plus portal, get your API token and the sender ID (SID) registered for your account.",
        "Whitelist this server's public IP address in the portal. Without it every send fails with a \"blocked IP\" message.",
        "Paste the token and SID here and enter your own mobile number: SSL Wireless has no balance call, so connecting sends one real test SMS to that number (not saved).",
        "Press Verify and connect. If the test SMS reaches your phone you are done. Messages will show Accepted, never Delivered, because SSL Wireless documents no delivery report.",
        "Then choose which events send SMS under Connections, Notifications."]},
    "alphasms": {"where": "Alpha SMS panel, API page", "steps": [
        "Log in to the Alpha SMS panel, open the API page and copy your API key.",
        "Paste it here. If Alpha SMS approved a sender ID for you, add it; otherwise leave it empty.",
        "Press Verify and connect. Dakbox checks the key by reading your balance, so nothing is sent.",
        "Use Send test SMS on the card to see a real message arrive, then choose which events send SMS under Connections, Notifications."]},
}


def _base(request: Request) -> str:
    return metacfg.public_url() or str(request.base_url).rstrip("/")


def _urls(pid: str, base: str, cfg: dict) -> list[dict]:
    if pid == "sslcommerz":
        return [{"label": "Success URL", "url": f"{base}/pay/sslcommerz/success"}, {"label": "Fail URL", "url": f"{base}/pay/sslcommerz/fail"},
                {"label": "Cancel URL", "url": f"{base}/pay/sslcommerz/cancel"}, {"label": "IPN listener (set in the SSLCOMMERZ panel, IPN Settings)", "url": f"{base}/pay/sslcommerz/ipn"}]
    if pid == "bkash":
        return [{"label": "Callback URL (sent with every payment, nothing to configure)", "url": f"{base}/pay/bkash/callback"}]
    if pid == "aamarpay":
        return [{"label": "Success / fail / cancel URLs (sent with every payment)", "url": f"{base}/pay/aamarpay/success"}, {"label": "IPN listener (give this to aamarPay support)", "url": f"{base}/pay/aamarpay/ipn"}]
    if pid == "steadfast":
        return [{"label": "Webhook URL (paste into Steadfast, with the secret below as the Bearer token)", "url": f"{base}/hooks/steadfast"}]
    return []


def view(r, base: str) -> dict:
    pid = r["id"]
    spec = SPECS.get(pid)
    cfg = db.jl(r["config"], {}) or {}
    out = {"id": pid, "group": r["grp"], "name": r["name"], "letter": r["letter"], "status": r["status"], "note": r["note"], "supported": bool(spec), "live": bool(r["live"]),
           "lastCheckAt": r["last_check_at"], "lastError": r["last_error"], "verifiedName": r["verified_name"], "notBuiltReason": NOT_BUILT.get(pid), "builtIn": pid in BUILT_IN, "guide": GUIDES.get(pid)}
    if spec:
        mod = spec["mod"]
        have = common.creds(pid) if r["live"] else {}
        out.update({"kind": spec["kind"], "officialDocs": spec["official"], "mode": cfg.get("mode"), "modes": list(mod.MODES),
                    "fields": [{**f, "hint": mask(have.get(f["key"])) if f["secret"] and have.get(f["key"]) else (have.get(f["key"]) if have.get(f["key"]) and not f["secret"] else None)} for f in mod.FIELDS],
                    "configFields": [{**f, "value": cfg.get(f["key"], f.get("default"))} for f in getattr(mod, "CONFIG_FIELDS", [])],
                    "extra": getattr(mod, "EXTRA", {}), "hasReport": getattr(mod, "HAS_REPORT", None), "needsTest": spec["kind"] == "sms" and not getattr(mod, "HAS_BALANCE", False), "baseUrl": cfg.get("base_url"), "urls": _urls(pid, base, cfg), "webhookSecret": cfg.get("webhook_secret") if pid == "steadfast" else None})
    return out


@router.get("/providers")
async def providers(request: Request):
    base = _base(request)
    rows = db.all("SELECT * FROM integrations WHERE grp IN ('Couriers','Payments','SMS') ORDER BY rowid")
    return {"items": [view(r, base) for r in rows], "publicUrl": metacfg.public_url(), "baseUsed": base}


class ConnectBody(BaseModel):
    mode: str = "sandbox"
    values: dict[str, str] = Field(default_factory=dict)
    config: dict[str, str] = Field(default_factory=dict)


@router.post("/providers/{pid}/connect", dependencies=[WRITE])
async def connect(pid: str, b: ConnectBody, request: Request):
    spec = SPECS.get(pid)
    if not spec:
        raise HTTPException(400, NOT_BUILT.get(pid, "This provider is not available."))
    mod = spec["mod"]
    if mod.MODES and b.mode not in mod.MODES:
        raise HTTPException(400, "Choose sandbox or live.")
    secrets = {}
    for f in mod.FIELDS:
        v = (b.values.get(f["key"]) or "").strip()
        if not v and f.get("optional"):
            continue
        if not v:
            raise HTTPException(400, f"{f['label']} is required.")
        if len(v) > 300 or "\n" in v:
            raise HTTPException(400, f"{f['label']} does not look right.")
        secrets[f["key"]] = v
    cfg = {"mode": b.mode if mod.MODES else "live"}
    for f in getattr(mod, "CONFIG_FIELDS", []):
        v = (b.config.get(f["key"]) or str(f.get("default", ""))).strip()
        if not v.isdigit():
            raise HTTPException(400, f"{f['label']} must be a whole number.")
        cfg[f["key"]] = v
    if pid == "bkash" and b.mode == "live":
        cfg["base_url"] = (b.config.get("base_url") or "").strip()
    try:
        if pid == "bkash":
            db.set_setting(f"bkash_token_{pid}", None)
            name = await bkash.check(pid, secrets, cfg)
        elif spec["kind"] == "sms" and not getattr(mod, "HAS_BALANCE", False):
            # No balance call exists to prove the credentials, so a real test message is the proof. The number is not stored.
            to = (b.config.get("test_number") or "").strip()
            if not to:
                raise HTTPException(400, "Enter a mobile number to send a test SMS to. It is the only way to check these credentials.")
            await sms_test(pid, secrets, cfg, to)
            name = f"{sms.NAMES[pid]} (sender {secrets.get('sid', '')})"
        else:
            name = await mod.check(secrets, cfg)
    except ProviderError as e:
        raise HTTPException(400, e.message)
    if pid == "steadfast":
        cfg["webhook_secret"] = (common.config(pid) or {}).get("webhook_secret") or pysecrets.token_urlsafe(24)
    common.save(pid, secrets, cfg, name)
    auth.audit("provider.connect", f"{db.get('SELECT name FROM integrations WHERE id=?', [pid])['name']} ({cfg['mode']})")
    return view(common.row(pid), _base(request))


async def sms_test(pid: str, secrets: dict, cfg: dict, to: str) -> None:
    """Send the test message with credentials that are not saved yet."""
    mod = SPECS[pid]["mod"]
    await mod.send(secrets, cfg, to=to, text=f"{sms.agent_settings().get('storeName') or 'Dakbox'}: SMS test. Order updates will be sent from this sender.", ref=db.uid("t"))


@router.post("/providers/{pid}/check", dependencies=[WRITE])
async def check(pid: str, request: Request):
    spec = SPECS.get(pid)
    r = common.row(pid)
    if not spec or not r or not r["live"]:
        raise HTTPException(400, "This provider is not connected.")
    c, cfg = common.creds(pid), common.config(pid)
    if spec["kind"] == "sms" and not getattr(spec["mod"], "HAS_BALANCE", False):
        return {"ok": r["status"] == "ok", "message": "This provider has no balance or status call, so it cannot be re-checked silently. Use Send test SMS.", "provider": view(r, _base(request))}
    try:
        name = await (spec["mod"].check(pid, c, cfg) if pid == "bkash" else spec["mod"].check(c, cfg))
        db.run("UPDATE integrations SET last_check_at=?, last_error=NULL, verified_name=?, status='ok' WHERE id=?", [db.now(), name, pid])
        ok, msg = True, f"Connected as {name}."
    except ProviderError as e:
        db.run("UPDATE integrations SET last_check_at=?, status='warn' WHERE id=?", [db.now(), pid])  # fail closed: nothing uses a provider that is not ok
        common.note_error(pid, e.message)
        ok, msg = False, e.message
    return {"ok": ok, "message": msg, "provider": view(common.row(pid), _base(request))}


@router.delete("/providers/{pid}", dependencies=[WRITE])
async def disconnect(pid: str):
    if pid not in SPECS or not common.row(pid):
        raise HTTPException(400, "This provider is not connected.")
    pending = db.get("SELECT COUNT(*) n FROM payments WHERE provider=? AND status='pending'", [pid])["n"] if SPECS[pid]["kind"] == "payment" else 0
    common.wipe(pid)
    db.set_setting(f"bkash_token_{pid}", None)
    auth.audit("provider.disconnect", pid, f"{pending} link(s) still pending" if pending else None)
    return {"ok": True, "pendingLinks": pending}


# ---------------------------------------------------------------- SMS
class TestSms(BaseModel):
    to: str = Field(min_length=6, max_length=20)


@router.post("/providers/{pid}/test-sms", dependencies=[WRITE])
async def test_sms(pid: str, b: TestSms):
    spec = SPECS.get(pid)
    if not spec or spec["kind"] != "sms" or not common.is_live(pid):
        raise HTTPException(400, "Connect this SMS provider first.")
    try:
        res = await sms.send_test(pid, b.to, auth.staff())
        db.run("UPDATE integrations SET status='ok', last_error=NULL, last_check_at=? WHERE id=?", [db.now(), pid])
    except ProviderError as e:
        common.note_error(pid, e.message)
        raise HTTPException(400, e.message)
    auth.audit("sms.test", pid)
    return {"ok": True, "message": "Test SMS accepted by the provider. Check the phone: acceptance is not delivery.", "status": res["status"]}


@router.get("/sms")
async def sms_overview():
    return {"messages": sms.recent(60), "usage": sms.usage(), "settings": sms.settings(), "provider": sms.live_provider()}


class SmsSettings(BaseModel):
    quiet: bool = True
    quietFrom: int = Field(22, ge=0, le=23)
    quietTo: int = Field(8, ge=0, le=23)
    perNumberDay: int = Field(6, ge=1, le=50)
    perDay: int = Field(500, ge=1, le=20000)


@router.put("/sms/settings", dependencies=[WRITE])
async def sms_settings(b: SmsSettings):
    db.set_setting("sms_settings", b.model_dump())
    auth.audit("sms.settings", "limits and quiet hours")
    return sms.settings()


@router.post("/sms/{mid}/resend", dependencies=[Depends(auth.require("orders.manage"))])
async def sms_resend(mid: str):
    r = await sms.resend(mid, auth.staff())
    if r["status"] in ("error", "not_sent", "held"):
        raise HTTPException(409, r.get("error") or "Not sent.")
    return r
