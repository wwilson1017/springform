"""In-turn clearing (agent.md §5, "Result cap and in-turn clearing").

Past `CLEAR_AT_TOKENS` of input on this turn's last model call, every tool result the model has
already seen becomes one `CLEARED` line, except the newest `KEEP_RESULTS`. Only the in-memory
messages change; the stored runs stay whole. Results the model has not seen yet (after the last
assistant message) are never cleared, nor small ones (a write's `{"id": 5}` is worth its space).
`errors` calls `shrink(force=True)` on a context overflow.
"""

from __future__ import annotations

from backend.core.agent import turn_hooks
from backend.core.agent.providers.windows import cache_inclusive_input_tokens

CLEAR_AT_TOKENS = 100_000
KEEP_RESULTS = 3
MIN_CLEAR_CHARS = 500
CLEARED = "[Result cleared to save context. If you still need it, run the read again; never repeat a write.]"

# simplification: the reading is this turn's last call only, and each round past the mark clears one
# more result, which re-writes a few messages of prompt cache; upgrade: clear in batches.


def _results(messages: list[dict]) -> list[tuple[int, int | None]]:
    """(message index, block index or None) of every tool result, oldest first: a `tool_result`
    block in a user message (Anthropic, FakeProvider) or a `role: tool` message (OpenAI)."""
    out: list[tuple[int, int | None]] = []
    for i, m in enumerate(messages):
        if m.get("role") == "tool":
            out.append((i, None))
        elif m.get("role") == "user" and isinstance(m.get("content"), list):
            out += [
                (i, j) for j, b in enumerate(m["content"]) if isinstance(b, dict) and b.get("type") == "tool_result"
            ]
    return out


def cleared(messages: list[dict]) -> tuple[list[dict], int]:
    """A copy of `messages` with the older seen results cleared, and how many were. Assistant
    messages are never touched (Anthropic's are SDK objects replayed as they came)."""
    last_assistant = max((i for i, m in enumerate(messages) if m.get("role") == "assistant"), default=-1)
    results = _results(messages)
    seen = [r for r in results if r[0] < last_assistant]
    keep = max(0, KEEP_RESULTS - (len(results) - len(seen)))
    out, count = list(messages), 0
    for i, j in seen[: max(0, len(seen) - keep)]:
        m = out[i]
        content = m["content"] if j is None else m["content"][j].get("content")
        if not isinstance(content, str) or content == CLEARED or len(content) <= MIN_CLEAR_CHARS:
            continue
        if j is None:
            out[i] = {**m, "content": CLEARED}
        else:
            blocks = list(m["content"])
            blocks[j] = {**blocks[j], "content": CLEARED}
            out[i] = {**m, "content": blocks}
        count += 1
    return out, count


def shrink(state, *, force: bool = False) -> int:
    """Clear when forced or past the mark; how many results were cleared."""
    if not force and (cache_inclusive_input_tokens(state.usage) or 0) <= CLEAR_AT_TOKENS:
        return 0
    state.messages, count = cleared(state.messages)
    return count


def before_model_call(state) -> None:
    shrink(state)


turn_hooks.register("before_model_call", before_model_call)
