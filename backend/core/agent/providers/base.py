"""The AIProvider interface the engine drives (lifted from CakeCRM `providers/base.py`).

Events yielded by `stream_turn()` (dicts, not yet SSE-encoded):
    {"type": "text", "text": "chunk"}
    {"type": "tool_start", "tool": "name", "tool_use_id": "id"}
    {"type": "tool_args", "tool": "name", "tool_use_id": "id", "args": {...}}
    {"type": "error", "error": "message", "status"?, "retry_after"?, "code"?}   (see error_event)
    {"type": "untrusted"}   web content entered the reply on the provider's side (Anthropic's own
                            search), sent as soon as it arrives; the engine taints the conversation
    {"type": "_turn_complete", "tool_calls": [{"id", "name", "args"}], "stop_reason": "...",
     "usage": {...}, "assistant_content"?: native blocks to replay within this turn}

`_turn_complete` is internal: the engine intercepts it to run tools and loop.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator

DEFAULT_MAX_TOKENS = 64_000  # streaming, and thinking counts against it on current models


def error_event(model: str, e: Exception, *, connection: bool = False) -> dict:
    """A provider `error` event from an SDK exception, with what `errors.classify` reads: the HTTP
    `status`, the provider's error `code` (OpenAI's `code`, else the body's error `type`, e.g.
    Anthropic's `overloaded_error`; "connection_error" when nothing came back) and `retry_after`
    seconds. The text names the model, so even an error no hook handles says which one failed."""
    status = getattr(e, "status_code", None)
    body = getattr(e, "body", None)
    inner = body.get("error", body) if isinstance(body, dict) else {}
    inner = inner if isinstance(inner, dict) else {}
    code = "connection_error" if connection else getattr(e, "code", None) or inner.get("code") or inner.get("type")
    try:
        retry_after = float(getattr(e, "response").headers.get("retry-after"))
    except (AttributeError, TypeError, ValueError):
        retry_after = None
    text = (
        f"{model} is rate-limited. Please try again in a moment."
        if status == 429
        else f"AI service error ({model}): {e!s}"
    )
    return {"type": "error", "error": text, "status": status, "retry_after": retry_after, "code": code}


def sse(data: dict) -> str:
    return f"data: {json.dumps(data, default=str)}\n\n"


class AIProvider(ABC):
    def __init__(self, model: str):
        self.model = model

    @abstractmethod
    def stream_turn(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str | tuple[str, str],
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> AsyncGenerator[dict, None]:
        """One model call. `system_prompt` is a string or a (static, volatile) pair; providers
        with prompt caching cache the static half."""

    @abstractmethod
    def add_tool_results(self, messages: list[dict], tool_calls: list[dict], results: list[dict]) -> list[dict]:
        """Append one tool-using iteration in the provider's native shape. Each result is
        {"tool_use_id", "tool_name", "content"}."""

    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @property
    def context_window(self) -> int | None:
        """Tokens, or None when unknown (the meter hides; compaction assumes a default budget)."""
        return None

    def build_tool_turn(
        self,
        text: str,
        tool_calls: list[dict],
        tool_results: list[dict],
        native: list | None = None,
    ) -> list[dict]:
        """Rebuild one tool-using assistant iteration as native messages. Exactly one result per
        call: a missing one is stubbed, so the model never sees an orphaned tool_use. `native` is
        the provider's own assistant content from this turn (only Anthropic uses it)."""
        tcs = [
            {
                "id": tc.get("tool_use_id") or tc.get("id"),
                "name": tc.get("tool") or tc.get("name"),
                "args": tc.get("args", {}),
            }
            for tc in tool_calls or []
        ]
        by_id = {r.get("tool_use_id"): r for r in tool_results or []}
        res = []
        for tc in tcs:
            r = by_id.get(tc["id"])
            content = r.get("content") if r else '{"status": "result not recorded"}'
            res.append({"tool_use_id": tc["id"], "tool_name": tc["name"], "content": content})
        msgs = self.add_tool_results([], tcs, res)
        if text:
            msgs = self._inject_assistant_text(msgs, text)
        return msgs

    def _inject_assistant_text(self, msgs: list[dict], text: str) -> list[dict]:
        """Put the iteration's text back on the rebuilt assistant message (add_tool_results drops it)."""
        if not msgs or not text:
            return msgs
        a = msgs[0]
        content = a.get("content")
        if isinstance(content, list):
            a["content"] = [{"type": "text", "text": text}] + content  # Anthropic blocks
        elif "tool_calls" in a:
            a["content"] = text  # OpenAI (content was None)
        return msgs
