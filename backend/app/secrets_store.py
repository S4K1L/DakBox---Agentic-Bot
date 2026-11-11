"""Encryption for credentials kept in the database (Meta access tokens and the Meta app secret).

Fernet (AES-128-CBC + HMAC). The key comes from DAKBOX_SECRET_KEY; if that is not set a key file is created next to the
database on first use (mode 600). For production set the environment variable so the key lives apart from the data.
Secrets are never returned by the API and never written to logs.
"""
from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

_fernet: Fernet | None = None


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


def seal(text: str) -> str:
    return _f().encrypt(text.encode()).decode()


def unseal(token: str | None) -> str | None:
    if not token:
        return None
    try:
        return _f().decrypt(token.encode()).decode()
    except InvalidToken:
        return None  # wrong key or tampered: treat as "not set" rather than crash


def mask(value: str | None) -> str | None:
    """Show only enough of a secret to recognise it: ••••1234."""
    if not value:
        return None
    return "••••" + value[-4:] if len(value) > 8 else "••••"
