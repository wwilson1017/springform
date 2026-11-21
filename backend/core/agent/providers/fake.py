"""A scripted provider: tests, and keyless local runs with AGENT_FAKE_PROVIDER=1.

`script(*turns)` queues what the next calls return, one turn per call:
    "text"                                  -> streams that text
    {"tool": name, "args": {...}, "text"?}  -> one tool call (after optional text)
    [{"tool": ...}, {"tool": ...}]          -> several tool calls in one iteration
    {"error": "message", ...}               -> a provider error; `text` streams first, and `status`,
                                               `code`, `retry_after` ride on the error event
    {"text": "...", "stop": "max_tokens"}   -> a reply with that stop reason (also with "tool")
    a dict turn with "untrusted": True      -> an `untrusted` event first (a provider-side web search)
    {"chunks": ["a", "b"], "delay": 0.2}    -> streams each chunk as its own text event, `delay` s apart
With nothing queued it answers from the conversation: a user message `/tool <name> <json args>`
calls that tool, a tool result or the resume nudge gets "Done.", anything else is echoed. A
message with attachments is echoed by its typed text plus `[attached: N photo(s), M file(s)]`.
Usage is reported as characters / 4 against CONTEXT_WINDOW (a photo counts as IMAGE_CHARS), so
compaction can be exercised.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections import deque
from collections.abc import AsyncGenerator

from backend.core.agent.delimiters import UNTRUSTED_EXTERNAL_MARKER
from backend.core.agent.providers.base import DEFAULT_MAX_TOKENS, AIProvider

CONTEXT_WINDOW = 200_000
IMAGE_CHARS = 4_000  # what a photo counts for in usage, not its base64 length
_script: deque = deque()


def script(*turns) -> None:
    _script.extend(turns)


def reset() -> None:
    _script.clear()


def _typed(content: list) -> tuple[str, str] | None:
    """(typed text, attachment note) of a user message with attachments; None for tool results."""
    if any(isinstance(p, dict) and p.get("type") == "tool_result" for p in content):
        return None
    photos = sum(1 for p in content if p.get("type") == "image")
    texts = [p.get("text", "") for p in content if p.get("type") == "text"]
    fenced = [t for t in texts if UNTRUSTED_EXTERNAL_MARKER in t]
    files = sum(1 for t in fenced if 'kind="image"' not in t)
    return "\n\n".join(t for t in texts if t not in fenced), f" [attached: {photos} photo(s), {files} file(s)]"


def _unscripted(messages: list[dict]):
    last = messages[-1] if messages else {}
    content, note = last.get("content"), ""
    if isinstance(content, list) and (typed := _typed(content)) is not None:
        content, note = typed
    if last.get("role") == "user" and isinstance(content, str) and not content.startswith("Please continue"):
        if content.startswith("/tool "):
            name, _, args = content[6:].strip().partition(" ")
            return {"tool": name, "args": json.loads(args or "{}")}
        return f"You said: {content}{note}"
    return "Done."


def _sized(messages: list[dict]) -> list[dict]:
    """The messages with each image part's data replaced by IMAGE_CHARS characters."""

    def part(p):
        return {**p, "data": "x" * IMAGE_CHARS} if isinstance(p, dict) and p.get("type") == "image" else p

    return [
        {**m, "content": [part(p) for p in m["content"]]} if isinstance(m.get("content"), list) else m for m in messages
    ]


class FakeProvider(AIProvider):
    @property
    def provider_name(self) -> str:
        return "fake"

    @property
    def context_window(self) -> int | None:
        return CONTEXT_WINDOW

    @property
    def supports_images(self) -> bool:
        return True

    async def stream_turn(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str | tuple[str, str],
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> AsyncGenerator[dict, None]:
        turn = _script.popleft() if _script else _unscripted(messages)
        if isinstance(turn, dict) and turn.get("untrusted") is True:
            yield {"type": "untrusted"}
        if isinstance(turn, dict) and "error" in turn:
            if turn.get("text"):
                yield {"type": "text", "text": turn["text"]}
            yield {"type": "error", **{k: turn[k] for k in ("error", "status", "code", "retry_after") if k in turn}}
            yield {"type": "_turn_complete", "tool_calls": [], "stop_reason": "error"}
            return
        if isinstance(turn, dict) and "chunks" in turn:
            for chunk in turn["chunks"]:
                await asyncio.sleep(turn.get("delay", 0))
                yield {"type": "text", "text": chunk}
            yield {"type": "_turn_complete", "tool_calls": [], "stop_reason": "end_turn", "usage": {}}
            return
        stop = turn.get("stop") if isinstance(turn, dict) else None
        if isinstance(turn, dict) and "tool" not in turn:
            turn = turn.get("text", "")  # a stop-only turn: {"text", "stop"}
        calls = [turn] if isinstance(turn, dict) else turn if isinstance(turn, list) else []
        text = turn if isinstance(turn, str) else "".join(c.get("text", "") for c in calls)
        if text:
            yield {"type": "text", "text": text}
        tool_calls = []
        for call in calls:
            tc = {"id": f"fake_{uuid.uuid4().hex[:12]}", "name": call["tool"], "args": call.get("args", {})}
            tool_calls.append(tc)
            yield {"type": "tool_start", "tool": tc["name"], "tool_use_id": tc["id"]}
            yield {"type": "tool_args", "tool": tc["name"], "tool_use_id": tc["id"], "args": tc["args"]}
        read = len(json.dumps(system_prompt)) + len(json.dumps(_sized(messages), default=str)) + len(json.dumps(tools))
        yield {
            "type": "_turn_complete",
            "tool_calls": tool_calls,
            "stop_reason": stop or ("tool_use" if tool_calls else "end_turn"),
            "usage": {"input_tokens": read // 4, "output_tokens": max(1, len(text) // 4)},
        }

    def add_tool_results(self, messages: list[dict], tool_calls: list[dict], results: list[dict]) -> list[dict]:
        assistant = [
            {"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc.get("args", {})} for tc in tool_calls
        ]
        user = [{"type": "tool_result", "tool_use_id": r["tool_use_id"], "content": str(r["content"])} for r in results]
        return messages + [{"role": "assistant", "content": assistant}, {"role": "user", "content": user}]
