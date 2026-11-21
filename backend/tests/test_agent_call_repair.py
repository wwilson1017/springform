"""Call repair (agent.md §5, "Call repair")."""

import json
from types import SimpleNamespace
from typing import cast

import pytest

from backend.core.agent import call_repair, history, registry as tool_registry
from backend.core.agent.providers import fake
from backend.core.agent.spec import ToolSpec
from backend.core.agent.turn_hooks import TurnState


@pytest.fixture(autouse=True)
def _fake(monkeypatch):
    monkeypatch.setenv("AGENT_FAKE_PROVIDER", "1")
    fake.reset()
    yield
    fake.reset()


def chat(client, **body) -> list[dict]:
    r = client.post("/api/agent/chat", json=body)
    assert r.status_code == 200, r.text
    return [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]


def of(evs, kind) -> list[dict]:
    return [e for e in evs if e["type"] == kind]


def p(kind) -> dict:
    return {"type": "object", "properties": {"v": {"type": kind}}}


@pytest.mark.parametrize(
    "kind,value,out",
    [
        ("integer", "42", 42),
        ("integer", " -7 ", -7),
        ("integer", "42.5", "42.5"),
        ("number", "2.5", 2.5),
        ("number", "3.0", 3),
        ("number", "inf", "inf"),
        ("boolean", "TRUE", True),
        ("boolean", "false", False),
        ("boolean", "yes", "yes"),
        ("array", '["a", 1]', ["a", 1]),
        ("array", "a", ["a"]),
        ("array", '{"a": 1}', ['{"a": 1}']),
        ("object", '{"a": 1}', {"a": 1}),
        ("object", "[1]", "[1]"),
        ("integer", 5, 5),
        ("integer", True, True),
        (["integer", "null"], "9", 9),
        (["string", "integer"], "9", "9"),  # already fits one allowed type
        ("string", 9, 9),
    ],
)
def test_coerce(kind, value, out):
    assert call_repair.coerce({"v": value}, p(kind)) == {"v": out}


def test_coerce_leaves_none_and_unknown_keys_alone():
    assert call_repair.coerce({"v": None, "w": "1"}, p("integer")) == {"v": None, "w": "1"}


@pytest.fixture
def echo(app):
    before = tool_registry.current()
    schema = {"type": "object", "properties": {"n": {"type": "integer"}, "tags": {"type": "array"}}}
    read = ToolSpec(name="core_echo", description="Echo.", input_schema=schema, writes=False, handler=lambda u, a: a)
    write = ToolSpec(
        name="core_echo_write",
        description="Echo, after approval.",
        input_schema=schema,
        writes=True,
        targets=lambda a: [],
        handler_in=lambda conn, u, a: a,
    )
    tool_registry.set_current(tool_registry.build_registry([*before.all(), read, write]))
    yield
    tool_registry.set_current(before)


def test_coerced_args_reach_the_handler_the_run_and_the_card(login_as, echo):
    a = login_as("member")
    args = {"n": "42", "tags": '["a"]'}
    fake.script({"tool": "core_echo", "args": args}, "ok", {"tool": "core_echo_write", "args": args}, "Approve?")
    [end] = of(chat(a, message="echo"), "tool_end")
    assert end["result"] == {"n": 42, "tags": ["a"]}
    run = history.get_tool_run(end["tool_run_id"]) or {}
    assert json.loads(run["args"]) == {"n": 42, "tags": ["a"]}
    [card] = of(chat(a, message="write"), "confirm")
    assert card["args"] == {"n": 42, "tags": ["a"]}


def test_an_unknown_tool_gets_a_suggestion(login_as):
    fake.script([{"tool": "example_list_widget", "args": {}}, {"tool": "zzz_nothing_like_it", "args": {}}], "ok")
    ends = of(chat(login_as("member"), message="list"), "tool_end")
    assert [e["result"] for e in ends] == [
        {"error": "Unknown tool 'example_list_widget'. Did you mean 'example_list_widgets'?"},
        {"error": "Unknown tool 'zzz_nothing_like_it'. Use only the tools you were given."},
    ]


def test_an_unloaded_deferred_tool_is_left_to_dispatch():
    spec = ToolSpec(name="x_tool", description="X.", input_schema={"type": "object"}, writes=False, handler=print)
    state = cast(TurnState, SimpleNamespace(by_name={"x_tool": spec}, deferred_specs=[spec], scratch={}))
    assert call_repair.before_tool(state, {"name": "x_tool", "args": {}}) is None


def test_repeating_an_unknown_tool_ends_the_turn(login_as):
    fake.script(*[{"tool": "example_list_widget", "args": {}}] * 6)
    evs = chat(login_as("member"), message="list")
    assert len(of(evs, "tool_end")) == 5 and "kept repeating" in of(evs, "text")[-1]["text"]
