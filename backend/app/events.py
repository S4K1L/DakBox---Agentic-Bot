"""In-process pub/sub that feeds the /api/events server-sent-events stream."""
from __future__ import annotations

import asyncio
from typing import Any

_subs: dict[str, set[asyncio.Queue]] = {}      # business id -> the open streams of people working in that business
_owner: dict[int, str] = {}


def _bid(bid: str | None) -> str | None:
    if bid:
        return bid
    from . import db, registry
    return None if db.strict() else registry.default_id()


def subscribe(bid: str | None = None) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    b = _bid(bid)
    if b:
        _subs.setdefault(b, set()).add(q)
        _owner[id(q)] = b
    return q


def unsubscribe(q: asyncio.Queue, bid: str | None = None) -> None:
    b = _owner.pop(id(q), None)
    if b and b in _subs:
        _subs[b].discard(q)
        if not _subs[b]:
            _subs.pop(b, None)


def emit(type_: str, **data: Any) -> None:
    """Tell the people working in the CURRENT business that something changed. Never reaches another business."""
    from . import db
    b = _bid(db.current())
    if not b:
        return
    ev = {"type": type_, **data}
    for q in list(_subs.get(b, ())):
        try:
            q.put_nowait(ev)
        except asyncio.QueueFull:
            pass
