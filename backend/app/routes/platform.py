"""The platform administrator's own endpoints: see and create businesses. (The full admin screens and onboarding come in phase 5.)
These never select a business and never read any business's data: they work on the registry only."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

import time
from pathlib import Path

from .. import aikey, auth, backups, db, export, jobs, limits, registry
from ..agent.agent import has_model
from ..secrets_store import seal_master, unseal_master

router = APIRouter(prefix="/api/platform", dependencies=[Depends(auth.platform_admin)])
downloads = APIRouter(prefix="/api/platform")          # the one-time file download, which carries its own short-lived token


def _view(b) -> dict:
    members = registry.members_of(b["id"])
    p = registry.plan_of(b["id"])
    return {"id": b["id"], "slug": b["slug"], "name": b["name"], "status": b["status"], "plan": b["plan"], "createdAt": b["created_at"],
            "members": len([m for m in members if m["member_active"]]), "owners": [m["name"] for m in members if m["role"] == "owner" and m["member_active"]][:3],
            "limits": {"seats": p["seats"], "products": p["products"], "aiReplies": p["ai_replies"], "platformAi": p["platform_ai"], "overridden": p["overridden"]}}


class OwnerBody(BaseModel):
    name: str = Field(default="", max_length=80)
    email: str = Field(min_length=3, max_length=120)
    password: str = Field(default="", max_length=200)       # a temporary one for a new person; ignored when the email already has an account


class NewBusiness(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    slug: str | None = Field(default=None, max_length=40)
    plan: str | None = Field(default=None, max_length=24)
    owner: OwnerBody | None = None                          # the business owner. Without one, the super administrator becomes the owner (command line and tests)


class LimitsBody(BaseModel):
    seats: int | None = Field(default=None, ge=0, le=10_000_000)
    products: int | None = Field(default=None, ge=0, le=10_000_000)
    aiReplies: int | None = Field(default=None, ge=0, le=10_000_000)
    platformAi: bool | None = None


class PatchBusiness(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    status: str | None = Field(default=None, max_length=12)
    plan: str | None = Field(default=None, max_length=24)
    limits: LimitsBody | None = None                      # per-business overrides of the plan; send an empty object to clear them


@router.get("/businesses")
async def businesses():
    return {"items": [_view(b) for b in registry.all_businesses()]}


@router.post("/businesses")
async def create_business(b: NewBusiness, user: dict = Depends(auth.platform_admin)):
    """A new, blank business with its own owner. The owner is a person (new, with a temporary password they must change at first sign-in, or an existing account);
    the super administrator is NOT made a member. Without an owner in the request the creator becomes the owner (the old behaviour, for the command line and tests)."""
    owner_acct, owner_new = None, False
    if b.owner:
        email = b.owner.email.strip().lower()
        if "@" not in email or " " in email:
            raise HTTPException(400, "Enter a valid email address for the owner.")
        owner_acct = registry.account_by_email(email)
        if not owner_acct:
            if len(b.owner.name.strip()) < 2:
                raise HTTPException(400, "Enter the owner's name.")
            auth.check_password_rules(b.owner.password, email)
    try:
        if b.plan and not registry.plan_row(b.plan):
            raise registry.RegistryError("There is no such plan.")
        biz = registry.create(b.name, b.slug)
        if b.plan:
            biz = registry.set_plan(biz["id"], b.plan)
    except registry.RegistryError as e:
        raise HTTPException(400, str(e)) from None
    if b.owner:
        if not owner_acct:
            owner_acct = registry.create_account(b.owner.name, email, await auth.hash_password(b.owner.password), must_change=True)
            owner_new = True
        registry.add_membership(owner_acct["id"], biz["id"], "owner")
    else:
        registry.add_membership(user["id"], biz["id"], "owner")
    with db.business(biz["id"]):
        auth.audit("business.create", biz["slug"], f"owner {owner_acct['email']}" if owner_acct else None, actor=user)
    registry.log_platform(user, "business.create", biz["slug"], f"plan {biz['plan']}" + (f", owner {owner_acct['email']}" if owner_acct else ""))
    return {"business": _view(biz), "owner": {"id": owner_acct["id"], "name": owner_acct["name"], "email": owner_acct["email"], "created": owner_new} if owner_acct else None}


@router.patch("/businesses/{ref}")
async def patch_business(ref: str, b: PatchBusiness, user: dict = Depends(auth.platform_admin)):
    try:
        biz = registry.resolve(ref)
        if b.name:
            biz = registry.rename(ref, b.name)
            registry.log_platform(user, "business.rename", biz["slug"], b.name)
        if b.plan is not None or b.limits is not None:
            lim = None
            if b.limits is not None:
                lim = {"seats": b.limits.seats, "products": b.limits.products, "ai_replies": b.limits.aiReplies, "platform_ai": b.limits.platformAi}
            biz = registry.set_plan(ref, b.plan, lim)
            registry.log_platform(user, "business.plan", biz["slug"], f"{biz['plan']}" + (f", overrides {lim}" if lim else ""))
        if b.status:
            if biz["id"] == registry.default_id() and b.status == "suspended":
                raise registry.RegistryError("The default business cannot be suspended.")
            biz = registry.set_status(ref, b.status)
            registry.log_platform(user, f"business.{b.status}", biz["slug"])
            if b.status == "suspended":
                for m in registry.members_of(biz["id"]):                   # people working in it are moved out at once
                    registry.revoke_account(m["id"], business_id=biz["id"])
    except registry.UnknownBusiness:
        raise HTTPException(404, "No such business.") from None
    except registry.RegistryError as e:
        raise HTTPException(400, str(e)) from None
    return {"business": _view(biz)}


def _iso_days_ago(n: int) -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(days=n)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _facts(b) -> dict:
    """What a business has set up and how much it is used, read from its own database. Sizes, statuses and staff actions only: no customer names, messages or order contents."""
    cut = _iso_days_ago(30)
    with db.business(b["id"]):
        n = lambda q, a=(): db.get(q, list(a))["n"]      # noqa: E731
        counts = {"products": n("SELECT COUNT(*) n FROM products"), "customers": n("SELECT COUNT(*) n FROM customers"), "conversations": n("SELECT COUNT(*) n FROM conversations"),
                  "orders": n("SELECT COUNT(*) n FROM orders"), "orders30": n("SELECT COUNT(*) n FROM orders WHERE created_at >= ?", [cut]),
                  "messages30": n("SELECT COUNT(*) n FROM messages WHERE created_at >= ?", [cut]), "openConversations": n("SELECT COUNT(*) n FROM conversations WHERE status='open'")}
        channels = [{"kind": c["kind"], "name": c["name"], "status": c["status"], "live": bool(c["live"]), "lastWebhookAt": c["last_webhook_at"], "lastError": c["last_error"]} for c in db.all("SELECT * FROM channels ORDER BY created_at")]
        integ = [{"id": i["id"], "group": i["grp"], "name": i["name"], "status": i["status"], "live": bool(i["live"]), "lastError": i["last_error"]} for i in db.all("SELECT * FROM integrations")]
        sources = [{"host": s_["host"], "kind": s_["kind"], "lastSyncAt": s_["last_sync_at"], "lastCount": s_["last_count"], "lastError": s_["last_error"], "ordersCount": s_["orders_count"]} for s_ in db.all("SELECT * FROM catalog_sources")]
        try:
            st = aikey.status()
            ai = {"engine": aikey.engine_id() if has_model() else "offline", "source": st["source"], "provider": st["providerLabel"], "model": st["model"], "quota": st["quota"], "lastError": st["lastError"]}
        except Exception:  # noqa: BLE001
            ai = {"engine": "offline", "source": None, "provider": None, "model": None, "quota": None, "lastError": None}
        audit = [{"at": a["at"], "actor": a["actor"], "action": a["action"], "target": a["target"]} for a in db.all("SELECT at, actor, action, target FROM audit ORDER BY id DESC LIMIT 20")]
        last_msg = db.get("SELECT MAX(last_message_at) t FROM conversations")["t"]
        onboarding = db.get_setting("onboarding", None) or {}
    couriers = [i for i in integ if i["group"] == "Couriers" and i["live"]]
    payments = [i for i in integ if i["group"] == "Payments" and i["live"] and i["id"] != "cod"]
    sms = [i for i in integ if i["group"] == "SMS" and i["live"]]
    return {"counts": counts, "channels": channels, "integrations": integ, "catalogSources": sources, "ai": ai, "audit": audit, "lastActivityAt": max([x for x in (last_msg, audit[0]["at"] if audit else None) if x], default=None),
            "features": {"channels": sorted({c["kind"] for c in channels if c["kind"] != "web" and c["status"] != "off"}), "webChat": any(c["kind"] == "web" for c in channels), "couriers": [i["name"] for i in couriers],
                         "payments": [i["name"] for i in payments], "sms": [i["name"] for i in sms], "websiteImport": len(sources), "ai": ai["engine"], "aiSource": ai["source"]},
            "setupGuide": {"shown": bool(onboarding.get("show")) and not onboarding.get("dismissed")}}


@router.get("/businesses/{ref}")
async def business_detail(ref: str):
    """One business as the platform sees it: plan and usage, who is in it, what it has connected, and its recent staff activity."""
    try:
        b = registry.resolve(ref)
    except registry.UnknownBusiness:
        raise HTTPException(404, "No such business.") from None
    p = registry.plan_of(b["id"])
    members = [{"id": m["id"], "name": m["name"], "email": m["email"], "role": m["role"], "active": bool(m["member_active"]) and bool(m["active"]), "lastLoginAt": m["last_login_at"]} for m in registry.members_of(b["id"])]
    f = _facts(b)
    return {**_view(b), "members": members, "usage": {"aiReplies": registry.usage_get(b["id"], "ai_replies"), "seats": registry.seats_used(b["id"]), "period": registry.period_now()},
            "plan": {"id": p["id"], "name": p["name"], "seats": p["seats"], "products": p["products"], "aiReplies": p["ai_replies"], "platformAi": bool(p["platform_ai"])}, **f}


@router.get("/features")
async def features():
    """The feature matrix: every business against what it has connected and how much it is used."""
    out = []
    for b in registry.all_businesses():
        try:
            f = _facts(b)
        except Exception:  # noqa: BLE001 - a broken business must not hide the others
            out.append({"slug": b["slug"], "name": b["name"], "status": b["status"], "error": "Its database could not be read."})
            continue
        out.append({"slug": b["slug"], "name": b["name"], "status": b["status"], "plan": b["plan"], "counts": f["counts"], "features": f["features"], "lastActivityAt": f["lastActivityAt"]})
    return {"items": out}


class DeleteBusiness(BaseModel):
    confirm: str = Field(max_length=80)                    # the business's address, typed out, so it cannot happen by a stray click


@router.post("/businesses/{ref}/delete")
async def delete_business(ref: str, b: DeleteBusiness, user: dict = Depends(auth.platform_admin)):
    """Remove a business and its whole database for good. The person must type its address; the default business can never be removed."""
    try:
        biz = registry.resolve(ref)
        if b.confirm.strip().lower() != biz["slug"]:
            raise registry.RegistryError(f"Type the business address “{biz['slug']}” to confirm.")
        slug, name = biz["slug"], biz["name"]
        registry.delete(biz["id"])
    except registry.UnknownBusiness:
        raise HTTPException(404, "No such business.") from None
    except registry.RegistryError as e:
        raise HTTPException(400, str(e)) from None
    registry.log_platform(user, "business.delete", slug, name)
    return {"ok": True}


@router.post("/businesses/{ref}/export")
async def export_business(ref: str, user: dict = Depends(auth.platform_admin)):
    """Build the business's data export and return a one-time download address (valid for about a minute)."""
    try:
        biz = registry.resolve(ref)
    except registry.UnknownBusiness:
        raise HTTPException(404, "No such business.") from None
    data, name = export.build(biz["id"])
    registry.log_platform(user, "business.export", biz["slug"], f"{len(data)} bytes")
    return {"url": f"/api/platform/download/{export.make_link(data, name)}", "filename": name, "bytes": len(data)}


