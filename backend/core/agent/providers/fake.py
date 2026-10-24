"""A scripted provider: tests, and keyless local runs with AGENT_FAKE_PROVIDER=1.

`script(*turns)` queues what the next calls return, one turn per call:
    "text"                                  -> streams that text
    {"tool": name, "args": {...}, "text"?}  -> one tool call (after optional text)
    [{"tool": ...}, {"tool": ...}]          -> several tool calls in one iteration
    {"error": "message"}                    -> a provider error
With nothing queued it answers from the conversation: a user message `/tool <name> <json args>`
calls that tool, a tool result or the resume nudge gets "Done.", anything else is echoed.
Usage is reported as characters / 4 against CONTEXT_WINDOW, so compaction can be exercised.
"""

from __future__ import annotations

import json
import uuid
from collections import deque
from collections.abc import AsyncGenerator

from backend.core.agent.providers.base import DEFAULT_MAX_TOKENS, AIProvider

CONTEXT_WINDOW = 200_000
_script: deque = deque()


def script(*turns) -> None:
    _script.extend(turns)


def reset() -> None:
    _script.clear()


def _unscripted(messages: list[dict]):
    last = messages[-1] if messages else {}
    content = last.get("content")
    if last.get("role") == "user" and isinstance(content, str) and not content.startswith("Please continue"):
        if content.startswith("/tool "):
            name, _, args = content[6:].strip().partition(" ")
            return {"tool": name, "args": json.loads(args or "{}")}
        return f"You said: {content}"
    return "Done."


class FakeProvider(AIProvider):
    @property
    def provider_name(self) -> str:
        return "fake"

    @property
    def context_window(self) -> int | None:
        return CONTEXT_WINDOW

    async def stream_turn(
        self, messages: list[dict], tools: list[dict], system_prompt: str | tuple[str, str],
        *, max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> AsyncGenerator[dict, None]:
        turn = _script.popleft() if _script else _unscripted(messages)
        if isinstance(turn, dict) and "error" in turn:
            yield {"type": "error", "error": turn["error"]}
            yield {"type": "_turn_complete", "tool_calls": [], "stop_reason": "error"}
            return
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
        read = len(json.dumps(system_prompt)) + len(json.dumps(messages, default=str)) + len(json.dumps(tools))
        yield {
            "type": "_turn_complete",
            "tool_calls": tool_calls,
            "stop_reason": "tool_use" if tool_calls else "end_turn",
            "usage": {"input_tokens": read // 4, "output_tokens": max(1, len(text) // 4)},
        }

    def add_tool_results(self, messages: list[dict], tool_calls: list[dict], results: list[dict]) -> list[dict]:
        assistant = [{"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc.get("args", {})} for tc in tool_calls]
        user = [{"type": "tool_result", "tool_use_id": r["tool_use_id"], "content": str(r["content"])} for r in results]
        return messages + [{"role": "assistant", "content": assistant}, {"role": "user", "content": user}]
