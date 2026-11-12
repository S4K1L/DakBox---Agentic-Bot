"""The registry: which businesses exist and where each one's database file is.

A separate small SQLite file (registry.db, next to the default database or in DAKBOX_DATA_DIR) holds only what must be global.
In this phase that is the list of businesses; later phases add user accounts, memberships, sessions and webhook routing.
Each business's data lives in its own file (businesses/<id>.db), so one business can never read another's rows by mistake.

The business that existed before this phase (the original dakbox.db) is registered as the "default" business, in place: nothing is moved or rewritten.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import db

REGISTRY_PATH = Path(db.DATA_DIR) / "registry.db"
DEFAULT_SLUG = "default"
RESERVED = {"admin", "api", "www", "app", "widget", "webhooks", "webhook", "pay", "static", "assets", "login", "logout", "signup", "register", "health", "w", "b", "platform", "support", "billing"}
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,38}[a-z0-9]$")

# id, name, seats, products, AI replies per month (None = unlimited), platform AI key allowed
DEFAULT_PLANS = [
    ("free", "Free", 3, 100, 100, 0, 1),
    ("standard", "Standard", 10, 1000, 2000, 1, 2),
    ("unlimited", "Unlimited", None, None, None, 1, 3),
]

_conn: sqlite3.Connection | None = None
_default_id: str | None = None
_migrated = False


class UnknownBusiness(KeyError):
    """No business with that id or slug (or it was deleted)."""


class RegistryError(ValueError):
    """A business name or address that cannot be used, worded for the person who typed it."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _c() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(REGISTRY_PATH), check_same_thread=False, isolation_level=None)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode = WAL")
        _conn.executescript("""
        CREATE TABLE IF NOT EXISTS businesses (
          id TEXT PRIMARY KEY, slug TEXT NOT NULL UNIQUE COLLATE NOCASE, name TEXT NOT NULL, path TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'active', plan TEXT NOT NULL DEFAULT 'free', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS accounts (
          id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE COLLATE NOCASE, name TEXT NOT NULL, password_hash TEXT NOT NULL,
          must_change INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1, platform_admin INTEGER NOT NULL DEFAULT 0,
          hue INTEGER NOT NULL DEFAULT 210, last_business_id TEXT, created_at TEXT NOT NULL, last_login_at TEXT
        );
        CREATE TABLE IF NOT EXISTS memberships (
          account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE, business_id TEXT NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
          role TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, PRIMARY KEY (account_id, business_id)
        );
        CREATE TABLE IF NOT EXISTS sessions (
          token_hash TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE, business_id TEXT,
          created_at TEXT NOT NULL, expires_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, ip TEXT, agent TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_reg_sessions_account ON sessions(account_id);
        CREATE TABLE IF NOT EXISTS registry_meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS plans (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, seats INTEGER, products INTEGER, ai_replies INTEGER, platform_ai INTEGER NOT NULL DEFAULT 0, sort INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS platform_log (
          id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, actor_id TEXT, actor TEXT NOT NULL, action TEXT NOT NULL, target TEXT, detail TEXT
        );
        CREATE TABLE IF NOT EXISTS usage (
          business_id TEXT NOT NULL, period TEXT NOT NULL, metric TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (business_id, period, metric)
        );
        """)
        _conn.execute("PRAGMA foreign_keys = ON")
        if "limits" not in [r["name"] for r in _conn.execute("PRAGMA table_info(businesses)")]:
            _conn.execute("ALTER TABLE businesses ADD COLUMN limits TEXT")        # optional per-business overrides of the plan, as JSON
        for pid, name, seats, products, ai, plat, sort in DEFAULT_PLANS:
            _conn.execute("INSERT OR IGNORE INTO plans(id,name,seats,products,ai_replies,platform_ai,sort) VALUES(?,?,?,?,?,?,?)", [pid, name, seats, products, ai, plat, sort])
    return _conn


def reset_for_tests() -> None:
    """Forget cached handles (the files stay). Tests use this after pointing the registry somewhere else."""
    global _conn, _default_id, _migrated
    if _conn is not None:
        _conn.close()
    _conn, _default_id, _migrated = None, None, False


