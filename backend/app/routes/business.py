"""The business owner's own panel: their business's profile, plan and use, and a copy of their data. (Their team is under /api/team.)
Everything here works on the business the session is in; nothing takes a business name from the request."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import auth, db, export, limits, registry

router = APIRouter(prefix="/api/business", dependencies=[Depends(auth.current_user)])


def _view(user: dict) -> dict:
    b = registry.resolve(user["business"]["id"])
    owners = [m for m in registry.members_of(b["id"]) if m["role"] == "owner" and m["member_active"]]
    members = [m for m in registry.members_of(b["id"]) if m["member_active"]]
    return {"id": b["id"], "slug": b["slug"], "name": b["name"], "status": b["status"], "createdAt": b["created_at"], "yourRole": user["role"], "canEdit": user["role"] == "owner",
            "owners": [m["name"] for m in owners], "people": len(members), **limits.summary()}


@router.get("")
async def get_business(user: dict = Depends(auth.current_user)):
    return _view(user)


class RenameBody(BaseModel):
    name: str = Field(min_length=2, max_length=80)


@router.patch("")
async def rename_business(b: RenameBody, user: dict = Depends(auth.current_user)):
    """Only an owner changes the business's name. (Its address, plan and status belong to the super administrator.)"""
    if user["role"] != "owner":
        raise HTTPException(403, "Only an owner can change the business details.")
    try:
        registry.rename(user["business"]["id"], b.name)
    except registry.RegistryError as e:
        raise HTTPException(400, str(e)) from None
    auth.audit("business.rename", None, b.name, actor=user)
    user = {**user, "business": {**user["business"], "name": " ".join(b.name.split())}}
    return _view(user)


@router.post("/export")
async def export_own_data(user: dict = Depends(auth.current_user)):
    """A copy of the business's data (one CSV per table, secrets left out) as a one-time download link. Owners only."""
    if user["role"] != "owner":
        raise HTTPException(403, "Only an owner can download the business data.")
    data, name = await asyncio.to_thread(export.build, user["business"]["id"])
    auth.audit("business.export", None, f"{len(data)} bytes", actor=user)
    return {"url": f"/api/platform/download/{export.make_link(data, name)}", "filename": name, "bytes": len(data)}
