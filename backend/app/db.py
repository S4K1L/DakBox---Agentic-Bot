"""SQLite access, one database file per business.

A small registry (registry.py) lists the businesses and where each one's file is. Every call here runs against the file of the *current business*,
a context variable set by `with db.business(ref):` (and, in later phases, by the request's session and by background jobs).
With no business selected, a single-business install keeps working: the call uses the default business (the original dakbox.db).
Set DAKBOX_STRICT_BUSINESS=1 for a hosted, multi-business install: then "no business selected" is an error, never a silent default.

Each connection is used only from the event-loop thread (all handlers are async).
"""
from __future__ import annotations

import json
import os
import random
import sqlite3
import string
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

DB_PATH = os.environ.get("DAKBOX_DB") or str(Path(__file__).resolve().parent.parent / "dakbox.db")      # the default business's file
DATA_DIR = Path(os.environ.get("DAKBOX_DATA_DIR") or Path(DB_PATH).resolve().parent)                      # registry.db and businesses/ live here
MAX_OPEN = int(os.environ.get("DAKBOX_MAX_OPEN_DBS") or 64)

_ctx: ContextVar[str | None] = ContextVar("dakbox_business", default=None)
_pool: "OrderedDict[str, sqlite3.Connection]" = OrderedDict()


class NoBusiness(RuntimeError):
    """A database call was made with no business selected on a strict (multi-business) install."""


def hosted() -> bool:
    """DAKBOX_HOSTED=1: this install serves other people's businesses. Strict business selection is on by default, the startup checks in hosting.py apply, and no demo data is made."""
    return os.environ.get("DAKBOX_HOSTED") == "1"


def strict() -> bool:
    """With no business selected, a database call is an error instead of using the original business. Always on when hosted (unless switched off on purpose with DAKBOX_STRICT_BUSINESS=0, which hosting.py refuses)."""
    v = os.environ.get("DAKBOX_STRICT_BUSINESS")
    return v == "1" or (hosted() and v != "0")


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


def _ensure(c: sqlite3.Connection, table: str, col: str, ddl: str) -> None:
    """Tiny migration helper: add a column to an existing table if it is missing."""
    cols = [r["name"] for r in c.execute(f"PRAGMA table_info({table})")]
    if col not in cols:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")


def ensure_column(table: str, col: str, ddl: str) -> None:
    _ensure(conn(), table, col, ddl)