# ---------------------------------------------------------------- reading
def ensure_default() -> sqlite3.Row:
    """The original single-business database, registered in place the first time the registry is used."""
    global _default_id
    row = _c().execute("SELECT * FROM businesses WHERE slug=?", [DEFAULT_SLUG]).fetchone()
    if not row:
        _c().execute("INSERT INTO businesses(id,slug,name,path,status,plan,created_at) VALUES(?,?,?,?,?,?,?)",
                     ["biz_default", DEFAULT_SLUG, "Default business", str(Path(db.DB_PATH).resolve()), "active", "unlimited", _now()])
        row = _c().execute("SELECT * FROM businesses WHERE slug=?", [DEFAULT_SLUG]).fetchone()
    _default_id = row["id"]
    if not _c().execute("SELECT 1 FROM registry_meta WHERE key='default_plan_unlimited'").fetchone():
        if row["plan"] == "free":                              # the original install keeps working exactly as before: no limits
            _c().execute("UPDATE businesses SET plan='unlimited' WHERE id=?", [row["id"]])
            row = _c().execute("SELECT * FROM businesses WHERE id=?", [row["id"]]).fetchone()
        _c().execute("INSERT OR REPLACE INTO registry_meta(key,value) VALUES('default_plan_unlimited',?)", [_now()])
    _migrate_legacy_once()
    return row


def default_id() -> str:
    return _default_id or ensure_default()["id"]


def resolve(ref: str) -> sqlite3.Row:
    """A business by id or slug. Unknown ones raise UnknownBusiness (never a default)."""
    ensure_default()
    row = _c().execute("SELECT * FROM businesses WHERE id=? OR slug=?", [ref, (ref or "").lower()]).fetchone()
    if not row:
        raise UnknownBusiness(ref)
    return row


def path_of(bid: str) -> str:
    row = _c().execute("SELECT path FROM businesses WHERE id=?", [bid]).fetchone()
    if not row:
        raise UnknownBusiness(bid)
    return row["path"]


def all_businesses() -> list[sqlite3.Row]:
    ensure_default()
    return _c().execute("SELECT * FROM businesses ORDER BY created_at, slug").fetchall()


# ---------------------------------------------------------------- writing
def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s[:40].strip("-")


def valid_slug(slug: str) -> str:
    s = (slug or "").strip().lower()
    if not _SLUG.match(s):
        raise RegistryError("The address can use only letters, numbers and dashes (2 to 40 characters, not starting or ending with a dash).")
    if s in RESERVED:
        raise RegistryError(f"“{s}” is reserved. Choose another address.")
    return s


def create(name: str, slug: str | None = None, *, bootstrap: bool = True) -> sqlite3.Row:
    """Make a new, empty business: its own database file with every table, and (by default) the standard starting setup."""
    ensure_default()
    nm = " ".join((name or "").split())
    if not (2 <= len(nm) <= 80):
        raise RegistryError("The business name must be 2 to 80 characters.")
    s = valid_slug(slug or slugify(nm) or "")
    if _c().execute("SELECT 1 FROM businesses WHERE slug=?", [s]).fetchone():
        raise RegistryError(f"The address “{s}” is already taken.")
    bid = db.uid("biz")
    path = Path(db.DATA_DIR) / "businesses" / f"{bid}.db"
    c = db._open(path)                                   # creates the file and every table
    c.close()
    _c().execute("INSERT INTO businesses(id,slug,name,path,status,plan,created_at) VALUES(?,?,?,?,?,?,?)", [bid, s, nm, str(path), "active", "free", _now()])
    if bootstrap:
        from . import seed
        with db.business(bid):
            seed.bootstrap(nm)
    return resolve(bid)


def rename(ref: str, name: str) -> sqlite3.Row:
    b = resolve(ref)
    nm = " ".join((name or "").split())
    if not (2 <= len(nm) <= 80):
        raise RegistryError("The business name must be 2 to 80 characters.")
    _c().execute("UPDATE businesses SET name=? WHERE id=?", [nm, b["id"]])
    return resolve(b["id"])


def set_status(ref: str, status: str) -> sqlite3.Row:
    if status not in ("active", "suspended", "trial"):
        raise RegistryError("Status must be active, trial or suspended.")
    b = resolve(ref)
    _c().execute("UPDATE businesses SET status=? WHERE id=?", [status, b["id"]])
    return resolve(b["id"])


