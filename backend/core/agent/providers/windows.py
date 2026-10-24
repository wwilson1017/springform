"""Context-window sizes and the `usage` SSE payload (lifted from CakeCRM `providers/windows.py`).

Exact model id first, then the longest prefix, so dated snapshots resolve to their base model.
Unknown models return None: the meter hides rather than guess.
"""

from __future__ import annotations

MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    "claude-fable-5-1": 1_000_000,
    "claude-opus-5-5": 1_000_000,
    "claude-sonnet-5-5": 1_000_000,
    "claude-haiku-5-5": 1_000_000,
    "claude-opus-4-8": 1_000_000,
    "claude-haiku-4-5": 200_000,
}


def get_context_window(model: str) -> int | None:
    if not model:
        return None
    if model in MODEL_CONTEXT_WINDOWS:
        return MODEL_CONTEXT_WINDOWS[model]
    prefixes = [k for k in MODEL_CONTEXT_WINDOWS if model.startswith(k)]
    return MODEL_CONTEXT_WINDOWS[max(prefixes, key=len)] if prefixes else None


def cache_inclusive_input_tokens(usage: dict) -> int | None:
    """Input tokens the model actually read (plain + cache writes + cache reads), or None.
    With prompt caching most of the input lives in the cache fields, so this is the honest
    measure of how full the context is."""
    if not usage:
        return None
    total = (
        (usage.get("input_tokens") or 0)
        + (usage.get("cache_creation_input_tokens") or 0)
        + (usage.get("cache_read_input_tokens") or 0)
    )
    return total if total > 0 else None


def context_usage_event(usage: dict, context_window: int | None, meter_only: bool = False) -> dict | None:
    """The `usage` event, or None when the meter cannot be shown. `meter_only` zeroes the raw
    counts for the confirmation wrap-up turn so a client summing them does not double count."""
    if context_window is None:
        return None
    context_tokens = cache_inclusive_input_tokens(usage)
    if context_tokens is None:
        return None
    return {
        "type": "usage",
        "input_tokens": 0 if meter_only else (usage.get("input_tokens") or 0),
        "output_tokens": 0 if meter_only else (usage.get("output_tokens") or 0),
        "context_tokens": context_tokens,
        "context_window": context_window,
    }