def _init(c: sqlite3.Connection) -> None:
    """Create or upgrade every table in one business's file. Runs each time a file is opened, so an old file is upgraded when it is first used."""
    c.executescript(SCHEMA)
    c.executescript(SCHEMA_AUTH)



    # Products imported from a website: where each one came from, so a re-sync updates it instead of duplicating it.
    for _col, _ddl in [("image", "TEXT"), ("source", "TEXT"), ("source_id", "TEXT"), ("source_url", "TEXT"), ("synced_at", "TEXT")]:
        _ensure(c, "products", _col, _ddl)
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_products_source ON products(source, source_id) WHERE source_id IS NOT NULL")
    c.execute("""CREATE TABLE IF NOT EXISTS catalog_sources (
      id TEXT PRIMARY KEY, host TEXT UNIQUE NOT NULL, url TEXT NOT NULL, kind TEXT NOT NULL, default_stock INTEGER NOT NULL DEFAULT 10,
      currency TEXT, created_at TEXT NOT NULL, last_sync_at TEXT, last_count INTEGER NOT NULL DEFAULT 0, last_note TEXT, last_error TEXT)""")

    for _c, _d in (("order_secret", "TEXT"), ("order_sms", "INTEGER NOT NULL DEFAULT 1"), ("orders_at", "TEXT"), ("orders_count", "INTEGER NOT NULL DEFAULT 0"), ("orders_error", "TEXT")):
        _ensure(c, "catalog_sources", _c, _d)

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
        _ensure(c, "channels", _col, _ddl)
    # Courier and payment providers: encrypted credentials live on the integrations row.
    for _col, _ddl in [
        ("credentials", "TEXT"),            # encrypted JSON of secrets (API keys, passwords, tokens)
        ("config", "TEXT"),                 # JSON of non-secret settings (mode, base URL, flat delivery charges)
        ("live", "INTEGER NOT NULL DEFAULT 0"),
        ("last_check_at", "TEXT"),
        ("last_error", "TEXT"),
        ("verified_name", "TEXT"),
    ]:
        _ensure(c, "integrations", _col, _ddl)
    c.executescript("""
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
    c.executescript("""
    CREATE TABLE IF NOT EXISTS sms_messages (
      id TEXT PRIMARY KEY, order_number TEXT, event TEXT NOT NULL, to_phone TEXT NOT NULL, body TEXT NOT NULL, encoding TEXT, parts INTEGER NOT NULL DEFAULT 1,
      provider TEXT, provider_ref TEXT, csms TEXT, status TEXT NOT NULL, error TEXT, created_at TEXT NOT NULL, send_after TEXT NOT NULL,
      sent_at TEXT, updated_at TEXT, last_report_at TEXT, by_user TEXT, manual INTEGER NOT NULL DEFAULT 0, dedupe_key TEXT UNIQUE
    );
    CREATE INDEX IF NOT EXISTS idx_sms_status ON sms_messages(status, send_after);
    CREATE INDEX IF NOT EXISTS idx_sms_phone ON sms_messages(to_phone, created_at);
    """)
    _ensure(c, "messages", "external_id", "TEXT")
    _ensure(c, "conversations", "checkout", "TEXT")
    for _c, _d in (("source", "TEXT"), ("ship_name", "TEXT"), ("ship_phone", "TEXT"),
                   ("ext_source", "TEXT"), ("ext_id", "TEXT"), ("ext_number", "TEXT"), ("site_total", "INTEGER")):    # orders that arrive from a website
        _ensure(c, "orders", _c, _d)
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_orders_ext ON orders(ext_source, ext_id) WHERE ext_id IS NOT NULL")
    c.executescript("""
    CREATE TABLE IF NOT EXISTS identities (
      kind TEXT NOT NULL, external_id TEXT NOT NULL, customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
      PRIMARY KEY (kind, external_id)
    );
    CREATE INDEX IF NOT EXISTS idx_ident_customer ON identities(customer_id);
    INSERT OR IGNORE INTO identities(kind, external_id, customer_id) SELECT channel_kind, external_id, id FROM customers WHERE external_id IS NOT NULL AND channel_kind IS NOT NULL;
    """)
    c.executescript("""
    CREATE UNIQUE INDEX IF NOT EXISTS idx_msg_ext ON messages(external_id) WHERE external_id IS NOT NULL;
    CREATE TABLE IF NOT EXISTS webhook_log (
      id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, kind TEXT, account_id TEXT, outcome TEXT NOT NULL, detail TEXT
    );
    """)




def _open(path: str | Path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode = WAL")
    c.execute("PRAGMA foreign_keys = ON")
    _init(c)
    return c


# ---------------------------------------------------------------- which business is current
def current() -> str | None:
    """The id of the business this code is running for, or None."""
    return _ctx.get()


def _resolve() -> str:
    bid = _ctx.get()
    if bid:
        return bid
    if strict():
        raise NoBusiness("No business is selected for this database call.")
    from . import registry
    return registry.default_id()


@contextmanager
def business(ref: str) -> Iterator[str]:
    """Run the block for one business (by id or slug). Nests and restores; async code and tasks created inside inherit it."""
    from . import registry
    bid = registry.resolve(ref)["id"]
    tok = _ctx.set(bid)
    try:
        yield bid
    finally:
        _ctx.reset(tok)


def set_business(bid: str) -> None:
    """Select the business for the rest of this request or task (the request's session decides which; nothing else may call this with a client-supplied value)."""
    _ctx.set(bid)


def conn() -> sqlite3.Connection:
    bid = _resolve()
    c = _pool.get(bid)
    if c is not None:
        _pool.move_to_end(bid)
        return c
    from . import registry
    c = _open(registry.path_of(bid))
    _pool[bid] = c
    while len(_pool) > MAX_OPEN:                      # close the least recently used file; it reopens on next use
        old, oc = next(iter(_pool.items()))
        if old == bid:
            break
        _pool.pop(old)
        oc.close()
    return c


def close_business(bid: str) -> None:
    c = _pool.pop(bid, None)
    if c is not None:
        c.close()


def close_all() -> None:
    for bid in list(_pool):
        close_business(bid)


def open_count() -> int:
    return len(_pool)


def all(query: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    return conn().execute(query, tuple(params)).fetchall()


def get(query: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
    return conn().execute(query, tuple(params)).fetchone()


def run(query: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
    return conn().execute(query, tuple(params))


def script(sql: str) -> None:
    conn().executescript(sql)


class tx:
    """with tx(): ... commits on success, rolls back on error."""

    def __enter__(self):
        conn().execute("BEGIN")

    def __exit__(self, et, ev, tb):
        conn().execute("ROLLBACK" if et else "COMMIT")
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
