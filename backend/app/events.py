"""In-process pub/sub that feeds the /api/events server-sent-events stream."""
from __future__ import annotations

import asyncio
from typing import Any

_subs: set[asyncio.Queue] = set()


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _subs.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    _subs.discard(q)


def emit(type_: str, **data: Any) -> None:
    ev = {"type": type_, **data}
    for q in list(_subs):
        try:
            q.put_nowait(ev)
        except asyncio.QueueFull:
            pass
