"""SQLite access. One connection, used only from the event-loop thread (all handlers are async)."""
from __future__ import annotations

import json
import os
import random
import sqlite3
import string
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

DB_PATH = os.environ.get("DAKBOX_DB") or str(Path(__file__).resolve().parent.parent / "dakbox.db")

_conn = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
_conn.row_factory = sqlite3.Row
_conn.execute("PRAGMA journal_mode = WAL")
_conn.execute("PRAGMA foreign_keys = ON")

SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, handle TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'ok', health TEXT NOT NULL DEFAULT '[]', alert TEXT,
  last_message_at TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS customers (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, phone TEXT, lang TEXT NOT NULL DEFAULT 'en',
  area TEXT, verified TEXT NOT NULL DEFAULT 'none', tags TEXT NOT NULL DEFAULT '[]',
  hue INTEGER NOT NULL DEFAULT 210, external_id TEXT, channel_kind TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers(id), channel_id TEXT NOT NULL REFERENCES channels(id),
  mode TEXT NOT NULL DEFAULT 'agent', status TEXT NOT NULL DEFAULT 'open', unread INTEGER NOT NULL DEFAULT 0,
  preview TEXT NOT NULL DEFAULT '', last_message_at TEXT NOT NULL, handoff_reason TEXT,
  window_expires_at TEXT, summary TEXT, pending TEXT, cart TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL REFERENCES conversations(id),
  role TEXT NOT NULL, author TEXT, text TEXT NOT NULL DEFAULT '', translation TEXT, meta TEXT,
  delivery TEXT, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id, id);
