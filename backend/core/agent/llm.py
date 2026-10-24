"""One-shot completions for other packages (the memory observer, summaries).

    complete(system, prompt, *, tier="light", max_tokens=1024) -> str      # sync, for jobs and threads
    acomplete(system, prompt, *, tier="light", max_tokens=1024) -> str     # same, from async code

Both raise NoProviderConfigured with zero keys and ProviderError when the provider fails. Never
call them inside `transaction()`: a model call must not hold the write lock. On current Claude
models thinking counts against `max_tokens`, so leave headroom for anything longer than a line.
"""

from __future__ import annotations

import asyncio

from backend.core import db
from backend.core.agent.providers import NoProviderConfigured, ProviderError, collect_text, get_provider

__all__ = ["NoProviderConfigured", "ProviderError", "acomplete", "complete"]


async def acomplete(system: str, prompt: str, *, tier: str = "light", max_tokens: int = 1024) -> str:
    provider = await asyncio.to_thread(get_provider, tier=tier)
    if provider is None:
        raise NoProviderConfigured("No AI provider is configured; add a key in Settings → AI.")
    return await collect_text(provider.stream_turn([{"role": "user", "content": prompt}], [], system, max_tokens=max_tokens))


def complete(system: str, prompt: str, *, tier: str = "light", max_tokens: int = 1024) -> str:
    if db.in_transaction():
        raise RuntimeError("llm.complete called inside transaction(); call the model before or after the write")
    return asyncio.run(acomplete(system, prompt, tier=tier, max_tokens=max_tokens))
