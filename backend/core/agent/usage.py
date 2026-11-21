"""The usage ledger (`core_agent_usage`, agent.md §5 "Usage ledger"): one row per completed model call.

Every model call streams through `metered(...)`: the turn loop, `llm.acomplete` (compaction, the
nightly observer, apps) and the provider test. It records the call just before passing its
`_turn_complete` event on, because every consumer stops reading at that event. The row names the
provider object that made the call, so a mid-turn fallback records the model that answered. A call
that sends several requests (Anthropic resuming a paused web search) reports each earlier one as a
`_usage` event, so each request gets its own row. A failed request (no usage) writes nothing; a call
cancelled before it completes is not seen.

Cost is fixed at write time from the `agent.cost_rates` setting: USD per million tokens per model,
so tokens x rate is micro-dollars. A model with no rate is stored with `cost_micros NULL`. Editing a
rate changes later rows only. A ledger failure is logged and never fails the call it measures.
"""

from __future__ import annotations

import logging
import math
from collections.abc import AsyncIterator
from datetime import timedelta

from backend.core import clock, db, localtime, settings
from backend.core.agent.aio import in_thread
from backend.core.agent.providers.base import AIProvider

logger = logging.getLogger(__name__)

RATES_SETTING = "agent.cost_rates"
FIELDS = ("input", "output", "cache_read", "cache_write")
MAX_RATE = 10_000  # USD per million tokens: far above any list price, so a typo is caught
MAX_MODELS = 200
# List prices, USD per million tokens, as of 2026-11: estimates for the models the providers
# default to (credentials.DEFAULT_MODELS) plus the other current Claude tiers. Cache write is the
# 5-minute write; OpenAI has no write charge.
DEFAULT_RATES: dict[str, dict[str, float]] = {
    "claude-fable-5-2": {"input": 8.0, "output": 40.0, "cache_read": 0.2, "cache_write": 10.0},
    "claude-opus-5-5": {"input": 4.0, "output": 20.0, "cache_read": 0.2, "cache_write": 5.0},
    "claude-sonnet-5-5": {"input": 2.0, "output": 10.0, "cache_read": 0.1, "cache_write": 2.5},
    "claude-haiku-5-5": {"input": 0.1, "output": 0.5, "cache_read": 0.01, "cache_write": 0.125},
    "gpt-5.5": {"input": 5.0, "output": 30.0, "cache_read": 0.5, "cache_write": 0.0},
    "gpt-5.4-nano": {"input": 0.2, "output": 1.25, "cache_read": 0.02, "cache_write": 0.0},
}


def check_rates(value: object) -> dict[str, dict[str, float]]:
    """The `Key.check` for `agent.cost_rates`: {model: {field: USD per million}}; missing fields are 0."""
    if not isinstance(value, dict) or len(value) > MAX_MODELS:
        raise ValueError(f"must be a mapping of up to {MAX_MODELS} model names to rates")
    out: dict[str, dict[str, float]] = {}
    for model, rate in value.items():
        if not isinstance(model, str) or not model.strip() or len(model) > 100:
            raise ValueError("model names must be text of 1 to 100 characters")
        if not isinstance(rate, dict) or set(rate) - set(FIELDS):
            raise ValueError(f"{model}: rates take only {', '.join(FIELDS)}")
        for f, v in rate.items():
            if isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v) or not 0 <= v <= MAX_RATE:
                raise ValueError(f"{model} {f}: must be a number from 0 to {MAX_RATE}")
        out[model.strip()] = {f: float(rate.get(f, 0)) for f in FIELDS}
    return out


def tokens(usage: dict) -> dict[str, int]:
    """A provider's usage dict as the ledger's four counts (input excludes cached tokens)."""
    return {
        "input": usage.get("input_tokens") or 0,
        "output": usage.get("output_tokens") or 0,
        "cache_read": usage.get("cache_read_input_tokens") or 0,
        "cache_write": usage.get("cache_creation_input_tokens") or 0,
    }


def cost_micros(model: str, counts: dict[str, int], rates: dict) -> int | None:
    """Micro-dollars at the model's rate (exact name match), or None when it has none."""
    rate = rates.get(model)
    return None if rate is None else round(sum(counts[f] * rate.get(f, 0) for f in FIELDS))


def record_in(conn: db.Conn, source: str, provider: str, model: str, usage: dict, conversation_id: int | None) -> None:
    counts = tokens(usage)
    rates = settings.get_setting(RATES_SETTING, DEFAULT_RATES) or {}
    conn.execute(
        """INSERT INTO core_agent_usage (at, user_id, source, conversation_id, provider, model,
               input_tokens, output_tokens, cache_read, cache_write, cost_micros)
           VALUES (?, (SELECT user_id FROM core_agent_conversations WHERE id = ?), ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            clock.now_iso(),
            conversation_id,
            source,
            conversation_id,
            provider,
            model,
            counts["input"],
            counts["output"],
            counts["cache_read"],
            counts["cache_write"],
            cost_micros(model, counts, rates),
        ),
    )


def record(source: str, provider: str, model: str, usage: dict, conversation_id: int | None = None) -> None:
    """One ledger row in its own transaction; a failure is logged, never raised."""
    try:
        with db.transaction() as conn:
            record_in(conn, source, provider, model, usage, conversation_id)
    except Exception:
        logger.warning("could not record model usage (%s, %s)", source, model, exc_info=True)


async def metered(
    stream: AsyncIterator[dict], provider: AIProvider, source: str, conversation_id: int | None = None
) -> AsyncIterator[dict]:
    """`stream` minus its `_usage` events, recording one row per request: each `_usage` (a request before
    the last, as when Anthropic resumes a paused reply) and the `_turn_complete` that carries usage."""
    async for event in stream:
        if event.get("type") in ("_usage", "_turn_complete") and event.get("usage"):
            await in_thread(record, source, provider.provider_name, provider.model, event["usage"], conversation_id)
        if event.get("type") != "_usage":
            yield event


def month_summary() -> dict:
    """This local month's usage by source and model, the total cost and the cache hit rate."""
    start = localtime.now_local().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = (start + timedelta(days=32)).replace(day=1)
    rows = db.rows(
        """SELECT source, model, count(*) AS calls, sum(input_tokens) AS input_tokens,
                  sum(output_tokens) AS output_tokens, sum(cache_read) AS cache_read,
                  sum(cache_write) AS cache_write, coalesce(sum(cost_micros), 0) AS cost_micros,
                  sum(cost_micros IS NULL) AS unpriced
           FROM core_agent_usage WHERE at >= ? AND at < ?
           GROUP BY source, model ORDER BY cost_micros DESC, source, model""",
        (clock.to_iso(start), clock.to_iso(end)),
    )
    read = sum(r["cache_read"] for r in rows)
    all_input = sum(r["input_tokens"] + r["cache_read"] + r["cache_write"] for r in rows)
    return {
        "month": start.strftime("%Y-%m"),
        "rows": rows,
        "cost_micros": sum(r["cost_micros"] for r in rows),
        "cache_hit_rate": read / all_input if all_input else None,
    }
