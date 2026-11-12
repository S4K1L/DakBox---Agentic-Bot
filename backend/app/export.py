"""A business's data as a zip a person can open: one CSV per table plus a manifest. Secrets (channel tokens, signing secrets, AI keys, password hashes,
sign-in sessions) are never included, so the file is safe to hand to the business owner."""
from __future__ import annotations

import csv
import io
import json
import secrets
import time
import zipfile

from . import db, registry

SKIP_TABLES = {"users", "sessions", "webhook_log", "sqlite_sequence"}
SECRET_WORDS = ("credential", "secret", "password", "token_hash")
SECRET_SETTINGS = {"ai_key", "ai_keys", "meta"}
_links: dict[str, tuple[bytes, str, float]] = {}
LINK_SECONDS = 90


def _secret_col(name: str) -> bool:
    n = name.lower()
    return any(w in n for w in SECRET_WORDS)


def _secret_setting(key: str) -> bool:
    return key in SECRET_SETTINGS or key.startswith(("bkash_token", "pay_token"))


def build(ref: str) -> tuple[bytes, str]:
    """(zip bytes, file name) for the business `ref`. Reads that one business only."""
    b = registry.resolve(ref)
    buf = io.BytesIO()
    counts: dict[str, int] = {}
    with db.business(b["id"]), zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        tables = [r["name"] for r in db.all("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        for t in tables:
            if t in SKIP_TABLES:
                continue
            rows = db.all(f'SELECT * FROM "{t}"')
            cols = [r["name"] for r in db.all(f'PRAGMA table_info("{t}")') if not _secret_col(r["name"])]
            if t == "settings":
                rows = [r for r in rows if not _secret_setting(r["key"])]
            out = io.StringIO()
            w = csv.writer(out)
            w.writerow(cols)
            for r in rows:
                w.writerow([r[c] for c in cols])
            z.writestr(f"{t}.csv", out.getvalue())
            counts[t] = len(rows)
        manifest = {"business": b["name"], "slug": b["slug"], "plan": b["plan"], "status": b["status"], "createdAt": b["created_at"],
                    "exportedAt": registry._now(), "rows": counts,
                    "note": "One CSV per table. Channel tokens, signing secrets, AI keys, password hashes and sign-in sessions are left out on purpose."}
        z.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
    stamp = time.strftime("%Y%m%d", time.gmtime())
    return buf.getvalue(), f"{b['slug']}-export-{stamp}.zip"


def make_link(data: bytes, filename: str) -> str:
    """A single-use token, valid for a minute and a half, so the browser can download without sending the sign-in header."""
    now = time.time()
    for k in [k for k, v in _links.items() if v[2] < now]:
        _links.pop(k, None)
    tok = secrets.token_urlsafe(24)
    _links[tok] = (data, filename, now + LINK_SECONDS)
    return tok


def take_link(tok: str) -> tuple[bytes, str] | None:
    v = _links.pop(tok, None)
    if not v or v[2] < time.time():
        return None
    return v[0], v[1]
