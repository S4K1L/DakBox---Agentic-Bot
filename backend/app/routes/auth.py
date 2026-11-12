from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import auth, db, limits, registry

router = APIRouter(prefix="/api")

_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,}$")


def _email(v: str) -> str:
    v = v.strip().lower()
    if not _EMAIL.match(v):
        raise HTTPException(400, "Enter a valid email address.")
    return v


class SetupBody(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: str
    password: str


class LoginBody(BaseModel):
    email: str
    password: str = Field(max_length=200)


class PasswordBody(BaseModel):
    current: str = Field(max_length=200)
    new: str


# ---------------------------------------------------------------- public
@router.get("/auth/status")
async def status():
    """Tells the app whether this is a brand-new install that still needs its first owner."""
    return {"setupRequired": auth.user_count() == 0, "hosted": db.hosted()}


def _enter(acct, bid: str | None) -> dict:
    """The user as the app needs it: their role in the business they are working in, and the businesses they can switch to."""
    biz = registry.resolve(bid) if bid else None
    m = registry.membership(acct["id"], bid) if bid else None
    return auth.view(registry.account_by_id(acct["id"]), m["role"] if m else "viewer", auth.business_view(biz) if biz else None, auth.my_businesses(acct["id"]))


@router.post("/auth/setup")
async def setup(b: SetupBody, request: Request):
    """Create the first owner (also the platform administrator). Refused once any account exists, so it cannot be used to take over an install."""
    email = _email(b.email)
    auth.check_password_rules(b.password, email)
    h = await auth.hash_password(b.password)
    if auth.user_count() > 0:
        raise HTTPException(409, "This workspace is already set up. Sign in instead.")
    acct = registry.create_account(b.name, email, h, platform_admin=True)
    if db.hosted():
        # A hosted server's first account is the super administrator only. Businesses (and their owners) are created from the super admin panel,
        # so the super administrator is not made the owner of anyone's business.
        registry.log_platform(_enter(acct, None), "platform.setup", email, "first super administrator created")
        return {"token": auth.open_session(acct["id"], None, request), "user": _enter(acct, None)}
    bid = registry.default_id()                              # a single-shop install: the first person is the super administrator and the shop's owner
    registry.add_membership(acct["id"], bid, "owner")
    token = auth.open_session(acct["id"], bid, request)
    with db.business(bid):
        auth.audit("workspace.setup", email, "first owner created", actor=_enter(acct, bid))
    return {"token": token, "user": _enter(acct, bid)}


@router.post("/auth/login")
async def login(b: LoginBody, request: Request):
    email = b.email.strip().lower()
    auth.check_throttle(request, email)
    acct = registry.account_by_email(email)
    ok = await auth.verify_password(b.password, acct["password_hash"] if acct else auth._DUMMY)  # same work either way
    if not acct or not ok or not acct["active"]:
        auth.record_fail(request, email)
        for m in (registry.memberships_of(acct["id"])[:5] if acct else []):          # a failed attempt is recorded where that person works, never elsewhere
            with db.business(m["id"]):
                auth.audit("login.fail", email, None, actor=None)
        raise HTTPException(401, "Wrong email or password.")
    auth.clear_fails(request, email)
    bid = registry.pick_business(acct["id"], acct["last_business_id"])
    if not bid and not acct["platform_admin"]:           # removed from every business: locked out, with the same generic answer as a wrong password
        raise HTTPException(401, "Wrong email or password.")
    token = auth.open_session(acct["id"], bid, request)
    if bid:
        with db.business(bid):
            auth.audit("login", email, None, actor=_enter(acct, bid))
    return {"token": token, "user": _enter(acct, bid)}


class SwitchBody(BaseModel):
    business: str = Field(min_length=1, max_length=60)


@router.post("/auth/switch")
async def switch(b: SwitchBody, user: dict = Depends(auth.current_user)):
    """Work in another business you belong to. The same sign-in carries over; nothing from the previous business stays selected."""
    try:
        biz = registry.resolve(b.business)
    except registry.UnknownBusiness:
        raise HTTPException(403, "You are not a member of that business.") from None
    m = registry.membership(user["id"], biz["id"])
    if not m or not m["active"]:
        raise HTTPException(403, "You are not a member of that business.")
    if biz["status"] == "suspended":
        raise HTTPException(403, "That business is suspended.")
    registry.switch_session(user["_token"], biz["id"])
    acct = registry.account_by_id(user["id"])
    return {"user": _enter(acct, biz["id"])}


# ---------------------------------------------------------------- signed in
@router.post("/auth/logout")
async def logout(user: dict = Depends(auth.current_user)):
    auth.revoke_session(user["_token"])
    return {"ok": True}


@router.post("/auth/password")
async def change_password(b: PasswordBody, user: dict = Depends(auth.current_user)):
    row = registry.account_by_id(user["id"])
    if not await auth.verify_password(b.current, row["password_hash"]):
        raise HTTPException(400, "Your current password is not right.")
    if b.new == b.current:
        raise HTTPException(400, "Choose a password you have not used for this account.")
    auth.check_password_rules(b.new, row["email"])
    registry.set_password(user["id"], await auth.hash_password(b.new), False)
    auth.revoke_user_sessions(user["id"], except_token=user["_token"])  # sign out every other device, in every business
    if db.current():
        auth.audit("password.change", user["email"])
    return {"ok": True}


# ---------------------------------------------------------------- team (owner and admin of the current business)
Role = Literal["owner", "admin", "agent", "viewer"]


class InviteBody(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: str
    role: Role
    password: str


class PatchBody(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    role: Role | None = None
    active: bool | None = None


class ResetBody(BaseModel):
    password: str


def _bid(user: dict) -> str:
    return user["business"]["id"]


def _member_view(row) -> dict:
    return auth.view(row, row["role"], active=bool(row["member_active"]))


def _target(uid: str, actor: dict):
    """A member of THIS business. Anyone else (including a person who only belongs elsewhere) is simply not found."""
    t = next((r for r in registry.members_of(_bid(actor)) if r["id"] == uid), None)
    if not t:
        raise HTTPException(404, "No such team member.")
    if t["role"] == "owner" and actor["role"] != "owner":
        raise HTTPException(403, "Only an owner can change an owner.")
    return t


@router.get("/team")
async def team(user: dict = Depends(auth.require("team.manage"))):
    return {
        "items": [_member_view(r) for r in registry.members_of(_bid(user))],
        "roles": [{"role": r, "blurb": auth.ROLE_BLURB[r], "permissions": sorted(auth.ROLE_PERMS[r])} for r in auth.ROLES],
        "canGrantOwner": user["role"] == "owner",
        "seats": limits.seats(),
    }


@router.post("/team")
async def invite(b: InviteBody, user: dict = Depends(auth.require("team.manage"))):
    email = _email(b.email)
    if b.role == "owner" and user["role"] != "owner":
        raise HTTPException(403, "Only an owner can add another owner.")
    auth.check_password_rules(b.password, email)
    bid = _bid(user)
    acct = registry.account_by_email(email)
    if acct and registry.membership(acct["id"], bid):
        raise HTTPException(409, "Someone with that email is already on the team.")
    limits.require_seat()
    if not acct:                                  # a new person: they must pick their own password at first sign-in
        acct = registry.create_account(b.name, email, await auth.hash_password(b.password), must_change=True)
    # else: this person already has a Dakbox account (maybe in another business). They keep their own password and name; the password typed here is not used.
    registry.add_membership(acct["id"], bid, b.role)
    auth.audit("team.add", email, b.role)
    row = next(r for r in registry.members_of(bid) if r["id"] == acct["id"])
    return {"user": _member_view(row), "note": "If this person already has a Dakbox account they keep their own password."}


@router.patch("/team/{uid}")
async def update_member(uid: str, b: PatchBody, user: dict = Depends(auth.require("team.manage"))):
    t = _target(uid, user)
    bid = _bid(user)
    if b.role == "owner" and user["role"] != "owner":
        raise HTTPException(403, "Only an owner can make someone an owner.")
    leaving_owner = t["role"] == "owner" and ((b.role and b.role != "owner") or b.active is False)
    if leaving_owner and t["member_active"] and registry.count_active_owners(bid) <= 1:
        raise HTTPException(409, "There must always be at least one active owner.")
    if b.active is False and t["id"] == user["id"]:
        raise HTTPException(409, "You cannot deactivate your own account.")
    if b.role and t["id"] == user["id"] and user["role"] != "owner":
        raise HTTPException(409, "You cannot change your own role.")
    if b.name and b.name.strip() != t["name"]:
        if not registry.exclusive_to(uid, bid):
            raise HTTPException(409, "This person belongs to other businesses, so only they can change their name.")
        registry.set_name(uid, b.name)
    if b.role and b.role != t["role"]:
        registry.set_membership(uid, bid, role=b.role)
        auth.audit("team.role", t["email"], f"{t['role']} → {b.role}")
    if b.active is not None and bool(t["member_active"]) != b.active:
        if b.active:
            limits.require_seat()                  # bringing someone back needs a free seat
        registry.set_membership(uid, bid, active=b.active)
        if not b.active:
            auth.revoke_user_sessions(uid, business_id=bid)       # out of this business at once; their other businesses are untouched
        auth.audit("team.activate" if b.active else "team.deactivate", t["email"])
    return {"user": _member_view(next(r for r in registry.members_of(bid) if r["id"] == uid))}


@router.post("/team/{uid}/reset-password")
async def reset_password(uid: str, b: ResetBody, user: dict = Depends(auth.require("team.manage"))):
    t = _target(uid, user)
    if not registry.exclusive_to(uid, _bid(user)):
        raise HTTPException(409, "This person belongs to other businesses, so only they can change their password.")
    auth.check_password_rules(b.password, t["email"])
    registry.set_password(uid, await auth.hash_password(b.password), True)
    auth.revoke_user_sessions(uid)
    auth.audit("team.reset_password", t["email"])
    return {"ok": True}


@router.get("/audit")
async def audit_log(limit: int = 60, user: dict = Depends(auth.require("audit.read"))):
    rows = db.all("SELECT * FROM audit ORDER BY id DESC LIMIT ?", [max(1, min(limit, 200))])
    return {"items": [dict(r) for r in rows]}
