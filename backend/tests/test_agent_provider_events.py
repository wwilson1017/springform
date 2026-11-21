"""What the vendor providers report (agent.md §5): error events with status, code and retry-after,
length cutoffs and refusals as stop reasons. The SDK clients are stubbed; nothing calls a model."""

import asyncio
from types import SimpleNamespace

import pytest

from backend.core.agent.providers import anthropic_provider, openai_provider
from backend.core.agent.providers.base import error_event


class Boom(Exception):
    def __init__(self, text="boom", status_code=None, body=None, code=None, headers=None):
        super().__init__(text)
        self.status_code, self.body, self.code = status_code, body, code
        if headers is not None:
            self.response = SimpleNamespace(headers=headers)


@pytest.mark.parametrize(
    "exc,want",
    [
        (Boom(status_code=429, headers={"retry-after": "7"}), {"status": 429, "retry_after": 7.0}),
        (Boom(status_code=429, headers={}), {"status": 429, "retry_after": None}),
        (Boom(status_code=429, headers={"retry-after": "soon"}), {"retry_after": None}),
        (Boom(status_code=429, code="insufficient_quota"), {"code": "insufficient_quota"}),  # OpenAI shape
        (
            Boom(status_code=529, body={"type": "error", "error": {"type": "overloaded_error", "message": "x"}}),
            {"code": "overloaded_error"},  # Anthropic shape
        ),
        (Boom(status_code=200, body={"type": "overloaded_error"}), {"status": 200, "code": "overloaded_error"}),
    ],
)
def test_error_event(exc, want):
    event = error_event("model-x", exc)
    assert event["type"] == "error" and "model-x" in event["error"]
    assert {k: event[k] for k in want} == want


def test_a_connection_error_has_its_own_code():
    assert error_event("model-x", Boom("reset"), connection=True)["code"] == "connection_error"


def drain(gen) -> list[dict]:
    async def go():
        return [e async for e in gen]

    return asyncio.run(go())


def chunk(content=None, finish=None, tool=None):
    delta = SimpleNamespace(content=content, tool_calls=[tool] if tool else None)
    return SimpleNamespace(usage=None, choices=[SimpleNamespace(delta=delta, finish_reason=finish)])


@pytest.mark.parametrize("with_tool", [False, True])
def test_openai_reports_a_length_cutoff(monkeypatch, with_tool):
    import openai

    half = SimpleNamespace(index=0, id="c1", function=SimpleNamespace(name="core_x", arguments='{"a": '))
    chunks = [chunk("Half a"), chunk(tool=half if with_tool else None), chunk(finish="length")]

    async def stream():
        for c in chunks:
            yield c

    async def create(**kw):
        return stream()

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda api_key: client)
    events = drain(openai_provider.OpenAIProvider("k", "gpt-x").stream_turn([], [], "sys"))
    assert events[-1]["type"] == "_turn_complete" and events[-1]["stop_reason"] == "max_tokens"


def test_openai_splits_cached_tokens_out_of_input(monkeypatch):
    """OpenAI counts cached tokens inside prompt_tokens; the provider reports them as Anthropic does."""
    import openai

    details = SimpleNamespace(cached_tokens=60)
    tail = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=7, prompt_tokens_details=details), choices=[]
    )

    async def stream():
        for c in (chunk("Hi", finish="stop"), tail):
            yield c

    async def create(**kw):
        return stream()

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda api_key: client)
    events = drain(openai_provider.OpenAIProvider("k", "gpt-x").stream_turn([], [], "sys"))
    assert events[-1]["usage"] == {"input_tokens": 40, "output_tokens": 7, "cache_read_input_tokens": 60}


def test_anthropic_refusal_is_a_completion(monkeypatch):
    final = SimpleNamespace(stop_reason="refusal", content=[], usage=SimpleNamespace(input_tokens=1, output_tokens=1))

    class Stream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

        async def get_final_message(self):
            return final

    client = SimpleNamespace(messages=SimpleNamespace(stream=lambda **kw: Stream()))
    monkeypatch.setattr(anthropic_provider, "_client", lambda key: client)
    events = drain(anthropic_provider.AnthropicProvider("k", "claude-x").stream_turn([], [], "sys"))
    assert [e["type"] for e in events] == ["_turn_complete"] and events[0]["stop_reason"] == "refusal"
