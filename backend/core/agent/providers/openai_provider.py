"""OpenAI (GPT), lifted from CakeCRM `providers/openai_provider.py`.

Streaming chat completions with function calling. The SDK is imported inside the methods, so
a missing package or an absent key never breaks import or startup.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator

from backend.core.agent.providers.base import DEFAULT_MAX_TOKENS, AIProvider, error_event

logger = logging.getLogger(__name__)


def _ensure_array_items(schema: dict) -> dict:
    """OpenAI requires `items` on every array schema."""
    if not isinstance(schema, dict):
        return schema
    out = dict(schema)
    if out.get("type") == "array" and "items" not in out:
        out["items"] = {}
    if "properties" in out:
        out["properties"] = {k: _ensure_array_items(v) for k, v in out["properties"].items()}
    if isinstance(out.get("items"), dict):
        out["items"] = _ensure_array_items(out["items"])
    return out


_VISION_PREFIXES = ("gpt-4o", "gpt-4.1", "gpt-5", "o1", "o3", "o4", "chatgpt-")
_NO_VISION = ("o1-mini", "o1-preview", "o3-mini")


def _user_content(content):
    """Neutral image parts as data-URL `image_url` parts; text parts are already OpenAI's shape."""
    if not isinstance(content, list):
        return content
    return [
        {"type": "image_url", "image_url": {"url": f"data:{p['media_type']};base64,{p['data']}"}}
        if isinstance(p, dict) and p.get("type") == "image"
        else p
        for p in content
    ]


class OpenAIProvider(AIProvider):
    def __init__(self, api_key: str, model: str):
        super().__init__(model)
        self.api_key = api_key

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def supports_images(self) -> bool:
        low = self.model.lower()
        return low.startswith(_VISION_PREFIXES) and not low.startswith(_NO_VISION)

    async def stream_turn(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str | tuple[str, str],
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> AsyncGenerator[dict, None]:
        import openai

        client = openai.AsyncOpenAI(api_key=self.api_key)
        if isinstance(system_prompt, tuple):
            system_prompt = "\n".join(system_prompt)  # caching is Anthropic-only
        api_messages: list[dict] = [{"role": "system", "content": system_prompt}]
        for m in messages:
            role = m.get("role")
            if role == "user":
                api_messages.append({"role": "user", "content": _user_content(m.get("content", ""))})
            elif role == "assistant":
                msg: dict = {"role": "assistant"}
                if m.get("content") is not None:
                    msg["content"] = m["content"]
                if m.get("tool_calls"):
                    msg["tool_calls"] = m["tool_calls"]
                api_messages.append(msg)
            elif role == "tool":
                api_messages.append(
                    {"role": "tool", "tool_call_id": m.get("tool_call_id", ""), "content": m.get("content", "")}
                )

        kwargs: dict = {
            "model": self.model,
            "messages": api_messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        # o-series and gpt-5.x take max_completion_tokens.
        kwargs["max_completion_tokens" if self.model.startswith(("o1", "o3", "o4", "gpt-5")) else "max_tokens"] = (
            max_tokens
        )
        if tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": _ensure_array_items(t.get("input_schema", {"type": "object", "properties": {}})),
                    },
                }
                for t in tools
            ]
        tool_calls: list[dict] = []
        usage: dict = {}
        finish = None
        try:
            async for chunk in await client.chat.completions.create(**kwargs):
                if chunk.usage:  # prompt_tokens includes the cached ones; split them out as Anthropic reports them
                    details = getattr(chunk.usage, "prompt_tokens_details", None)
                    cached = getattr(details, "cached_tokens", 0) or 0
                    usage = {
                        "input_tokens": (chunk.usage.prompt_tokens or 0) - cached,
                        "output_tokens": chunk.usage.completion_tokens or 0,
                        "cache_read_input_tokens": cached,
                    }
                finish = (chunk.choices[0].finish_reason if chunk.choices else None) or finish
                delta = chunk.choices[0].delta if chunk.choices else None
                if not delta:
                    continue
                if delta.content:
                    yield {"type": "text", "text": delta.content}
                for tc in delta.tool_calls or []:
                    while len(tool_calls) <= tc.index:
                        tool_calls.append({"id": "", "name": "", "input_json": ""})
                    call = tool_calls[tc.index]
                    if tc.id:
                        call["id"] = tc.id
                    if tc.function and tc.function.name:
                        call["name"] = tc.function.name
                        yield {"type": "tool_start", "tool": tc.function.name, "tool_use_id": tc.id or ""}
                    if tc.function and tc.function.arguments:
                        call["input_json"] += tc.function.arguments
        except openai.APIError as e:
            logger.error("OpenAI API error: %s", e)
            yield error_event(self.model, e, connection=isinstance(e, openai.APIConnectionError))
            yield {"type": "_turn_complete", "tool_calls": [], "stop_reason": "error"}
            return

        for call in tool_calls:
            try:
                call["args"] = json.loads(call["input_json"] or "{}")
            except ValueError:
                call["args"] = {}
            yield {"type": "tool_args", "tool": call["name"], "tool_use_id": call["id"], "args": call["args"]}
        yield {
            "type": "_turn_complete",
            "tool_calls": tool_calls,
            "stop_reason": (
                "max_tokens"  # a length cutoff, named as Anthropic does
                if finish == "length"
                else "refusal"
                if finish == "content_filter"
                else "tool_use"
                if tool_calls
                else "stop"
            ),
            "usage": usage,
        }

    def add_tool_results(self, messages: list[dict], tool_calls: list[dict], results: list[dict]) -> list[dict]:
        assistant = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": json.dumps(tc.get("args", {}))},
                }
                for tc in tool_calls
            ],
        }
        return (
            messages
            + [assistant]
            + [{"role": "tool", "tool_call_id": r["tool_use_id"], "content": str(r["content"])} for r in results]
        )
