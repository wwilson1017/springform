"""`in_thread`: `asyncio.to_thread` that a cancel waits out.

A worker thread cannot be stopped. When a turn is cancelled (Stop, shutdown) while one of its
database calls runs in a thread, `in_thread` lets that call finish before the cancel goes on,
so a stopped turn never leaves a statement running behind it and shutdown can close the
database once every turn task has ended (scheduler.md §4).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any


async def in_thread(fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
    work = asyncio.ensure_future(asyncio.to_thread(fn, *args, **kwargs))
    try:
        return await asyncio.shield(work)
    except asyncio.CancelledError:
        await asyncio.wait([work])
        if not work.cancelled():
            work.exception()  # retrieved: the cancel wins, the thread's error is not news
        raise