@downloads.get("/download/{token}")
async def download(token: str):
    got = export.take_link(token)
    if not got:
        raise HTTPException(404, "This download link has expired. Make a new one.")
    data, name = got
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@router.post("/businesses/{ref}/join")
async def join_business(ref: str, user: dict = Depends(auth.platform_admin)):
    """Support access: the administrator joins a business as an admin so they can open it. It is written in that business's own activity log, so its owners can see it."""
    try:
        biz = registry.resolve(ref)
    except registry.UnknownBusiness:
        raise HTTPException(404, "No such business.") from None
    existing = registry.membership(user["id"], biz["id"])
    if existing and existing["active"]:
        return {"business": _view(biz), "role": existing["role"]}
    registry.add_membership(user["id"], biz["id"], "admin")
    with db.business(biz["id"]):
        auth.audit("support.join", user["name"], "Platform support joined this business as an admin.", actor=user)
    registry.log_platform(user, "support.join", biz["slug"])
    return {"business": _view(biz), "role": "admin"}


@router.post("/businesses/{ref}/leave")
async def leave_business(ref: str, user: dict = Depends(auth.platform_admin)):
    try:
        biz = registry.resolve(ref)
    except registry.UnknownBusiness:
        raise HTTPException(404, "No such business.") from None
    m = registry.membership(user["id"], biz["id"])
    if not m:
        raise HTTPException(409, "You are not a member of this business.")
    if m["role"] == "owner" and registry.count_active_owners(biz["id"]) <= 1:
        raise HTTPException(409, "You are the only owner. Add another owner first.")
    registry.remove_membership(user["id"], biz["id"])
    registry.detach_sessions(user["id"], biz["id"])
    with db.business(biz["id"]):
        auth.audit("support.leave", user["name"], "Platform support left this business.", actor=user)
    registry.log_platform(user, "support.leave", biz["slug"])
    return {"ok": True}


