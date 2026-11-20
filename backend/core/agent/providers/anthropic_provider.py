"""Anthropic (Claude), lifted from CakeCRM `providers/anthropic_provider.py`.

Streaming with tool use and prompt caching. The SDK is imported inside the methods, so a
missing package or an absent key never breaks import or startup.

Thinking: current models think adaptively and return thinking blocks that must be replayed
unchanged while the same tool loop continues. `_turn_complete` therefore carries the
message's own content (`assistant_content`) and `build_tool_turn` replays it within a turn.
Earlier turns are rebuilt from the database without thinking blocks, which the API accepts
(blocks may be dropped from the front of a history, never edited in the middle).

Web search (`web.search_provider = "anthropic"`): when Whisk is offered `core_web_search`, that
tool is swapped for Anthropic's server-side `web_search`. Anthropic runs the searches inside the
reply, so the results never pass through the engine's fence: `_turn_complete` then carries
`untrusted: True` and the engine taints the conversation. A `pause_turn` (the server's own loop
limit) is continued here, replaying the paused content; the cited pages are appended to the reply
as a Markdown "Sources" list, so the links are shown and saved with the text.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from backend.core.agent.providers.base import DEFAULT_MAX_TOKENS, AIProvider
from backend.core.agent.providers.windows import get_context_window

logger = logging.getLogger(__name__)

_CACHE_CONTROL = {"type": "ephemeral"}
SERVER_SEARCH = "web_search_20250305"  # simplification: the basic version every Claude model takes; the
# dynamic-filtering version (web_search_20260209) needs a per-model list
MAX_CONTINUATIONS = 3  # pause_turn resumes per call
# One AsyncAnthropic per key, for connection reuse. Any: the SDK is imported lazily and fed plain dicts.
_clients: dict[str, Any] = {}


def _search_settings() -> tuple[str, int]:
    from backend.core.platform import keys

    return keys.get("web.search_provider"), keys.get("web.search_max_uses")


def _sources(content: list) -> str:
    """The pages the reply cites, as a Markdown list ('' when it cites none)."""
    seen: dict[str, str] = {}
    for block in content:
        for c in getattr(block, "citations", None) or []:
            url = getattr(c, "url", None)
            if url and url not in seen:
                seen[url] = (getattr(c, "title", None) or url).replace("[", "(").replace("]", ")")
    return "\n\nSources:\n" + "\n".join(f"- [{title}]({url})" for url, title in seen.items()) if seen else ""


def _client(api_key: str) -> Any:
    import anthropic

    cache_key = hashlib.sha256(api_key.encode()).hexdigest()
    if cache_key not in _clients:
        _clients[cache_key] = anthropic.AsyncAnthropic(api_key=api_key)
    return _clients[cache_key]


class AnthropicProvider(AIProvider):
    def __init__(self, api_key: str, model: str):
        super().__init__(model)
        self.api_key = api_key

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def context_window(self) -> int | None:
        # 200K is the floor for every current Claude model, so an unlisted new id still meters.
        return get_context_window(self.model) or (200_000 if self.model.startswith("claude-") else None)

    @staticmethod
    def _system_blocks(system_prompt: str | tuple[str, str]) -> list[dict]:
        if isinstance(system_prompt, tuple):
            static, volatile = system_prompt
            blocks = [{"type": "text", "text": static, "cache_control": _CACHE_CONTROL}]
            return blocks + ([{"type": "text", "text": volatile}] if volatile else [])
        return [{"type": "text", "text": system_prompt}]

    @staticmethod
    def _cache_last_user_message(messages: list[dict]) -> list[dict]:
        """cache_control on the last user message: conversation-prefix caching."""
        if not messages or messages[-1].get("role") != "user":
            return messages
        content = messages[-1].get("content")
        if isinstance(content, str):
            content = [{"type": "text", "text": content, "cache_control": _CACHE_CONTROL}]
        elif isinstance(content, list) and content:
            content = [*content[:-1], {**content[-1], "cache_control": _CACHE_CONTROL}]
        return [*messages[:-1], {"role": "user", "content": content}]

    async def stream_turn(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str | tuple[str, str],
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> AsyncGenerator[dict, None]:
        import anthropic

        from backend.core.web.tools import SEARCH

        api_tools: list[dict] = [
            {"name": t["name"], "description": t.get("description", ""), "input_schema": t.get("input_schema", {})}
            for t in tools
        ]
        if any(t["name"] == SEARCH for t in api_tools):
            provider, max_uses = await asyncio.to_thread(_search_settings)
            if provider == "anthropic":
                api_tools = [{"type": SERVER_SEARCH, "name": "web_search", "max_uses": max_uses}] + [
                    t for t in api_tools if t["name"] != SEARCH
                ]
        if api_tools:
            api_tools[-1] = {**api_tools[-1], "cache_control": _CACHE_CONTROL}
        api_messages = self._cache_last_user_message([m for m in messages if m.get("role") in ("user", "assistant")])
        tool_calls: list[dict] = []
        content: list = []  # every block of the reply, paused pieces included
        final = None
        try:
            for _ in range(MAX_CONTINUATIONS + 1):
                async with _client(self.api_key).messages.stream(
                    model=self.model,
                    max_tokens=max_tokens,
                    system=self._system_blocks(system_prompt),
                    messages=api_messages,
                    tools=api_tools or anthropic.NOT_GIVEN,
                ) as stream:
                    async for event in stream:
                        if (
                            event.type == "content_block_start"
                            and getattr(event.content_block, "type", "") == "tool_use"
                        ):
                            block = event.content_block
                            tool_calls.append({"id": block.id, "name": block.name, "input_json": ""})
                            yield {"type": "tool_start", "tool": block.name, "tool_use_id": block.id}
                        elif event.type == "content_block_delta":
                            if hasattr(event.delta, "text"):
                                yield {"type": "text", "text": event.delta.text}
                            elif hasattr(event.delta, "partial_json") and tool_calls:
                                tool_calls[-1]["input_json"] += event.delta.partial_json
                        elif event.type == "content_block_stop" and tool_calls and "args" not in tool_calls[-1]:
                            last = tool_calls[-1]
                            try:
                                last["args"] = json.loads(last["input_json"] or "{}")
                            except ValueError:
                                last["args"] = {}
                            yield {
                                "type": "tool_args",
                                "tool": last["name"],
                                "tool_use_id": last["id"],
                                "args": last["args"],
                            }
                    final = await stream.get_final_message()
                content += final.content
                if final.stop_reason != "pause_turn":
                    break
                # The server stopped its own search loop mid-reply: send the paused reply back to resume it.
                api_messages = [*api_messages, {"role": "assistant", "content": final.content}]
        except anthropic.RateLimitError:
            yield {"type": "error", "error": "Claude is rate-limited. Please try again in a moment."}
            yield {"type": "_turn_complete", "tool_calls": [], "stop_reason": "error"}
            return
        except anthropic.APIError as e:
            logger.error("Anthropic API error: %s", e)
            yield {"type": "error", "error": f"AI service error: {e!s}"}
            yield {"type": "_turn_complete", "tool_calls": [], "stop_reason": "error"}
            return

        if final is None:  # unreachable: the first pass sets it or raises
            raise RuntimeError("no final message")
        if final.stop_reason == "refusal":
            yield {"type": "error", "error": "The model declined this request."}
            yield {"type": "_turn_complete", "tool_calls": [], "stop_reason": "error"}
            return
        if sources := _sources(content):
            yield {"type": "text", "text": sources}
        usage = final.usage
        yield {
            "type": "_turn_complete",
            "tool_calls": tool_calls,
            "stop_reason": final.stop_reason,
            "usage": {
                "input_tokens": usage.input_tokens or 0,
                "output_tokens": usage.output_tokens or 0,
                "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
                "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
            },
            "assistant_content": content,
            "untrusted": any(getattr(b, "type", "") == "web_search_tool_result" for b in content),
        }

    def add_tool_results(self, messages: list[dict], tool_calls: list[dict], results: list[dict]) -> list[dict]:
        assistant = [
            {"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc.get("args", {})} for tc in tool_calls
        ]
        user = [{"type": "tool_result", "tool_use_id": r["tool_use_id"], "content": str(r["content"])} for r in results]
        return messages + [{"role": "assistant", "content": assistant}, {"role": "user", "content": user}]

    def build_tool_turn(self, text, tool_calls, tool_results, native=None) -> list[dict]:
        msgs = super().build_tool_turn("" if native else text, tool_calls, tool_results)
        if native:
            msgs[0] = {"role": "assistant", "content": native}  # thinking + text + tool_use, unchanged
        return msgs
