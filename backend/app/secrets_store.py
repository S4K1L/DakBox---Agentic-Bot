"""Encryption for credentials kept in the database (Meta tokens, provider keys, AI keys, webhook secrets).

Fernet (AES-128-CBC + HMAC). The master key comes from DAKBOX_SECRET_KEY; if that is not set a key file is created next to the
database on first use (mode 600). For production set the environment variable so the key lives apart from the data.
Secrets are never returned by the API and never written to logs.

Each business has its OWN encryption key, derived from the master key and the business id (HKDF-SHA256). A secret sealed in one business
cannot be opened in another, even if its stored text were copied across. New secrets are written as "b1.<token>". Older values (no prefix,
written with the master key before businesses had their own keys) still open, but only in the default business, and `rekey_business`
rewrites them under the business's own key. Secrets that belong to the platform itself (not to any business) use the master key via seal_master/unseal_master.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_fernet: Fernet | None = None
_derived: dict[str, Fernet] = {}
PREFIX = "b1."


def _key() -> bytes:
    env = os.environ.get("DAKBOX_SECRET_KEY")
    if env:
        return env.encode()
    path = Path(os.environ.get("DAKBOX_SECRET_FILE") or Path(__file__).resolve().parent.parent / ".secret_key")
    if path.exists():
        return path.read_bytes().strip()
    key = Fernet.generate_key()
    path.write_bytes(key)
    os.chmod(path, 0o600)
    print(f"[secrets] created {path.name}; set DAKBOX_SECRET_KEY in production and keep this key out of backups of the database")
    return key


def _f() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_key())
    return _fernet


def _business_key(bid: str) -> Fernet:
    f = _derived.get(bid)
    if f is None:
        raw = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"dakbox-business-key-v1", info=bid.encode()).derive(_key())
        f = _derived[bid] = Fernet(base64.urlsafe_b64encode(raw))
    return f


def _bid() -> str:
    """The business whose key to use: the current one (a single-business install with none selected uses the default; a strict one refuses)."""
    from . import db, registry
    b = db.current()
    if b:
        return b
    if db.strict():
        raise db.NoBusiness("No business is selected, so there is no key to encrypt with.")
    return registry.default_id()


def seal(text: str) -> str:
    """Encrypt for the current business."""
    return PREFIX + _business_key(_bid()).encrypt(text.encode()).decode()


def unseal(token: str | None) -> str | None:
    """Decrypt for the current business. A value sealed for another business is simply 'not set' here."""
    if not token:
        return None
    try:
        if token.startswith(PREFIX):
            return _business_key(_bid()).decrypt(token[len(PREFIX):].encode()).decode()
        from . import registry
        if _bid() != registry.default_id():       # legacy values (master key) belong to the original install only
            return None
        return _f().decrypt(token.encode()).decode()
    except InvalidToken:
        return None  # wrong key or tampered: treat as "not set" rather than crash


def seal_master(text: str) -> str:
    """For secrets of the platform itself (not of a business)."""
    return "m1." + _f().encrypt(text.encode()).decode()


def unseal_master(token: str | None) -> str | None:
    if not token or not token.startswith("m1."):
        return None
    try:
        return _f().decrypt(token[3:].encode()).decode()
    except InvalidToken:
        return None


def is_legacy(token: str | None) -> bool:
    return bool(token) and not token.startswith(PREFIX)


# ---------------------------------------------------------------- moving old values under the business's own key
def rekey_business(ref: str) -> int:
    """Re-encrypt every stored secret of one business under its own key. Safe to repeat: only values still on the old key are touched. Returns how many were rewritten."""
    from . import db, registry
    n = 0
    with db.business(ref):
        def fix(v):
            nonlocal n
            if not is_legacy(v):
                return v
            plain = unseal(v)
            if plain is None:
                return v
            n += 1
            return seal(plain)
        for table, col in (("channels", "credentials"), ("integrations", "credentials"), ("catalog_sources", "order_secret")):
            for r in db.all(f"SELECT rowid AS rid, {col} AS v FROM {table} WHERE {col} IS NOT NULL AND {col} != ''"):
                nv = fix(r["v"])
                if nv != r["v"]:
                    db.run(f"UPDATE {table} SET {col}=? WHERE rowid=?", [nv, r["rid"]])
        meta = db.get_setting("meta", None)
        if isinstance(meta, dict):
            changed = {k: fix(v) if k in ("app_secret", "verify_token") else v for k, v in meta.items()}
            if changed != meta:
                db.set_setting("meta", changed)
        keys = db.get_setting("ai_keys", None)
        if isinstance(keys, dict):
            changed = {k: fix(v) for k, v in keys.items()}
            if changed != keys:
                db.set_setting("ai_keys", changed)
        legacy = db.get_setting("ai_key", None)
        if isinstance(legacy, str) and is_legacy(legacy):
            db.set_setting("ai_key", fix(legacy))
        for r in db.all("SELECT key, value FROM settings WHERE key LIKE 'bkash_token_%'"):
            v = db.jl(r["value"], None)
            if isinstance(v, str):
                nv = fix(v)
                if nv != v:
                    db.set_setting(r["key"], nv)
    return n


def rekey_all() -> int:
    from . import registry
    return sum(rekey_business(b["id"]) for b in registry.all_businesses())


def mask(value: str | None) -> str | None:
    """Show only enough of a secret to recognise it: ••••1234."""
    if not value:
        return None
    return "••••" + value[-4:] if len(value) > 8 else "••••"