# ---------------------------------------------------------------- overview, accounts, the platform's own record
@router.get("/overview")
async def overview():
    rows = registry.all_businesses()
    period = registry.period_now()
    return {"period": period, "businesses": {"total": len(rows), "active": len([b for b in rows if b["status"] == "active"]),
                                              "trial": len([b for b in rows if b["status"] == "trial"]), "suspended": len([b for b in rows if b["status"] == "suspended"])},
            "accounts": registry.account_count(), "aiReplies": sum(registry.usage_get(b["id"], "ai_replies") for b in rows)}


def _account_row(a) -> dict:
    ms = registry.memberships_all(a["id"])
    return {"id": a["id"], "name": a["name"], "email": a["email"], "active": bool(a["active"]), "platformAdmin": bool(a["platform_admin"]), "mustChange": bool(a["must_change"]),
            "createdAt": a["created_at"], "lastLoginAt": a["last_login_at"], "sessions": len(registry.sessions_of(a["id"])),
            "businesses": [{"slug": m["slug"], "name": m["name"], "role": m["role"], "active": bool(m["active"]), "status": m["status"]} for m in ms]}


@router.get("/accounts")
async def accounts():
    return {"items": [_account_row(a) for a in registry.all_accounts()]}


@router.get("/accounts/{aid}")
async def account_detail(aid: str):
    a = registry.account_by_id(aid)
    if not a:
        raise HTTPException(404, "No such account.")
    sess = [{"createdAt": x["created_at"], "lastSeenAt": x["last_seen_at"], "expiresAt": x["expires_at"], "ip": x["ip"], "device": (x["agent"] or "")[:80], "business": x["slug"], "businessName": x["name"]}
            for x in registry.sessions_of(aid)]
    log = [{"at": r["at"], "action": r["action"], "actor": r["actor"]} for r in registry.platform_log(500) if r["target"] == a["email"]][:15]
    return {**_account_row(a), "sessionList": sess, "platformLog": log}