CREATE TABLE IF NOT EXISTS products (
  id TEXT PRIMARY KEY, sku TEXT UNIQUE NOT NULL, name TEXT NOT NULL, variant TEXT, price INTEGER NOT NULL,
  stock INTEGER NOT NULL DEFAULT 0, sold30 INTEGER NOT NULL DEFAULT 0, art TEXT, description TEXT, keywords TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS orders (
  id TEXT PRIMARY KEY, number TEXT UNIQUE NOT NULL, customer_id TEXT NOT NULL REFERENCES customers(id), channel_kind TEXT,
  items TEXT NOT NULL, shipping INTEGER NOT NULL DEFAULT 0, zone TEXT NOT NULL DEFAULT 'dhaka', address TEXT,
  pay_status TEXT NOT NULL, pay_method TEXT, pay_ref TEXT, fulfillment TEXT NOT NULL, stage INTEGER NOT NULL DEFAULT 0,
  times TEXT NOT NULL DEFAULT '[]', courier TEXT, scans TEXT NOT NULL DEFAULT '[]', log TEXT NOT NULL DEFAULT '[]',
  return_requested INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
  id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL, customer_id TEXT NOT NULL REFERENCES customers(id),
  conversation_id TEXT, order_number TEXT, item TEXT, amount INTEGER NOT NULL DEFAULT 0, reason TEXT, said TEXT,
  said_tr TEXT, policy TEXT, attachment TEXT, status TEXT NOT NULL DEFAULT 'pending', due_at TEXT, decided_at TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS policies (key TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS integrations (
  id TEXT PRIMARY KEY, grp TEXT NOT NULL, name TEXT NOT NULL, letter TEXT NOT NULL, status TEXT NOT NULL, note TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, product_id TEXT NOT NULL, customer_id TEXT NOT NULL, conversation_id TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT, engine TEXT, ms INTEGER, tools TEXT, handed_off INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
"""
SCHEMA_AUTH = """
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE COLLATE NOCASE, name TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('owner','admin','agent','viewer')),
  password_hash TEXT NOT NULL, must_change INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1,
  hue INTEGER NOT NULL DEFAULT 220, last_login_at TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL, expires_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, ip TEXT, agent TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, actor_id TEXT, actor TEXT NOT NULL,
  action TEXT NOT NULL, target TEXT, detail TEXT
);
"""
_conn.executescript(SCHEMA)
_conn.executescript(SCHEMA_AUTH)


def ensure_column(table: str, col: str, ddl: str) -> None:
    """Tiny migration helper: add a column to an existing table if it is missing."""
    cols = [r["name"] for r in _conn.execute(f"PRAGMA table_info({table})")]
    if col not in cols:
        _conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")


# Real Meta channels: which account a channel is, how to reach it, and what we last saw from it.
for _col, _ddl in [
    ("external_id", "TEXT"),            # WhatsApp phone number ID / Facebook Page ID / Instagram account ID
    ("config", "TEXT"),                 # JSON: {"via": "...", "waba_id": "..."}
    ("credentials", "TEXT"),            # encrypted JSON: {"access_token": "..."}
    ("token_expires_at", "TEXT"),
    ("last_webhook_at", "TEXT"),
    ("webhook_count", "INTEGER NOT NULL DEFAULT 0"),
    ("last_check_at", "TEXT"),
    ("last_error", "TEXT"),
    ("verified_name", "TEXT"),
    ("live", "INTEGER NOT NULL DEFAULT 0"),
]:
    ensure_column("channels", _col, _ddl)
# Courier and payment providers: encrypted credentials live on the integrations row.
for _col, _ddl in [
    ("credentials", "TEXT"),            # encrypted JSON of secrets (API keys, passwords, tokens)
    ("config", "TEXT"),                 # JSON of non-secret settings (mode, base URL, flat delivery charges)
    ("live", "INTEGER NOT NULL DEFAULT 0"),
    ("last_check_at", "TEXT"),
    ("last_error", "TEXT"),
    ("verified_name", "TEXT"),
]:
    ensure_column("integrations", _col, _ddl)
_conn.executescript("""
CREATE TABLE IF NOT EXISTS payments (
  id TEXT PRIMARY KEY, order_number TEXT NOT NULL, provider TEXT NOT NULL, amount INTEGER NOT NULL, currency TEXT NOT NULL DEFAULT 'BDT',
  tran_id TEXT NOT NULL UNIQUE, status TEXT NOT NULL, provider_ref TEXT, link_url TEXT, trx_id TEXT, mode TEXT,
  created_at TEXT NOT NULL, paid_at TEXT, created_by TEXT, conversation_id TEXT, note TEXT, refunded INTEGER NOT NULL DEFAULT 0, extra TEXT
);
CREATE INDEX IF NOT EXISTS idx_pay_order ON payments(order_number);
CREATE TABLE IF NOT EXISTS payment_refunds (
  id TEXT PRIMARY KEY, payment_id TEXT NOT NULL REFERENCES payments(id), amount INTEGER NOT NULL, status TEXT NOT NULL,
  provider_ref TEXT, reason TEXT, created_by TEXT, created_at TEXT NOT NULL, note TEXT, manual INTEGER NOT NULL DEFAULT 0
);
""")
_conn.executescript("""
CREATE TABLE IF NOT EXISTS sms_messages (
  id TEXT PRIMARY KEY, order_number TEXT, event TEXT NOT NULL, to_phone TEXT NOT NULL, body TEXT NOT NULL, encoding TEXT, parts INTEGER NOT NULL DEFAULT 1,
  provider TEXT, provider_ref TEXT, csms TEXT, status TEXT NOT NULL, error TEXT, created_at TEXT NOT NULL, send_after TEXT NOT NULL,
  sent_at TEXT, updated_at TEXT, last_report_at TEXT, by_user TEXT, manual INTEGER NOT NULL DEFAULT 0, dedupe_key TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_sms_status ON sms_messages(status, send_after);
CREATE INDEX IF NOT EXISTS idx_sms_phone ON sms_messages(to_phone, created_at);
""")
ensure_column("messages", "external_id", "TEXT")
ensure_column("conversations", "checkout", "TEXT")
for _c, _d in (("source", "TEXT"), ("ship_name", "TEXT"), ("ship_phone", "TEXT")):
    ensure_column("orders", _c, _d)
_conn.executescript("""
CREATE TABLE IF NOT EXISTS identities (
  kind TEXT NOT NULL, external_id TEXT NOT NULL, customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  PRIMARY KEY (kind, external_id)
);
CREATE INDEX IF NOT EXISTS idx_ident_customer ON identities(customer_id);
INSERT OR IGNORE INTO identities(kind, external_id, customer_id) SELECT channel_kind, external_id, id FROM customers WHERE external_id IS NOT NULL AND channel_kind IS NOT NULL;
""")
_conn.executescript("""
CREATE UNIQUE INDEX IF NOT EXISTS idx_msg_ext ON messages(external_id) WHERE external_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS webhook_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, kind TEXT, account_id TEXT, outcome TEXT NOT NULL, detail TEXT
);
""")


def all(query: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    return _conn.execute(query, tuple(params)).fetchall()


def get(query: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
    return _conn.execute(query, tuple(params)).fetchone()


def run(query: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
    return _conn.execute(query, tuple(params))


def script(sql: str) -> None:
    _conn.executescript(sql)


class tx:
    """with tx(): ... commits on success, rolls back on error."""

    def __enter__(self):
        _conn.execute("BEGIN")

    def __exit__(self, et, ev, tb):
        _conn.execute("ROLLBACK" if et else "COMMIT")
        return False


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def ago(minutes: float) -> str:
    """A timestamp `minutes` in the past (negative = future)."""
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def jl(s: str | None, fallback: Any = None) -> Any:
    if not s:
        return fallback
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        return fallback


def dumps(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False)


def uid(prefix: str) -> str:
    return f"{prefix}_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=7))


def get_setting(key: str, fallback: Any = None) -> Any:
    r = get("SELECT value FROM settings WHERE key = ?", [key])
    return jl(r["value"], fallback) if r else fallback


def set_setting(key: str, value: Any) -> None:
    run("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", [key, dumps(value)])
