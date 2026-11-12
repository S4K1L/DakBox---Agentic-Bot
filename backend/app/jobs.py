"""Background jobs across businesses.

Each timer walks the active businesses and runs its work inside that business (its own database, settings and keys). A business that is
slow or broken never delays or stops the others: every one gets its own time limit and its errors are caught and printed with its address name.
"""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from . import db, registry

LAST: dict[str, dict] = {}                  # what each timer's last pass did, shown on the platform health page
PER_BUSINESS_TIMEOUT = 300.0
CONCURRENCY = 4


async def for_each_business(label: str, fn: Callable[[], Awaitable[None]], *, timeout: float | None = None) -> dict:
    """Run `fn` once for every active business. Returns {"ok": [...slugs], "failed": {slug: reason}} (also useful in tests)."""
    result: dict = {"ok": [], "failed": {}}
    sem = asyncio.Semaphore(CONCURRENCY)
    limit = timeout if timeout is not None else PER_BUSINESS_TIMEOUT

    async def one(b) -> None:
        async with sem:
            try:
                with db.business(b["id"]):
                    await asyncio.wait_for(fn(), limit)
                result["ok"].append(b["slug"])
            except asyncio.TimeoutError:
                result["failed"][b["slug"]] = "timed out"
                print(f"[{label}:{b['slug']}] timed out")
            except Exception as e:  # noqa: BLE001 - one business must never stop the others
                result["failed"][b["slug"]] = type(e).__name__
                print(f"[{label}:{b['slug']}]", repr(e))

    await asyncio.gather(*(one(b) for b in registry.all_businesses() if b["status"] != "suspended"))
    LAST[label] = {"at": registry._now(), "ok": len(result["ok"]), "failed": dict(result["failed"])}
    return result


# ---------------------------------------------------------------- the timers' work (each is one pass over every business)
async def recheck_channels() -> dict:
    from . import meta

    async def work() -> None:
        for c in db.all("SELECT * FROM channels WHERE live=1 AND status != 'off'"):
            try:
                await meta.check_channel(c)
            except Exception as e:  # noqa: BLE001
                print("[recheck]", repr(e))
    return await for_each_business("recheck", work)


async def poll_couriers() -> dict:
    from . import couriers
    return await for_each_business("couriers", couriers.poll_all)


async def sms_tick() -> dict:
    from . import sms

    async def work() -> None:
        await sms.process_due()
        await sms.poll_reports()
    return await for_each_business("sms", work)


async def sync_catalogs() -> dict:
    from . import catalog_import
    return await for_each_business("catalog", catalog_import.sync_all)