def delete(ref: str) -> None:
    """Remove a business and its database file for good. The default business cannot be removed."""
    b = resolve(ref)
    if b["id"] == default_id():
        raise RegistryError("The default business cannot be deleted.")
    db.close_business(b["id"])
    for suffix in ("", "-wal", "-shm"):
        Path(str(b["path"]) + suffix).unlink(missing_ok=True)
    _c().execute("UPDATE sessions SET business_id=NULL WHERE business_id=?", [b["id"]])        # people working in it land on the business picker, signed in
    _c().execute("DELETE FROM usage WHERE business_id=?", [b["id"]])
    _c().execute("UPDATE accounts SET last_business_id=NULL WHERE last_business_id=?", [b["id"]])
    _c().execute("DELETE FROM businesses WHERE id=?", [b["id"]])


# ================================================================ people: accounts, memberships, sessions
# One account per person (global sign-in), a membership per business they belong to (with their role there), and sessions that name
# the business they are working in. The business of a request comes from the session only, never from anything the client sends.
import hashlib  # noqa: E402
import secrets as _secrets  # noqa: E402
from datetime import timedelta  # noqa: E402

from .util import hue_for  # noqa: E402

SESSION_DAYS = 7
_FMT = "%Y-%m-%dT%H:%M:%S.%fZ"


def account_count() -> int:
    return _c().execute("SELECT COUNT(*) n FROM accounts").fetchone()["n"]


def account_by_email(email: str):
    return _c().execute("SELECT * FROM accounts WHERE email=?", [(email or "").strip().lower()]).fetchone()


def account_by_id(aid: str):
    return _c().execute("SELECT * FROM accounts WHERE id=?", [aid]).fetchone()


def create_account(name: str, email: str, pw_hash: str, *, must_change: bool = False, platform_admin: bool = False, account_id: str | None = None, created_at: str | None = None):
    aid = account_id or db.uid("usr")
    _c().execute("INSERT INTO accounts(id,email,name,password_hash,must_change,active,platform_admin,hue,created_at) VALUES(?,?,?,?,?,1,?,?,?)",
                 [aid, email.strip().lower(), name.strip(), pw_hash, 1 if must_change else 0, 1 if platform_admin else 0, hue_for(name), created_at or _now()])
    return account_by_id(aid)


def set_password(account_id: str, pw_hash: str, must_change: bool) -> None:
    _c().execute("UPDATE accounts SET password_hash=?, must_change=? WHERE id=?", [pw_hash, 1 if must_change else 0, account_id])


def set_name(account_id: str, name: str) -> None:
    _c().execute("UPDATE accounts SET name=? WHERE id=?", [name.strip(), account_id])


def add_membership(account_id: str, business_id: str, role: str, active: bool = True) -> None:
    _c().execute("INSERT INTO memberships(account_id,business_id,role,active,created_at) VALUES(?,?,?,?,?) ON CONFLICT(account_id,business_id) DO UPDATE SET role=excluded.role, active=excluded.active",
                 [account_id, business_id, role, 1 if active else 0, _now()])


def membership(account_id: str, business_id: str):
    return _c().execute("SELECT * FROM memberships WHERE account_id=? AND business_id=?", [account_id, business_id]).fetchone()


def set_membership(account_id: str, business_id: str, *, role: str | None = None, active: bool | None = None) -> None:
    if role is not None:
        _c().execute("UPDATE memberships SET role=? WHERE account_id=? AND business_id=?", [role, account_id, business_id])
    if active is not None:
        _c().execute("UPDATE memberships SET active=? WHERE account_id=? AND business_id=?", [1 if active else 0, account_id, business_id])


def remove_membership(account_id: str, business_id: str) -> None:
    _c().execute("DELETE FROM memberships WHERE account_id=? AND business_id=?", [account_id, business_id])


def memberships_of(account_id: str) -> list:
    """The businesses a person can work in (active membership, business not deleted), oldest first."""
    return _c().execute(
        "SELECT m.role, m.active, b.id, b.slug, b.name, b.status, b.plan FROM memberships m JOIN businesses b ON b.id=m.business_id "
        "WHERE m.account_id=? AND m.active=1 ORDER BY m.created_at, b.slug", [account_id]).fetchall()


