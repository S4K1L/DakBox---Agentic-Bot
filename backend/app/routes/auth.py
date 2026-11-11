from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import auth, db

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
    return {"setupRequired": auth.user_count() == 0}


@router.post("/auth/setup")
async def setup(b: SetupBody, request: Request):
    """Create the first owner. Refused once any user exists, so it cannot be used to take over an install."""
    email = _email(b.email)
    auth.check_password_rules(b.password, email)
    h = await auth.hash_password(b.password)
    with db.tx():
        if auth.user_count() > 0:
            raise HTTPException(409, "This workspace is already set up. Sign in instead.")
        user = auth.create_user(b.name, email, "owner", h, must_change=False)
    token = auth.open_session(user["id"], request)
    auth.audit("workspace.setup", email, "first owner created", actor=auth.view(user))
    return {"token": token, "user": auth.view(db.get("SELECT * FROM users WHERE id=?", [user["id"]]))}


@router.post("/auth/login")
async def login(b: LoginBody, request: Request):
    email = b.email.strip().lower()
    auth.check_throttle(request, email)
    row = db.get("SELECT * FROM users WHERE email=?", [email])
    ok = await auth.verify_password(b.password, row["password_hash"] if row else auth._DUMMY)  # same work either way
    if not row or not ok or not row["active"]:
        auth.record_fail(request, email)
        auth.audit("login.fail", email, None, actor=None)
        raise HTTPException(401, "Wrong email or password.")
    auth.clear_fails(request, email)
    token = auth.open_session(row["id"], request)
    fresh = db.get("SELECT * FROM users WHERE id=?", [row["id"]])
    auth.audit("login", email, None, actor=auth.view(fresh))
    return {"token": token, "user": auth.view(fresh)}


# ---------------------------------------------------------------- signed in
@router.post("/auth/logout")
async def logout(user: dict = Depends(auth.current_user)):
    auth.revoke_session(user["_token"])
    return {"ok": True}


@router.post("/auth/password")
async def change_password(b: PasswordBody, user: dict = Depends(auth.current_user)):
    row = db.get("SELECT * FROM users WHERE id=?", [user["id"]])
    if not await auth.verify_password(b.current, row["password_hash"]):
        raise HTTPException(400, "Your current password is not right.")
    if b.new == b.current:
        raise HTTPException(400, "Choose a password you have not used for this account.")
    auth.check_password_rules(b.new, row["email"])
    db.run("UPDATE users SET password_hash=?, must_change=0 WHERE id=?", [await auth.hash_password(b.new), user["id"]])
    auth.revoke_user_sessions(user["id"], except_token=user["_token"])  # sign out every other device
    auth.audit("password.change", user["email"])
    return {"ok": True}


# ---------------------------------------------------------------- team (owner and admin)
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


def _active_owners() -> int:
    return db.get("SELECT COUNT(*) n FROM users WHERE role='owner' AND active=1")["n"]


def _target(uid: str, actor: dict):
    t = db.get("SELECT * FROM users WHERE id=?", [uid])
    if not t:
        raise HTTPException(404, "No such team member.")
    if t["role"] == "owner" and actor["role"] != "owner":
        raise HTTPException(403, "Only an owner can change an owner.")
    return t


@router.get("/team")
async def team(user: dict = Depends(auth.require("team.manage"))):
    rows = db.all("SELECT * FROM users ORDER BY CASE role WHEN 'owner' THEN 0 WHEN 'admin' THEN 1 WHEN 'agent' THEN 2 ELSE 3 END, name")
    return {
        "items": [auth.view(r) for r in rows],
        "roles": [{"role": r, "blurb": auth.ROLE_BLURB[r], "permissions": sorted(auth.ROLE_PERMS[r])} for r in auth.ROLES],
        "canGrantOwner": user["role"] == "owner",
    }


@router.post("/team")
async def invite(b: InviteBody, user: dict = Depends(auth.require("team.manage"))):
    email = _email(b.email)
    if b.role == "owner" and user["role"] != "owner":
        raise HTTPException(403, "Only an owner can add another owner.")
    auth.check_password_rules(b.password, email)
    if db.get("SELECT 1 FROM users WHERE email=?", [email]):
        raise HTTPException(409, "Someone with that email is already on the team.")
    u = auth.create_user(b.name, email, b.role, await auth.hash_password(b.password), must_change=True)  # they must pick their own password
    auth.audit("team.add", email, b.role)
    return {"user": auth.view(u)}


@router.patch("/team/{uid}")
async def update_member(uid: str, b: PatchBody, user: dict = Depends(auth.require("team.manage"))):
    t = _target(uid, user)
    if b.role == "owner" and user["role"] != "owner":
        raise HTTPException(403, "Only an owner can make someone an owner.")
    leaving_owner = t["role"] == "owner" and ((b.role and b.role != "owner") or b.active is False)
    if leaving_owner and t["active"] and _active_owners() <= 1:
        raise HTTPException(409, "There must always be at least one active owner.")
    if b.active is False and t["id"] == user["id"]:
        raise HTTPException(409, "You cannot deactivate your own account.")
    if b.role and t["id"] == user["id"] and user["role"] != "owner":
        raise HTTPException(409, "You cannot change your own role.")
    if b.name:
        db.run("UPDATE users SET name=? WHERE id=?", [b.name.strip(), uid])
    if b.role and b.role != t["role"]:
        db.run("UPDATE users SET role=? WHERE id=?", [b.role, uid])
        auth.audit("team.role", t["email"], f"{t['role']} → {b.role}")
    if b.active is not None and bool(t["active"]) != b.active:
        db.run("UPDATE users SET active=? WHERE id=?", [1 if b.active else 0, uid])
        if not b.active:
            auth.revoke_user_sessions(uid)
        auth.audit("team.activate" if b.active else "team.deactivate", t["email"])
    return {"user": auth.view(db.get("SELECT * FROM users WHERE id=?", [uid]))}


@router.post("/team/{uid}/reset-password")
async def reset_password(uid: str, b: ResetBody, user: dict = Depends(auth.require("team.manage"))):
    t = _target(uid, user)
    auth.check_password_rules(b.password, t["email"])
    db.run("UPDATE users SET password_hash=?, must_change=1 WHERE id=?", [await auth.hash_password(b.password), uid])
    auth.revoke_user_sessions(uid)
    auth.audit("team.reset_password", t["email"])
    return {"ok": True}


@router.get("/audit")
async def audit_log(limit: int = 60, user: dict = Depends(auth.require("audit.read"))):
    rows = db.all("SELECT * FROM audit ORDER BY id DESC LIMIT ?", [max(1, min(limit, 200))])
    return {"items": [dict(r) for r in rows]}
