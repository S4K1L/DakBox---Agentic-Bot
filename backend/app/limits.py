"""What a business's plan allows: team seats, products and AI replies per month. Limits come from the plan (registry), with optional per-business overrides;
None means unlimited. The original install runs on the Unlimited plan, so nothing changes for it."""
from __future__ import annotations

from fastapi import HTTPException

from . import db, registry


def _bid() -> str:
    return db.current() or registry.default_id()


def plan() -> dict:
    return registry.plan_of(_bid())


def seats() -> dict:
    p = plan()
    used = registry.seats_used(_bid())
    return {"used": used, "limit": p["seats"], "left": None if p["seats"] is None else max(0, p["seats"] - used)}


def require_seat() -> None:
    s = seats()
    if s["limit"] is not None and s["used"] >= s["limit"]:
        raise HTTPException(409, f"Your {plan()['name']} plan allows {s['limit']} team members and all seats are in use. Deactivate someone, or ask the platform administrator for a bigger plan.")


def products() -> dict:
    p = plan()
    used = db.get("SELECT COUNT(*) n FROM products")["n"]
    return {"used": used, "limit": p["products"], "left": None if p["products"] is None else max(0, p["products"] - used)}


def require_product_room(adding: int = 1) -> None:
    s = products()
    if s["limit"] is not None and s["used"] + adding > s["limit"]:
        raise HTTPException(409, f"Your {plan()['name']} plan allows {s['limit']} products and you have {s['used']}. Remove some, or ask the platform administrator for a bigger plan.")


def ai() -> dict:
    """AI replies this month. Only replies written with the platform's key are limited; a business using its own key is never held back."""
    from . import aikey
    p = plan()
    used = registry.usage_get(_bid(), "ai_replies")
    limited = aikey.source() in ("platform", "environment")
    lim = p["ai_replies"] if limited else None
    return {"used": used, "limit": lim, "limited": limited, "exhausted": lim is not None and used >= lim, "planLimit": p["ai_replies"]}


def summary() -> dict:
    p = plan()
    return {"plan": {"id": p["id"], "name": p["name"], "platformAi": p["platform_ai"], "overridden": p["overridden"]}, "seats": seats(), "products": products(), "ai": ai(), "period": registry.period_now()}