def members_of(business_id: str) -> list:
    return _c().execute(
        "SELECT a.*, m.role, m.active AS member_active FROM memberships m JOIN accounts a ON a.id=m.account_id WHERE m.business_id=? "
        "ORDER BY CASE m.role WHEN 'owner' THEN 0 WHEN 'admin' THEN 1 WHEN 'agent' THEN 2 ELSE 3 END, a.name", [business_id]).fetchall()


def exclusive_to(account_id: str, business_id: str) -> bool:
    """True when this person belongs to no other business, so that business may manage their password and name."""
    return _c().execute("SELECT COUNT(*) n FROM memberships WHERE account_id=? AND business_id != ?", [account_id, business_id]).fetchone()["n"] == 0


def count_active_owners(business_id: str) -> int:
    return _c().execute("SELECT COUNT(*) n FROM memberships m JOIN accounts a ON a.id=m.account_id WHERE m.business_id=? AND m.role='owner' AND m.active=1 AND a.active=1", [business_id]).fetchone()["n"]


def pick_business(account_id: str, preferred: str | None = None) -> str | None:
    """Where a person lands after signing in: the business they used last if they still can, else their oldest active one."""
    ms = [m for m in memberships_of(account_id) if m["status"] != "suspended"]
    ids = [m["id"] for m in ms]
    if preferred and preferred in ids:
        return preferred
    return ids[0] if ids else None


# ---------------------------------------------------------------- sessions
def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def open_session(account_id: str, business_id: str | None, ip: str | None, agent: str | None) -> str:
    token = _secrets.token_urlsafe(32)
    exp = (datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    c = _c()
    c.execute("INSERT INTO sessions(token_hash,account_id,business_id,created_at,expires_at,last_seen_at,ip,agent) VALUES(?,?,?,?,?,?,?,?)",
              [_digest(token), account_id, business_id, _now(), exp, _now(), ip, (agent or "")[:160]])
    c.execute("UPDATE accounts SET last_login_at=?, last_business_id=COALESCE(?, last_business_id) WHERE id=?", [_now(), business_id, account_id])
    c.execute("DELETE FROM sessions WHERE expires_at < ?", [_now()])
    return token


def session(token: str):
    return _c().execute("SELECT s.*, a.active AS account_active FROM sessions s JOIN accounts a ON a.id=s.account_id WHERE s.token_hash=?", [_digest(token)]).fetchone()


def switch_session(token: str, business_id: str) -> None:
    c = _c()
    c.execute("UPDATE sessions SET business_id=? WHERE token_hash=?", [business_id, _digest(token)])
    c.execute("UPDATE accounts SET last_business_id=? WHERE id=(SELECT account_id FROM sessions WHERE token_hash=?)", [business_id, _digest(token)])


def revoke_session(token: str) -> None:
    _c().execute("DELETE FROM sessions WHERE token_hash=?", [_digest(token)])


def revoke_account(account_id: str, *, except_token: str | None = None, business_id: str | None = None) -> None:
    q, a = "DELETE FROM sessions WHERE account_id=?", [account_id]
    if business_id:
        q, a = q + " AND business_id=?", a + [business_id]
    if except_token:
        q, a = q + " AND token_hash != ?", a + [_digest(except_token)]
    _c().execute(q, a)


def reset_accounts() -> None:
    """Tests: forget every account, membership and session (businesses stay)."""
    c = _c()
    for t in ("sessions", "memberships", "accounts"):
        c.execute(f"DELETE FROM {t}")


# ---------------------------------------------------------------- the one-time move from per-business users to accounts
def _migrate_legacy_once() -> None:
    global _migrated
    if _migrated:
        return
    _migrated = True
    for b in _c().execute("SELECT * FROM businesses").fetchall():
        marker = f"legacy_users:{b['id']}"
        if _c().execute("SELECT 1 FROM registry_meta WHERE key=?", [marker]).fetchone():
            continue
        if not Path(b["path"]).exists():
            continue
        with db.business(b["id"]):
            users = db.all("SELECT * FROM users")
            for u in users:
                acct = account_by_id(u["id"]) or account_by_email(u["email"])
                if not acct:
                    acct = create_account(u["name"], u["email"], u["password_hash"], must_change=bool(u["must_change"]), account_id=u["id"], created_at=u["created_at"])
                add_membership(acct["id"], b["id"], u["role"], bool(u["active"]))
                if b["id"] == default_id() and u["role"] == "owner" and not _c().execute("SELECT 1 FROM accounts WHERE platform_admin=1").fetchone():
                    _c().execute("UPDATE accounts SET platform_admin=1 WHERE id=?", [acct["id"]])      # whoever owns the original install runs the platform
            db.run("DELETE FROM sessions")                      # old per-business sign-ins end once: people sign in again
        _c().execute("INSERT OR REPLACE INTO registry_meta(key,value) VALUES(?,?)", [marker, _now()])


# ================================================================ plans, limits and usage
import json as _json  # noqa: E402


def plans() -> list:
    return _c().execute("SELECT * FROM plans ORDER BY sort, id").fetchall()


def plan_row(pid: str):
    return _c().execute("SELECT * FROM plans WHERE id=?", [pid]).fetchone()


def save_plan(pid: str, name: str, seats, products, ai_replies, platform_ai: bool) -> None:
    for v in (seats, products, ai_replies):
        if v is not None and (not isinstance(v, int) or v < 0 or v > 10_000_000):
            raise RegistryError("Limits must be whole numbers (or empty for unlimited).")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,23}", pid or ""):
        raise RegistryError("A plan id can use lowercase letters, numbers and dashes (up to 24).")
    nm = " ".join((name or "").split())
    if not 2 <= len(nm) <= 40:
        raise RegistryError("A plan name must be 2 to 40 characters.")
    _c().execute("INSERT INTO plans(id,name,seats,products,ai_replies,platform_ai,sort) VALUES(?,?,?,?,?,?,COALESCE((SELECT MAX(sort)+1 FROM plans),1)) "
                 "ON CONFLICT(id) DO UPDATE SET name=excluded.name, seats=excluded.seats, products=excluded.products, ai_replies=excluded.ai_replies, platform_ai=excluded.platform_ai",
                 [pid, nm, seats, products, ai_replies, 1 if platform_ai else 0])


