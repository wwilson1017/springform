"""In-turn clearing (agent.md §5, "Result cap and in-turn clearing")."""

import json

import pytest

from backend.core.agent import assembly, context_shrink, history, registry as tool_registry, turn_hooks
from backend.core.agent.context_shrink import CLEARED, cleared
from backend.core.agent.providers import fake
from backend.core.agent.providers.fake import FakeProvider
from backend.core.agent.spec import ToolSpec

BODY = "y" * 1000


@pytest.fixture(autouse=True)
def _fake(monkeypatch):
    monkeypatch.setenv("AGENT_FAKE_PROVIDER", "1")
    fake.reset()
    yield
    fake.reset()


def anthropic_shape(n: int, *, trailing: int = 0) -> list[dict]:
    msgs: list[dict] = [{"role": "user", "content": "go"}]
    for i in range(n + trailing):
        msgs.append({"role": "assistant", "content": [{"type": "tool_use", "id": f"t{i}", "name": "x", "input": {}}]})
        msgs.append(
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"t{i}", "content": f"{i}{BODY}"}]}
        )
    if not trailing:
        msgs.append({"role": "assistant", "content": "thinking about it"})
    return msgs


def openai_shape(n: int) -> list[dict]:
    msgs: list[dict] = [{"role": "user", "content": "go"}]
    for i in range(n):
        msgs.append({"role": "assistant", "content": None, "tool_calls": [{"id": f"t{i}"}]})
        msgs.append({"role": "tool", "tool_call_id": f"t{i}", "content": f"{i}{BODY}"})
    msgs.append({"role": "assistant", "content": "thinking about it"})
    return msgs


def contents(msgs) -> list[str]:
    out = []
    for m in msgs:
        if m["role"] == "tool":
            out.append(m["content"])
        elif m["role"] == "user" and isinstance(m["content"], list):
            out += [b["content"] for b in m["content"]]
    return out


@pytest.mark.parametrize("shape", [anthropic_shape, openai_shape])
def test_cleared_keeps_the_newest_three_in_both_shapes(shape):
    msgs = shape(6)
    before = json.dumps(msgs)
    out, count = cleared(msgs)
    assert count == 3 and contents(out) == [CLEARED] * 3 + [f"{i}{BODY}" for i in (3, 4, 5)]
    assert json.dumps(msgs) == before  # the input is not changed
    assert cleared(out)[1] == 0  # already cleared ones are not counted again


def test_small_results_are_left():
    msgs = anthropic_shape(5)
    msgs[2]["content"][0]["content"] = '{"id": 5}'
    out, count = cleared(msgs)
    assert count == 1 and contents(out)[:2] == ['{"id": 5}', CLEARED]


def test_results_the_model_has_not_seen_are_never_cleared():
    msgs = anthropic_shape(0, trailing=5)
    msgs[-1]["content"] = [{"type": "tool_result", "tool_use_id": f"u{i}", "content": BODY} for i in range(5)]
    out, count = cleared(msgs)
    assert contents(out)[-5:] == [BODY] * 5  # the round the model is about to read
    assert count == 4  # the four seen rounds before it, since five unseen already fill the keep


def test_clearing_starts_past_the_token_mark_and_only_in_the_turn(login_as, app, monkeypatch):
    monkeypatch.setattr(context_shrink, "CLEAR_AT_TOKENS", 1)
    before = tool_registry.current()
    spec = ToolSpec(name="core_page", description="A page.", input_schema={"type": "object", "properties": {}},
                    writes=False, handler=lambda u, a: BODY)  # fmt: skip
    tool_registry.set_current(tool_registry.build_registry([*before.all(), spec]))
    seen: list[list[str]] = []
    point = turn_hooks.REGISTERED["before_model_call"]
    monkeypatch.setitem(
        turn_hooks.REGISTERED, "before_model_call", [*point, lambda s: seen.append(contents(s.messages))]
    )
    try:
        fake.script(*[{"tool": "core_page", "args": {"n": i}} for i in range(6)], "done reading")
        evs = [json.loads(x[6:]) for x in login_as("member").post("/api/agent/chat", json={"message": "read"}).text.splitlines() if x.startswith("data: ")]  # fmt: skip
    finally:
        tool_registry.set_current(before)
    assert evs[-1]["type"] == "done"
    assert CLEARED not in seen[1]  # one result is never cleared
    assert seen[-1] == [CLEARED] * 3 + [BODY] * 3
    runs = history.tool_runs_for(evs[0]["id"])
    assert all(history.model_content(r) == BODY for r in runs)  # storage untouched
    assert CLEARED not in json.dumps(assembly.assemble_messages(FakeProvider("fake"), evs[0]["id"]))


def test_shrink_waits_for_the_mark_unless_forced():
    from types import SimpleNamespace

    state = SimpleNamespace(messages=anthropic_shape(6), usage={"input_tokens": context_shrink.CLEAR_AT_TOKENS})
    assert context_shrink.shrink(state) == 0
    state.usage = {"input_tokens": 60_000, "cache_read_input_tokens": 40_001}
    assert context_shrink.shrink(state) == 3
    state.messages, state.usage = anthropic_shape(6), {}
    assert context_shrink.shrink(state, force=True) == 3
