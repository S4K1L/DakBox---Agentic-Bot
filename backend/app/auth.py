"""Sign-in, sessions and role permissions.

- Passwords are hashed with scrypt (stdlib) and compared in constant time.
- A session is a random 256-bit token. Only its SHA-256 is stored, so a database leak cannot be replayed,
  and a session can be revoked (sign out, password change, deactivation).
- Roles: owner and admin can do everything (admins cannot touch owners); agent works the inbox and orders but
  cannot approve money or change settings; viewer is read-only.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import secrets
import time
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request

from . import db
from .util import hue_for, initials

SESSION_DAYS = 7
ROLES = ("owner", "admin", "agent", "viewer")

ALL_PERMS = (
    "conv.reply", "draft.approve", "approvals.decide", "orders.manage", "orders.refund",
    "products.stock", "products.manage", "settings.write", "connections.write", "team.manage", "audit.read", "simulate",
)
ROLE_PERMS: dict[str, set[str]] = {
    "owner": set(ALL_PERMS),
    "admin": set(ALL_PERMS),
    "agent": {"conv.reply", "draft.approve", "orders.manage", "products.stock", "simulate"},
    "viewer": set(),
}
ROLE_BLURB = {
    "owner": "Everything, including adding and changing other owners.",
    "admin": "Everything except changing owners: approvals, refunds, settings, connections and the team.",
    "agent": "Works the inbox and orders. Cannot approve returns or refunds, change settings or manage the team.",
    "viewer": "Read-only. Sees conversations, orders and insights; cannot change anything.",
}

_current: ContextVar[dict | None] = ContextVar("dakbox_user", default=None)


# ---------------------------------------------------------------- passwords
_N, _R, _P = 2**14, 8, 1
_COMMON = {"password", "password1", "password123", "1234567890", "qwertyuiop", "letmein123", "iloveyou12", "admin12345", "welcome123"}


def check_password_rules(pw: str, email: str = "") -> None:
    if len(pw) < 10:
        raise HTTPException(400, "Use at least 10 characters.")
    if len(pw) > 200:
        raise HTTPException(400, "That password is too long.")
    if pw.lower() in _COMMON or len(set(pw)) < 4:
        raise HTTPException(400, "That password is too easy to guess.")
    if email and pw.lower() == email.lower():
        raise HTTPException(400, "The password cannot be your email.")


def _hash_sync(pw: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(pw.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${dk.hex()}"


def _verify_sync(pw: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, dk = stored.split("$")
        got = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(got, bytes.fromhex(dk))
    except (ValueError, TypeError):
        return False


async def hash_password(pw: str) -> str:
    return await asyncio.to_thread(_hash_sync, pw)  # scrypt is slow on purpose: keep it off the event loop


async def verify_password(pw: str, stored: str) -> bool:
    return await asyncio.to_thread(_verify_sync, pw, stored)


_DUMMY = _hash_sync("dakbox-timing-equaliser")


# ---------------------------------------------------------------- login throttling
_fails: dict[str, list[float]] = {}
_MAX_FAILS, _WINDOW = 5, 15 * 60


def _key(request: Request, email: str) -> str:
    ip = request.client.host if request.client else "?"
    return f"{ip}|{email.lower()}"


def check_throttle(request: Request, email: str) -> None:
    k = _key(request, email)
    now = time.time()
    recent = [t for t in _fails.get(k, []) if now - t < _WINDOW]
    _fails[k] = recent
    if len(recent) >= _MAX_FAILS:
        wait = int(_WINDOW - (now - recent[0])) // 60 + 1
        raise HTTPException(429, f"Too many attempts. Try again in {wait} min.")


def record_fail(request: Request, email: str) -> None:
    _fails.setdefault(_key(request, email), []).append(time.time())


def clear_fails(request: Request, email: str) -> None:
    _fails.pop(_key(request, email), None)


# ---------------------------------------------------------------- users & sessions
def view(u) -> dict:
    return {
        "id": u["id"], "name": u["name"], "first": u["name"].split()[0], "email": u["email"], "initials": initials(u["name"]), "hue": u["hue"],
        "role": u["role"], "active": bool(u["active"]), "mustChange": bool(u["must_change"]), "lastLoginAt": u["last_login_at"], "createdAt": u["created_at"],
        "permissions": sorted(ROLE_PERMS[u["role"]]),
    }


def user_count() -> int:
    return db.get("SELECT COUNT(*) n FROM users")["n"]


def create_user(name: str, email: str, role: str, pw_hash: str, must_change: bool) -> dict:
    uid = db.uid("usr")
    db.run(
        "INSERT INTO users(id,email,name,role,password_hash,must_change,active,hue,created_at) VALUES(?,?,?,?,?,?,1,?,?)",
        [uid, email.strip().lower(), name.strip(), role, pw_hash, 1 if must_change else 0, hue_for(name), db.now()],
    )
    return db.get("SELECT * FROM users WHERE id=?", [uid])


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def open_session(user_id: str, request: Request | None) -> str:
    token = secrets.token_urlsafe(32)
    exp = (datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    db.run(
        "INSERT INTO sessions(token_hash,user_id,created_at,expires_at,last_seen_at,ip,agent) VALUES(?,?,?,?,?,?,?)",
        [_digest(token), user_id, db.now(), exp, db.now(), request.client.host if request and request.client else None, (request.headers.get("user-agent", "")[:160] if request else None)],
    )
    db.run("UPDATE users SET last_login_at=? WHERE id=?", [db.now(), user_id])
    db.run("DELETE FROM sessions WHERE expires_at < ?", [db.now()])  # housekeeping
    return token


def revoke_session(token: str) -> None:
    db.run("DELETE FROM sessions WHERE token_hash=?", [_digest(token)])


def revoke_user_sessions(user_id: str, except_token: str | None = None) -> None:
    if except_token:
        db.run("DELETE FROM sessions WHERE user_id=? AND token_hash != ?", [user_id, _digest(except_token)])
    else:
        db.run("DELETE FROM sessions WHERE user_id=?", [user_id])


def token_from(request: Request) -> str | None:
    h = request.headers.get("authorization", "")
    if h.lower().startswith("bearer "):
        return h[7:].strip() or None
    return request.query_params.get("token")  # EventSource cannot set headers


_PASSWORD_OK_PATHS = {"/api/me", "/api/auth/password", "/api/auth/logout"}


async def current_user(request: Request) -> dict:
    token = token_from(request)
    if not token:
        raise HTTPException(401, "Sign in to continue.")
    row = db.get(
        "SELECT u.*, s.expires_at FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash=?", [_digest(token)]
    )
    if not row or row["expires_at"] < db.now() or not row["active"]:
        raise HTTPException(401, "Your session has ended. Sign in again.")
    if row["must_change"] and request.url.path not in _PASSWORD_OK_PATHS:
        raise HTTPException(403, "password_change_required")
    u = view(row)
    u["_token"] = token
    _current.set(u)
    return u


def require(perm: str):
    async def dep(user: dict = Depends(current_user)) -> dict:
        if perm not in user["permissions"]:
            raise HTTPException(403, "Your role cannot do this.")
        return user
    return dep


def staff() -> str:
    """First name of whoever made the current request (used as the author on messages and events)."""
    u = _current.get()
    return u["first"] if u else "Staff"


def audit(action: str, target: str | None = None, detail: str | None = None, actor: dict | None = None) -> None:
    u = actor or _current.get()
    db.run("INSERT INTO audit(at,actor_id,actor,action,target,detail) VALUES(?,?,?,?,?,?)",
           [db.now(), u["id"] if u else None, u["name"] if u else "system", action, target, detail])