class NewAccount(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=1, max_length=200)           # a temporary one: they must choose their own at first sign-in
    business: str | None = Field(default=None, max_length=60)
    role: str = Field(default="agent", max_length=10)


@router.post("/accounts")
async def create_account(b: NewAccount, user: dict = Depends(auth.platform_admin)):
    """Make an account (and optionally put it in a business) without that business's owner having to invite them."""
    email = b.email.strip().lower()
    if "@" not in email or " " in email:
        raise HTTPException(400, "Enter a valid email address.")
    if b.role not in auth.ROLES:
        raise HTTPException(400, "Role must be owner, admin, agent or viewer.")
    auth.check_password_rules(b.password, email)
    if registry.account_by_email(email):
        raise HTTPException(409, "An account with that email already exists.")
    biz = None
    if b.business:
        try:
            biz = registry.resolve(b.business)
        except registry.UnknownBusiness:
            raise HTTPException(404, "No such business.") from None
        with db.business(biz["id"]):
            limits.require_seat()
    acct = registry.create_account(b.name, email, await auth.hash_password(b.password), must_change=True)
    if biz:
        registry.add_membership(acct["id"], biz["id"], b.role)
        with db.business(biz["id"]):
            auth.audit("team.add", email, f"{b.role} (added by platform support)", actor=user)
    registry.log_platform(user, "account.create", email, biz["slug"] if biz else None)
    return _account_row(registry.account_by_id(acct["id"]))


