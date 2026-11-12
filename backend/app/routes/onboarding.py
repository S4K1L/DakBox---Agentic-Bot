"""The setup guide a new business sees: five steps (what you sell, products, a channel, the AI, a test message). Each step's state is read from the
business's real data, so it can never drift; only the skips ("just the website chat for now", "offline rules are fine") and hiding the guide are remembered."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import auth, db
from ..agent.agent import has_model
from ..agent.tools import agent_settings

router = APIRouter(prefix="/api/onboarding", dependencies=[Depends(auth.current_user)])

STEPS = ("about", "products", "channel", "ai", "test")
SKIPPABLE = ("channel", "ai")


def _state() -> dict:
    s = db.get_setting("onboarding", None) or {}
    return {"show": bool(s.get("show")), "dismissed": bool(s.get("dismissed")), "marks": [m for m in (s.get("marks") or []) if m in SKIPPABLE]}


def _view() -> dict:
    st = _state()
    real = {
        "about": bool((agent_settings().get("storeAbout") or "").strip()),
        "products": db.get("SELECT COUNT(*) n FROM products")["n"] > 0,
        "channel": db.get("SELECT COUNT(*) n FROM channels WHERE kind != 'web'")["n"] > 0,
        "ai": has_model(),
        "test": db.get("SELECT COUNT(*) n FROM messages WHERE role='assistant'")["n"] > 0,
    }
    steps = [{"id": k, "done": real[k] or k in st["marks"], "skipped": k in st["marks"] and not real[k]} for k in STEPS]
    n = len([x for x in steps if x["done"]])
    return {"show": st["show"] and not st["dismissed"], "dismissed": st["dismissed"], "steps": steps, "done": n, "total": len(STEPS), "complete": n == len(STEPS)}


@router.get("")
async def get_onboarding():
    return _view()


class Mark(BaseModel):
    step: str = Field(max_length=12)


@router.post("/skip")
async def skip(b: Mark, user: dict = Depends(auth.require("settings.write"))):
    """Count a step as handled without doing it (only the channel and AI steps can be skipped)."""
    if b.step not in SKIPPABLE:
        raise HTTPException(400, "That step cannot be skipped.")
    s = db.get_setting("onboarding", None) or {}
    s["marks"] = sorted(set(s.get("marks") or []) | {b.step})
    db.set_setting("onboarding", s)
    return _view()


@router.post("/dismiss")
async def dismiss(user: dict = Depends(auth.require("settings.write"))):
    s = db.get_setting("onboarding", None) or {}
    s["dismissed"] = True
    db.set_setting("onboarding", s)
    return _view()
