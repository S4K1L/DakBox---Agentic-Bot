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

from . import aikey, db, hosting
from .agent.agent import has_model  # noqa: E402
from .domain import HttpError  # noqa: E402
from .routes import api, auth as auth_routes, business as business_routes, catalog as catalog_routes, meta as meta_routes, onboarding as onboarding_routes, pay_public, platform as platform_routes, providers as provider_routes, shop_orders as shop_order_routes, webchat, webhooks  # noqa: E402
from .seed import seed_if_empty  # noqa: E402

hosting.enforce()                                       # a hosted install refuses to start when a protection is missing
seed_if_empty()

PROD = os.environ.get("DAKBOX_ENV") == "production" or db.hosted()
app = FastAPI(title="Dakbox", version="0.1.0", docs_url=None if PROD else "/api/docs", openapi_url=None if PROD else "/api/openapi.json")
# Sessions use a bearer token (no cookies), so CORS is not a login boundary, but still keep it tight in production:
# the app is served from the same origin, so nothing else needs access unless DAKBOX_ORIGINS lists it.
_origins = [o.strip() for o in os.environ.get("DAKBOX_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_origins if PROD else ["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(auth_routes.router)
app.include_router(meta_routes.router)
app.include_router(provider_routes.router)
app.include_router(catalog_routes.router)
app.include_router(onboarding_routes.router)
app.include_router(business_routes.router)
app.include_router(platform_routes.router)
app.include_router(platform_routes.downloads)
app.include_router(pay_public.router)
app.include_router(api.router)
app.include_router(webhooks.router)
app.include_router(shop_order_routes.router)
app.include_router(webchat.router)


@app.exception_handler(HttpError)
async def http_error(_: Request, e: HttpError):
    return JSONResponse({"error": e.message, "detail": e.message}, status_code=e.status)


async def _recheck_channels() -> None:
    """Every 6 hours, re-verify live channels so an expiring or revoked token shows up before customers notice."""
    import asyncio
    from . import jobs
    while True:
        await asyncio.sleep(6 * 3600)
        await jobs.recheck_channels()


async def _poll_couriers() -> None:
    """Every 20 minutes, ask couriers about parcels still on the way (so orders move even if no webhook arrives)."""
    import asyncio
    from . import jobs
    while True:
        await asyncio.sleep(20 * 60)
        await jobs.poll_couriers()


async def _sms_loop() -> None:
    """Every minute: send messages whose quiet hours are over, and collect delivery reports where the provider has them."""
    import asyncio
    from . import jobs
    while True:
        await asyncio.sleep(60)
        await jobs.sms_tick()


async def _catalog_loop() -> None:
    """Every 6 hours: re-read each connected website so prices and stock follow the shop."""
    import asyncio
    from . import jobs
    while True:
        await asyncio.sleep(6 * 3600)
        await jobs.sync_catalogs()


async def _backup_loop() -> None:
    """Daily (DAKBOX_BACKUP_EVERY_HOURS, default 24 on a hosted install, off otherwise): back up, verify, prune, remember how it went."""
    import asyncio
    from . import backups
    hours = float(os.environ.get("DAKBOX_BACKUP_EVERY_HOURS") or (24 if db.hosted() else 0))
    if hours <= 0:
        return
    await asyncio.sleep(120)                           # first one shortly after start-up, then on the schedule
    while True:
        r = await asyncio.to_thread(backups.run_scheduled)
        print(f"[backup] {'ok ' + r.get('name', '') if r['ok'] else 'FAILED ' + str(r.get('problems'))}")
        await asyncio.sleep(hours * 3600)


@app.get("/healthz")
async def healthz():
    """For load balancers and uptime monitors: 200 when the server can read its registry, 503 otherwise. Says nothing about any business."""
    from . import registry
    try:
        registry._c().execute("SELECT 1").fetchone()
        return {"ok": True}
    except Exception:  # noqa: BLE001
        return JSONResponse({"ok": False}, status_code=503)


@app.on_event("startup")
async def banner() -> None:
    import asyncio
    app.state.recheck = asyncio.create_task(_recheck_channels())
    app.state.courier_poll = asyncio.create_task(_poll_couriers())
    app.state.sms_loop = asyncio.create_task(_sms_loop())
    app.state.catalog_loop = asyncio.create_task(_catalog_loop())
    app.state.backup_loop = asyncio.create_task(_backup_loop())
    from . import registry, secrets_store
    n = secrets_store.rekey_all()                       # secrets saved before each business had its own key are moved under it (repeatable, only touches old values)
    if n:
        print(f"[secrets] re-encrypted {n} stored secrets under per-business keys")
    print(f"Businesses: {len(registry.all_businesses())} (registry at {registry.REGISTRY_PATH.name})")
    print(f"Dakbox API ready · assistant engine: {aikey.engine_label() + ' (' + str(aikey.model()) + ')' if has_model() else 'offline rules (add an AI key under Assistant, Engine and key)'}")


# One server in production: serve the built Flutter web app from the same origin (run ./build_web.sh first).
_web = Path(__file__).resolve().parent.parent.parent / "app" / "build" / "web"
if _web.exists():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=_web, html=True), name="web")