class ResetPw(BaseModel):
    password: str = Field(min_length=1, max_length=200)


@router.post("/accounts/{aid}/reset-password")
async def reset_account_password(aid: str, b: ResetPw, user: dict = Depends(auth.platform_admin)):
    """Set a temporary password for someone who is locked out. They are signed out everywhere and must choose their own at the next sign-in."""
    a = registry.account_by_id(aid)
    if not a:
        raise HTTPException(404, "No such account.")
    if a["id"] == user["id"]:
        raise HTTPException(400, "Change your own password from the account menu.")
    auth.check_password_rules(b.password, a["email"])
    registry.set_password(aid, await auth.hash_password(b.password), True)
    registry.revoke_account(aid)
    registry.log_platform(user, "account.reset_password", a["email"])
    return {"ok": True}


class MemberBody(BaseModel):
    role: str | None = Field(default=None, max_length=10)
    active: bool | None = None


@router.put("/accounts/{aid}/memberships/{ref}")
async def set_account_membership(aid: str, ref: str, b: MemberBody, user: dict = Depends(auth.platform_admin)):
    """Add an account to a business or change its role / switch it off there."""
    a = registry.account_by_id(aid)
    if not a:
        raise HTTPException(404, "No such account.")
    try:
        biz = registry.resolve(ref)
    except registry.UnknownBusiness:
        raise HTTPException(404, "No such business.") from None
    if b.role is not None and b.role not in auth.ROLES:
        raise HTTPException(400, "Role must be owner, admin, agent or viewer.")
    cur = registry.membership(aid, biz["id"])
    role = b.role or (cur["role"] if cur else "agent")
    active = b.active if b.active is not None else (bool(cur["active"]) if cur else True)
    if cur and cur["role"] == "owner" and cur["active"] and (role != "owner" or not active) and registry.count_active_owners(biz["id"]) <= 1:
        raise HTTPException(409, "There must always be at least one active owner. Make someone else an owner first.")
    if (not cur or not cur["active"]) and active:
        with db.business(biz["id"]):
            limits.require_seat()
    registry.add_membership(aid, biz["id"], role, active)
    if not active:
        registry.detach_sessions(aid, biz["id"])
    with db.business(biz["id"]):
        auth.audit("team.update" if cur else "team.add", a["email"], f"{role}{'' if active else ', switched off'} (by platform support)", actor=user)
    registry.log_platform(user, "membership.set", a["email"], f"{biz['slug']}: {role}{'' if active else ' (off)'}")
    return _account_row(registry.account_by_id(aid))


