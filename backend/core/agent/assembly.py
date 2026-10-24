"""Server-side context assembly (ported from CakeCRM `assistant/assembly.py`).

Rebuilds the provider `messages` for a turn from the database, so context is built and kept
server-side rather than trusted from a client transcript:

    user row                        -> {"role": "user", "content": text}
    assistant row, no tool calls    -> {"role": "assistant", "content": text}
    assistant row, with tool calls  -> provider.build_tool_turn(text, calls, results from tool runs)

After a compaction the aged middle is replaced by the stored gist, folded onto the first kept
user row. One oversized row is cut for the live context only (storage stays whole), re-closing
any fence the cut leaves open.

The memory seam: when `backend.core.memory` is installed, `memory_context()` asks it for this
turn's block and fences it as untrusted; `after_turn()` lets it look at the finished turn.
"""

from __future__ import annotations

import json
import logging
import re

from backend.core import db
from backend.core.agent import agents, delimiters, history
from backend.core.auth.deps import User

try:
    from backend.core import memory as _memory
except ImportError:
    _memory = None

logger = logging.getLogger(__name__)

CHARS_PER_TOKEN = 4
DEFAULT_BUDGET_TOKENS = 128_000
HEAD_ROWS = 2  # the opening exchange, kept verbatim across every compaction
_OVERSIZED_ROW_FRACTION = 0.25
_TRUNCATION_MARKER = "\n…[truncated]"
_FENCE_OPEN_RE = re.compile(rf'<({delimiters.UNTRUSTED_EXTERNAL_TAG}|{delimiters.CONVERSATION_SUMMARY_TAG}) id=(\\?)"([0-9a-f]+)\2"')


def _truncate(text, limit: int):
    """Cut `text` to `limit` for the live context, re-closing any fence the cut left open (a
    fence nested in a JSON string has escaped quotes, so the close is spelled the same way)."""
    if not isinstance(text, str) or len(text) <= limit:
        return text
    cut = text[:limit]
    closes = [f'</{tag} id={esc}"{nonce}{esc}">' for tag, esc, nonce in _FENCE_OPEN_RE.findall(cut)]
    return "\n".join([cut + _TRUNCATION_MARKER] + [c for c in closes if c not in cut])


def apply_compaction(rows: list[dict], summary: str | None, first_kept_id: int | None) -> list[dict]:
    """Head verbatim, the gist folded onto the first kept user row, tail verbatim."""
    if not summary or first_kept_id is None or len(rows) <= HEAD_ROWS or first_kept_id <= rows[HEAD_ROWS - 1]["id"]:
        return rows
    tail = [r for r in rows if r["id"] >= first_kept_id]
    if not tail:
        return rows
    first = tail[0]
    if first["role"] == "user":
        merged = {**first, "content": {**first["content"], "text": summary + "\n\n" + first["content"].get("text", "")}}
        return rows[:HEAD_ROWS] + [merged] + tail[1:]
    # The boundary always snaps to a user row; a standalone gist keeps a hand-edited one usable.
    return rows[:HEAD_ROWS] + [{"id": first_kept_id, "role": "user", "content": {"text": summary}}] + tail


def assemble_messages(provider, conversation_id: int) -> list[dict]:
    """The provider messages for this conversation; [] when it has none. The caller saved the
    new user row first, so the result ends on the latest user turn."""
    state = history.compaction_state(conversation_id) or {}
    rows = apply_compaction(history.messages(conversation_id), state.get("summary"), state.get("summary_first_kept_id"))
    runs: dict[int, dict[str, dict]] = {}
    for run in history.tool_runs_for(conversation_id):
        if run["message_id"] is not None:
            runs.setdefault(run["message_id"], {})[run["tool_use_id"]] = run
    limit = int(_OVERSIZED_ROW_FRACTION * (getattr(provider, "context_window", None) or DEFAULT_BUDGET_TOKENS) * CHARS_PER_TOKEN)
    out: list[dict] = []
    for row in rows:
        text = _truncate(row["content"].get("text") or "", limit)
        calls = row["content"].get("tool_calls")
        if row["role"] == "user":
            out.append({"role": "user", "content": text})
        elif not calls:
            if text:
                out.append({"role": "assistant", "content": text})
        else:
            by_id = runs.get(row["id"], {})
            results = [
                {"tool_use_id": c["tool_use_id"], "tool_name": c["tool"], "content": _truncate(history.model_content(by_id[c["tool_use_id"]]), limit)}
                for c in calls if c["tool_use_id"] in by_id
            ]
            bounded = [{**c, "args": c["args"] if len(json.dumps(c["args"], default=str)) <= limit else {"truncated": True}} for c in calls]
            out.extend(provider.build_tool_turn(text, bounded, results))
    return _coalesce(out)


def _coalesce(messages: list[dict]) -> list[dict]:
    """Merge consecutive same-role user/assistant messages (Anthropic needs strict alternation).
    Never merge a message carrying OpenAI's top-level tool_calls: that would orphan its results."""
    out: list[dict] = []
    for m in messages:
        if out and m["role"] in ("user", "assistant") and out[-1]["role"] == m["role"] and "tool_calls" not in m and "tool_calls" not in out[-1]:
            out[-1] = {**out[-1], "content": _merge(out[-1].get("content"), m.get("content"))}
        else:
            out.append(dict(m))
    return out


def _merge(a, b):
    if isinstance(a, str) and isinstance(b, str):
        return f"{a}\n\n{b}" if a and b else a or b
    blocks = lambda c: c if isinstance(c, list) else ([{"type": "text", "text": c}] if c else [])  # noqa: E731
    return blocks(a) + blocks(b)


def has_untrusted(messages: list[dict]) -> bool:
    """True when any assembled content carries an untrusted-external fence (any provider shape)."""
    return any(delimiters.UNTRUSTED_EXTERNAL_MARKER in (m["content"] if isinstance(m.get("content"), str) else str(m.get("content"))) for m in messages)


# ── Memory seam ───────────────────────────────────────────────────────────────


def memory_context(user: User, agent_slug: str, query: str | None) -> str:
    """The memory block for this turn, fenced as untrusted, or "" (no memory package, no query,
    nothing relevant, or a memory failure: memory never breaks a turn)."""
    fn = getattr(_memory, "context_for", None)
    if fn is None or not query:
        return ""
    try:
        text = fn(db.get_conn(), user, agent_slug, query)
    except Exception:
        logger.warning("memory.context_for failed; turn continues without memory", exc_info=True)
        return ""
    return delimiters.wrap_untrusted_memory(text) if text else ""


def after_turn(conversation_id: int) -> None:
    """`memory.after_turn(conn, conversation_id)` inside its own transaction, when present."""
    fn = getattr(_memory, "after_turn", None)
    if fn is None:
        return
    try:
        with db.transaction() as conn:
            fn(conn, conversation_id)
    except Exception:
        logger.warning("memory.after_turn failed", exc_info=True)


def system_prompt(agent: dict, user: User, *, query: str | None, catalog: str = "") -> tuple[str, str]:
    return agents.build_system_prompt(agent, user, catalog=catalog, memory=memory_context(user, agent["slug"], query))
