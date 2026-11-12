"""Start-up checks for a hosted install (DAKBOX_HOSTED=1). A hosted server refuses to start if something that protects other people's businesses is missing,
instead of quietly running in a weaker mode."""
from __future__ import annotations

import os

from . import db


def problems() -> list[str]:
    if not db.hosted():
        return []
    out = []
    if not os.environ.get("DAKBOX_SECRET_KEY"):
        out.append("DAKBOX_SECRET_KEY is not set. Every business's secrets are encrypted with keys derived from it; a key file next to the code is not acceptable on a hosted server.")
    if not os.environ.get("DAKBOX_DATA_DIR"):
        out.append("DAKBOX_DATA_DIR is not set. Say where the registry and every business's database live (and back up).")
    if os.environ.get("DAKBOX_STRICT_BUSINESS") == "0":
        out.append("DAKBOX_STRICT_BUSINESS=0 turns off the protection against a request with no business selected. Remove it.")
    if os.environ.get("DAKBOX_ENV") not in (None, "", "production"):
        out.append("DAKBOX_ENV must be 'production' (or unset) on a hosted server.")
    return out


def enforce() -> None:
    bad = problems()
    if bad:
        raise RuntimeError("Dakbox will not start in hosted mode:\n - " + "\n - ".join(bad))