@router.delete("/accounts/{aid}/memberships/{ref}")
async def remove_account_membership(aid: str, ref: str, user: dict = Depends(auth.platform_admin)):
    a = registry.account_by_id(aid)
    if not a:
        raise HTTPException(404, "No such account.")
    try:
        biz = registry.resolve(ref)
    except registry.UnknownBusiness:
        raise HTTPException(404, "No such business.") from None
    cur = registry.membership(aid, biz["id"])
    if not cur:
        raise HTTPException(404, "That account is not in this business.")
    if cur["role"] == "owner" and cur["active"] and registry.count_active_owners(biz["id"]) <= 1:
        raise HTTPException(409, "There must always be at least one active owner. Make someone else an owner first.")
    registry.remove_membership(aid, biz["id"])
    registry.detach_sessions(aid, biz["id"])
    with db.business(biz["id"]):
        auth.audit("team.remove", a["email"], "removed by platform support", actor=user)
    registry.log_platform(user, "membership.remove", a["email"], biz["slug"])
    return _account_row(registry.account_by_id(aid))


class PatchAccount(BaseModel):
    active: bool | None = None
    signOut: bool = False
    name: str | None = Field(default=None, min_length=2, max_length=80)
    platformAdmin: bool | None = None


@router.patch("/accounts/{aid}")
async def patch_account(aid: str, b: PatchAccount, user: dict = Depends(auth.platform_admin)):
    """Stop an account from signing in anywhere (or allow it again), or sign it out of every device."""
    a = registry.account_by_id(aid)
    if not a:
        raise HTTPException(404, "No such account.")
    if b.active is False:
        if a["id"] == user["id"]:
            raise HTTPException(400, "You cannot stop your own account.")
        if a["platform_admin"] and registry.platform_admin_count() <= 1:
            raise HTTPException(400, "That is the only platform administrator.")
        registry.set_account_active(aid, False)
        registry.log_platform(user, "account.stop", a["email"])
    elif b.active is True:
        registry.set_account_active(aid, True)
        registry.log_platform(user, "account.allow", a["email"])
    if b.signOut:
        registry.revoke_account(aid)
        registry.log_platform(user, "account.signout", a["email"])
    if b.name:
        registry.set_name(aid, b.name)
        registry.log_platform(user, "account.rename", a["email"], b.name)
    if b.platformAdmin is not None and bool(a["platform_admin"]) != b.platformAdmin:
        if not b.platformAdmin and (a["id"] == user["id"] or registry.platform_admin_count() <= 1):
            raise HTTPException(400, "There must always be another platform administrator. You cannot remove your own, or the last one.")
        registry.set_platform_admin(aid, b.platformAdmin)
        registry.log_platform(user, "account.admin_on" if b.platformAdmin else "account.admin_off", a["email"])
    a = registry.account_by_id(aid)
    return {"id": a["id"], "active": bool(a["active"]), "platformAdmin": bool(a["platform_admin"]), "name": a["name"]}


@router.post("/accounts/{aid}/delete")
async def delete_account(aid: str, user: dict = Depends(auth.platform_admin)):
    """Remove an account for good (a person who asks to be forgotten). Only when it belongs to no business any more and is not a platform administrator."""
    a = registry.account_by_id(aid)
    if not a:
        raise HTTPException(404, "No such account.")
    if a["platform_admin"]:
        raise HTTPException(400, "A platform administrator's account cannot be deleted here.")
    if registry.all_memberships_of(aid):
        raise HTTPException(409, "This account still belongs to a business. Remove it from every business first.")
    registry.delete_account(aid)
    registry.log_platform(user, "account.delete", a["email"])
    return {"ok": True}