def set_plan(ref: str, plan_id: str | None = None, limits: dict | None = None) -> sqlite3.Row:
    b = resolve(ref)
    if plan_id is not None:
        if not plan_row(plan_id):
            raise RegistryError("There is no such plan.")
        _c().execute("UPDATE businesses SET plan=? WHERE id=?", [plan_id, b["id"]])
    if limits is not None:
        clean = {}
        for k in ("seats", "products", "ai_replies"):
            if k in limits and limits[k] is not None:
                v = limits[k]
                if not isinstance(v, int) or v < 0 or v > 10_000_000:
                    raise RegistryError("Limits must be whole numbers.")
                clean[k] = v
        if "platform_ai" in limits and limits["platform_ai"] is not None:
            clean["platform_ai"] = 1 if limits["platform_ai"] else 0
        _c().execute("UPDATE businesses SET limits=? WHERE id=?", [_json.dumps(clean) if clean else None, b["id"]])
    return resolve(b["id"])


def plan_of(bid: str) -> dict:
    """What a business is allowed: its plan, with any per-business overrides applied. None means unlimited."""
    b = resolve(bid)
    p = plan_row(b["plan"]) or plan_row("free")
    out = {"id": p["id"], "name": p["name"], "seats": p["seats"], "products": p["products"], "ai_replies": p["ai_replies"], "platform_ai": bool(p["platform_ai"])}
    try:
        ov = _json.loads(b["limits"] or "{}")
    except ValueError:
        ov = {}
    for k in ("seats", "products", "ai_replies"):
        if k in ov:
            out[k] = ov[k]
    if "platform_ai" in ov:
        out["platform_ai"] = bool(ov["platform_ai"])
    out["overridden"] = sorted(ov)
    return out


def period_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def usage_add(bid: str, metric: str, n: int = 1) -> None:
    _c().execute("INSERT INTO usage(business_id,period,metric,n) VALUES(?,?,?,?) ON CONFLICT(business_id,period,metric) DO UPDATE SET n=n+excluded.n", [bid, period_now(), metric, n])


