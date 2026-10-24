"""In-process rate limits for the MCP endpoint (lifted from todo-gtd `backend/ratelimit.py`).

One process serves the install (`platform.md`), so an in-memory counter is the whole truth. Keys
are any string: a link id for the call limit, the client address for wrong-token misses (behind
the proxy, uvicorn's proxy headers make `request.client` the real client; `auth.md` §8).
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict

# Above this many tracked keys, whole expired buckets are dropped, so a flood from ever-new
# addresses cannot grow the dict without bound. At the hard cap the least recently touched
# bucket is evicted to admit the newcomer.
_SWEEP_AT = 256
_MAX_TRACKED = 10_000

_limiters: list[RateLimiter] = []


def clear_all() -> None:
    """Empty every limiter (tests)."""
    for limiter in _limiters:
        limiter.clear()


class RateLimiter:
    """At most `max_hits` per `window` seconds per key."""

    def __init__(self, window: int, max_hits: int):
        self.window = window
        self.max_hits = max_hits
        self.hits: OrderedDict[str, list[float]] = OrderedDict()  # an LRU: eviction is popitem(last=False)
        self._last_sweep = 0.0
        self._lock = threading.Lock()
        _limiters.append(self)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            if len(self.hits) > _SWEEP_AT and now - self._last_sweep >= 1.0:
                self._last_sweep = now
                for stale in [k for k, v in self.hits.items() if not v or now - v[-1] >= self.window]:
                    del self.hits[stale]
            if key not in self.hits and len(self.hits) >= _MAX_TRACKED:
                self.hits.popitem(last=False)
            self.hits[key] = [t for t in self.hits.get(key, []) if now - t < self.window]
            self.hits.move_to_end(key)
            if len(self.hits[key]) >= self.max_hits:
                return False
            self.hits[key].append(now)
            return True

    def clear(self) -> None:
        with self._lock:
            self.hits.clear()