@router.get("/log")
async def platform_log(limit: int = 100):
    return {"items": [{"id": r["id"], "at": r["at"], "actor": r["actor"], "action": r["action"], "target": r["target"], "detail": r["detail"]} for r in registry.platform_log(limit)]}


# ---------------------------------------------------------------- health and backups
STARTED = time.time()
BACKUP_STALE_HOURS = 36


@router.get("/health")
async def health():
    """Is the server healthy: background jobs, backups, database files. For the platform administrator's monitoring page (and anything polling it)."""
    biz = []
    for b in registry.all_businesses():
        p = Path(b["path"])
        biz.append({"slug": b["slug"], "status": b["status"], "bytes": (p.stat().st_size + (Path(str(p) + "-wal").stat().st_size if Path(str(p) + "-wal").exists() else 0)) if p.exists() else None, "fileMissing": not p.exists()})
    last = backups.last_status()
    listed = backups.list_backups()
    problems = []
    for x in biz:
        if x["fileMissing"]:
            problems.append(f"The database file of {x['slug']} is missing.")
    for label, r in jobs.LAST.items():
        if r["failed"]:
            problems.append(f"The {label} job failed for: {', '.join(sorted(r['failed']))}.")
    if db.hosted():
        if not listed:
            problems.append("No backup has been made yet.")
        elif last and not last["ok"]:
            problems.append("The last scheduled backup failed: " + "; ".join(last.get("problems") or ["unknown reason"]))
        else:
            from datetime import datetime, timezone
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(listed[0]["createdAt"].replace("Z", "+00:00"))).total_seconds() / 3600
            if age > BACKUP_STALE_HOURS:
                problems.append(f"The newest backup is {int(age)} hours old.")
    return {"ok": not problems, "problems": problems, "uptimeSeconds": int(time.time() - STARTED), "hosted": db.hosted(), "strict": db.strict(), "openDatabases": db.open_count(),
            "businesses": biz, "jobs": jobs.LAST, "backup": {"last": last, "count": len(listed), "newest": listed[0]["name"] if listed else None}}


@router.get("/backups")
async def list_backups():
    return {"items": backups.list_backups(), "directory": str(backups.backup_dir()), "note": "A backup does not contain the master key (DAKBOX_SECRET_KEY). Keep that separately."}


@router.post("/backups")
async def make_backup(user: dict = Depends(auth.platform_admin)):
    import asyncio
    m = await asyncio.to_thread(backups.create, f"manual, by {user['name']}")
    v = backups.verify(m["name"])
    registry.log_platform(user, "backup.create", m["name"], "verified" if v["ok"] else "DOES NOT VERIFY")
    return {"name": m["name"], "verify": v}


@router.post("/backups/{name}/drill")
async def drill_backup(name: str, user: dict = Depends(auth.platform_admin)):
    """Restore the backup into a scratch folder and open every business from it. Never touches live data."""
    import asyncio
    try:
        r = await asyncio.to_thread(backups.drill, name)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(404, str(e)) from None
    registry.log_platform(user, "backup.drill", name, "ok" if r["ok"] else "FAILED")
    return r


# ---------------------------------------------------------------- plans and usage
def _plan_view(p) -> dict:
    return {"id": p["id"], "name": p["name"], "seats": p["seats"], "products": p["products"], "aiReplies": p["ai_replies"], "platformAi": bool(p["platform_ai"]),
            "businesses": len([b for b in registry.all_businesses() if b["plan"] == p["id"]])}


class PlanBody(BaseModel):
    name: str = Field(min_length=2, max_length=40)
    seats: int | None = Field(default=None, ge=0, le=10_000_000)
    products: int | None = Field(default=None, ge=0, le=10_000_000)
    aiReplies: int | None = Field(default=None, ge=0, le=10_000_000)
    platformAi: bool = False