def usage_get(bid: str, metric: str, period: str | None = None) -> int:
    r = _c().execute("SELECT n FROM usage WHERE business_id=? AND period=? AND metric=?", [bid, period or period_now(), metric]).fetchone()
    return r["n"] if r else 0


def seats_used(bid: str) -> int:
    return _c().execute("SELECT COUNT(*) n FROM memberships m JOIN accounts a ON a.id=m.account_id WHERE m.business_id=? AND m.active=1 AND a.active=1", [bid]).fetchone()["n"]


# ---------------------------------------------------------------- the platform's own AI keys (used by businesses whose plan allows them)
def platform_ai() -> dict:
    try:
        d = _json.loads((_c().execute("SELECT value FROM registry_meta WHERE key='platform_ai'").fetchone() or {"value": "{}"})["value"] or "{}")
    except ValueError:
        d = {}
    return {"keys": d.get("keys") or {}, "models": d.get("models") or {}}


def save_platform_ai(d: dict) -> None:
    _c().execute("INSERT OR REPLACE INTO registry_meta(key,value) VALUES('platform_ai',?)", [_json.dumps(d)])


# ================================================================ the platform's own record and its people (phase 5)
def log_platform(actor: dict | None, action: str, target: str | None = None, detail: str | None = None) -> None:
    """What the platform administrator did to businesses and accounts (who, what, when). Kept in the registry, apart from every business's own activity log."""
    _c().execute("INSERT INTO platform_log(at,actor_id,actor,action,target,detail) VALUES(?,?,?,?,?,?)",
                 [_now(), actor["id"] if actor else None, actor["name"] if actor else "system", action, target, detail])


def platform_log(limit: int = 100) -> list:
    return _c().execute("SELECT * FROM platform_log ORDER BY id DESC LIMIT ?", [max(1, min(int(limit), 500))]).fetchall()


def all_accounts() -> list:
    return _c().execute("SELECT * FROM accounts ORDER BY platform_admin DESC, name COLLATE NOCASE").fetchall()


def set_account_active(account_id: str, active: bool) -> None:
    _c().execute("UPDATE accounts SET active=? WHERE id=?", [1 if active else 0, account_id])
    if not active:
        revoke_account(account_id)


def platform_admin_count() -> int:
    return _c().execute("SELECT COUNT(*) n FROM accounts WHERE platform_admin=1 AND active=1").fetchone()["n"]


def remove_all_memberships(business_id: str) -> None:
    _c().execute("DELETE FROM memberships WHERE business_id=?", [business_id])


def detach_sessions(account_id: str, business_id: str) -> None:
    """Move a person's open sessions out of one business without signing them out (they land on the business picker)."""
    _c().execute("UPDATE sessions SET business_id=NULL WHERE account_id=? AND business_id=?", [account_id, business_id])


def all_memberships_of(account_id: str) -> list:
    """Every membership of an account, active or not (memberships_of lists only the working ones)."""
    return _c().execute("SELECT * FROM memberships WHERE account_id=?", [account_id]).fetchall()


def delete_account(account_id: str) -> None:
    _c().execute("DELETE FROM sessions WHERE account_id=?", [account_id])
    _c().execute("DELETE FROM accounts WHERE id=?", [account_id])


def sessions_of(account_id: str) -> list:
    """An account's open sessions (never the token itself): where and when, and which business each is working in."""
    return _c().execute(
        "SELECT s.created_at, s.last_seen_at, s.expires_at, s.ip, s.agent, b.slug, b.name FROM sessions s LEFT JOIN businesses b ON b.id=s.business_id "
        "WHERE s.account_id=? AND s.expires_at > ? ORDER BY s.last_seen_at DESC", [account_id, _now()]).fetchall()


def memberships_all(account_id: str) -> list:
    """Every membership (active or not) with its business, for the platform's user page."""
    return _c().execute(
        "SELECT m.role, m.active, m.created_at, b.id, b.slug, b.name, b.status FROM memberships m JOIN businesses b ON b.id=m.business_id WHERE m.account_id=? ORDER BY b.slug", [account_id]).fetchall()


def set_platform_admin(account_id: str, on: bool) -> None:
    _c().execute("UPDATE accounts SET platform_admin=? WHERE id=?", [1 if on else 0, account_id])
