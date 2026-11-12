"""Rate limits per business, so one business (or one bot hammering its public addresses) cannot starve the others on a shared server.

Sliding window, in memory, keyed by (scope, business). Limits are per minute and can be tuned with environment variables:
  DAKBOX_API_RATE   signed-in requests per business per minute   (default 3000)
  DAKBOX_DOOR_RATE  public-address requests per business per minute: webhooks, payment callbacks, website chat   (default 600)
Setting one to 0 switches that limit off."""
from __future__ import annotations

import os
import time
from collections import deque

from fastapi import HTTPException

DEFAULTS = {"api": 3000, "door": 600}
ENV = {"api": "DAKBOX_API_RATE", "door": "DAKBOX_DOOR_RATE"}
WINDOW = 60.0
_hits: dict[tuple[str, str], deque] = {}


def limit_for(scope: str) -> int:
    v = os.environ.get(ENV[scope])
    try:
        return int(v) if v not in (None, "") else DEFAULTS[scope]
    except ValueError:
        return DEFAULTS[scope]


def check(scope: str, business_id: str) -> None:
    """Count one request; raise 429 when this business is over its limit for this minute."""
    lim = limit_for(scope)
    if lim <= 0:
        return
    now = time.monotonic()
    q = _hits.setdefault((scope, business_id), deque())
    while q and now - q[0] > WINDOW:
        q.popleft()
    if len(q) >= lim:
        wait = max(1, int(WINDOW - (now - q[0])) + 1)
        raise HTTPException(429, f"Too many requests for this business. Try again in {wait} seconds.", headers={"Retry-After": str(wait)})
    q.append(now)


def reset() -> None:
    _hits.clear()
