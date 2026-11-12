"""Which business a PUBLIC request (a webhook, a payment callback, the website chat) is for.

These doors have no login, so the business must be in the address: /webhooks/meta/<slug>, /pay/<slug>/<provider>/<kind>, /widget?b=<slug>, and so on.
Each business uses its own secrets, so a request signed for business A can never be accepted at business B's address.

The original single-business addresses (/webhooks/meta, /pay/<provider>/<kind>, ...) keep working for the default business, so nothing already configured at
Meta or a payment gateway breaks. On a strict (hosted) install they are switched off: every address must name its business.
"""
from __future__ import annotations

from fastapi import HTTPException

from . import db, ratelimit, registry


def enter(slug: str | None) -> str:
    """Select the business for the rest of this request. An unknown or suspended business is a plain 404, never a fallback to another one."""
    if not slug:
        if db.strict():
            raise HTTPException(404, "Not found.")
        bid = registry.default_id()
        db.set_business(bid)
        ratelimit.check("door", bid)
        return bid
    try:
        b = registry.resolve(slug)
    except registry.UnknownBusiness:
        raise HTTPException(404, "Not found.") from None
    if b["status"] == "suspended":
        raise HTTPException(404, "Not found.")
    db.set_business(b["id"])
    ratelimit.check("door", b["id"])
    return b["id"]


def slug() -> str:
    """The current business's address name."""
    return registry.resolve(db.current() or registry.default_id())["slug"]


def seg() -> str:
    """The address piece for the current business: empty for the default business on a single-business install (the original addresses), else /<slug>."""
    bid = db.current() or registry.default_id()
    if bid == registry.default_id() and not db.strict():
        return ""
    return "/" + registry.resolve(bid)["slug"]
