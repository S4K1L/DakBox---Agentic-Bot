"""Settings for the Meta app that owns the webhook: app ID, app secret, verify token, public URL."""
from __future__ import annotations

import os
import secrets as pysecrets

from . import db
from .secrets_store import mask, seal, unseal


def _row() -> dict:
    return db.get_setting("meta", {}) or {}


def app_id() -> str | None:
    return _row().get("app_id") or os.environ.get("META_APP_ID") or None


def app_secret() -> str | None:
    return unseal(_row().get("app_secret")) or os.environ.get("META_APP_SECRET") or None


def verify_token() -> str | None:
    return unseal(_row().get("verify_token")) or os.environ.get("META_VERIFY_TOKEN") or None


def public_url() -> str | None:
    u = _row().get("public_url") or os.environ.get("PUBLIC_URL") or None
    return u.rstrip("/") if u else None


def webhook_url() -> str:
    return f"{public_url() or 'https://YOUR-PUBLIC-URL'}/webhooks/meta"


def update(app_id_: str | None = None, app_secret_: str | None = None, verify_token_: str | None = None, public_url_: str | None = None) -> None:
    cur = _row()
    if app_id_ is not None:
        cur["app_id"] = app_id_.strip()
    if app_secret_:
        cur["app_secret"] = seal(app_secret_.strip())
    if verify_token_:
        cur["verify_token"] = seal(verify_token_.strip())
    if public_url_ is not None:
        cur["public_url"] = public_url_.strip().rstrip("/")
    db.set_setting("meta", cur)


def new_verify_token() -> str:
    return pysecrets.token_urlsafe(24)


def view(reveal_verify_token: bool = False) -> dict:
    return {
        "appId": app_id(), "appSecretSet": bool(app_secret()), "appSecretHint": mask(app_secret()),
        "verifyTokenSet": bool(verify_token()), "verifyToken": verify_token() if reveal_verify_token else None,
        "publicUrl": public_url(), "webhookUrl": webhook_url(),
        "graphVersion": os.environ.get("META_GRAPH_VERSION", "v26.0"),
    }
