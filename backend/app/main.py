from __future__ import annotations

import os
from pathlib import Path


def _load_env() -> None:
    """Read backend/.env or the repo's .env without a dependency."""
    here = Path(__file__).resolve().parent.parent
    for f in (here / ".env", here.parent / ".env"):
        if f.exists():
            for line in f.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip("'\""))


_load_env()

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

from .agent.agent import MODEL, has_model  # noqa: E402
from .domain import HttpError  # noqa: E402
from .routes import api, auth as auth_routes, meta as meta_routes, pay_public, providers as provider_routes, webchat, webhooks  # noqa: E402
from .seed import seed_if_empty  # noqa: E402

seed_if_empty()

PROD = os.environ.get("DAKBOX_ENV") == "production"
app = FastAPI(title="Dakbox", version="0.1.0", docs_url=None if PROD else "/api/docs", openapi_url=None if PROD else "/api/openapi.json")
# Sessions use a bearer token (no cookies), so CORS is not a login boundary, but still keep it tight in production:
# the app is served from the same origin, so nothing else needs access unless DAKBOX_ORIGINS lists it.
_origins = [o.strip() for o in os.environ.get("DAKBOX_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_origins if PROD else ["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(auth_routes.router)
app.include_router(meta_routes.router)
app.include_router(provider_routes.router)
app.include_router(pay_public.router)
app.include_router(api.router)
app.include_router(webhooks.router)
app.include_router(webchat.router)


@app.exception_handler(HttpError)
async def http_error(_: Request, e: HttpError):
    return JSONResponse({"error": e.message, "detail": e.message}, status_code=e.status)


async def _recheck_channels() -> None:
    """Every 6 hours, re-verify live channels so an expiring or revoked token shows up before customers notice."""
    import asyncio
    from . import db, meta
    while True:
        await asyncio.sleep(6 * 3600)
        for c in db.all("SELECT * FROM channels WHERE live=1 AND status != 'off'"):
            try:
                await meta.check_channel(c)
            except Exception as e:
                print("[recheck]", repr(e))


async def _poll_couriers() -> None:
    """Every 20 minutes, ask couriers about parcels still on the way (so orders move even if no webhook arrives)."""
    import asyncio
    from . import couriers
    while True:
        await asyncio.sleep(20 * 60)
        try:
            await couriers.poll_all()
        except Exception as e:
            print("[couriers]", repr(e))


async def _sms_loop() -> None:
    """Every minute: send messages whose quiet hours are over, and collect delivery reports where the provider has them."""
    import asyncio
    from . import sms
    while True:
        await asyncio.sleep(60)
        try:
            await sms.process_due()
            await sms.poll_reports()
        except Exception as e:
            print("[sms]", repr(e))


@app.on_event("startup")
async def banner() -> None:
    import asyncio
    app.state.recheck = asyncio.create_task(_recheck_channels())
    app.state.courier_poll = asyncio.create_task(_poll_couriers())
    app.state.sms_loop = asyncio.create_task(_sms_loop())
    print(f"Dakbox API ready · assistant engine: {'Claude (' + MODEL + ')' if has_model() else 'offline rules (set ANTHROPIC_API_KEY for Claude)'}")


# One server in production: serve the built Flutter web app from the same origin (run ./build_web.sh first).
_web = Path(__file__).resolve().parent.parent.parent / "app" / "build" / "web"
if _web.exists():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=_web, html=True), name="web")