@router.get("/plans")
async def plans():
    """null means unlimited."""
    return {"items": [_plan_view(p) for p in registry.plans()]}


@router.put("/plans/{pid}")
async def save_plan(pid: str, b: PlanBody, user: dict = Depends(auth.platform_admin)):
    try:
        registry.save_plan(pid, b.name, b.seats, b.products, b.aiReplies, b.platformAi)
    except registry.RegistryError as e:
        raise HTTPException(400, str(e)) from None
    return {"plan": _plan_view(registry.plan_row(pid))}


@router.get("/usage")
async def usage():
    """This month, per business: team seats, products and AI replies against their plan."""
    out = []
    for b in registry.all_businesses():
        p = registry.plan_of(b["id"])
        with db.business(b["id"]):
            products = db.get("SELECT COUNT(*) n FROM products")["n"]
        out.append({"slug": b["slug"], "name": b["name"], "status": b["status"], "plan": p["name"], "seats": {"used": registry.seats_used(b["id"]), "limit": p["seats"]},
                    "products": {"used": products, "limit": p["products"]}, "aiReplies": {"used": registry.usage_get(b["id"], "ai_replies"), "limit": p["ai_replies"], "platformAi": p["platform_ai"]}})
    return {"period": registry.period_now(), "items": out}


# ---------------------------------------------------------------- the platform's own AI keys
PLATFORM_PROVIDERS = ("anthropic", "openai", "gemini", "deepseek")


def _ai_view() -> dict:
    st = registry.platform_ai()
    items = []
    for pid in PLATFORM_PROVIDERS:
        sealed = st["keys"].get(pid)
        k = unseal_master(sealed) if sealed else None
        env = aikey.env_key(pid)
        m = st["models"].get(pid) or {}
        items.append({"id": pid, "label": aikey.PROVIDERS[pid]["label"], "hasKey": bool(k or env), "source": "stored" if k else ("environment" if env else None),
                      "masked": aikey.mask(k or env), "model": m.get("model"), "smallModel": m.get("small")})
    return {"items": items, "note": "Businesses on a plan that allows platform AI use these keys, and their replies count against the plan's monthly allowance."}


class PlatformAiBody(BaseModel):
    provider: str = Field(max_length=20)
    key: str = Field(min_length=1, max_length=400)
    model: str | None = Field(default=None, max_length=120)
    smallModel: str | None = Field(default=None, max_length=120)
    skipCheck: bool = False


@router.get("/ai")
async def platform_ai_status():
    return _ai_view()


@router.put("/ai")
async def platform_ai_save(b: PlatformAiBody, user: dict = Depends(auth.platform_admin)):
    """Save a key businesses on a suitable plan can use. Checked with the provider first; stored encrypted with the master key, never shown again."""
    try:
        if b.provider not in PLATFORM_PROVIDERS:
            raise aikey.KeyError_("Choose Claude, ChatGPT, Gemini or DeepSeek.")
        key = aikey.normalize_key(b.provider, b.key)
        res = {"models": [], "modelAvailable": None}
        if not b.skipCheck:
            res = await aikey.check(b.provider, key, (b.model or "").strip() or None)
    except aikey.KeyError_ as e:
        raise HTTPException(502 if e.kind == "network" else 400, str(e)) from None
    st = registry.platform_ai()
    st["keys"][b.provider] = seal_master(key)
    st["models"][b.provider] = {"model": (b.model or "").strip() or None, "small": (b.smallModel or "").strip() or None}
    registry.save_platform_ai(st)
    return {**_ai_view(), "models": res["models"], "modelAvailable": res["modelAvailable"]}


@router.delete("/ai")
async def platform_ai_remove(provider: str, user: dict = Depends(auth.platform_admin)):
    st = registry.platform_ai()
    if provider not in st["keys"]:
        raise HTTPException(409, "No platform key is saved for that provider.")
    st["keys"].pop(provider)
    st["models"].pop(provider, None)
    registry.save_platform_ai(st)
    return _ai_view()
