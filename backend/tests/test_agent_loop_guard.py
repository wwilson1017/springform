"""Loop guards (agent.md §5, "Loop guards")."""

import json

import pytest

from backend.core.agent import dispatch, loop_guard, registry as tool_registry, turn_hooks
from backend.core.agent.providers import fake
from backend.core.agent.spec import ToolSpec


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


@pytest.fixture
def seen(monkeypatch):
    """What the model was sent, per call (JSON of its messages)."""
    sent: list[str] = []
    point = turn_hooks.REGISTERED["before_model_call"]
    monkeypatch.setitem(
        turn_hooks.REGISTERED, "before_model_call", [*point, lambda s: sent.append(json.dumps(s.messages))]
    )
    return sent


@pytest.fixture
def tools(app):
    """core_count (a new result each call), core_page (untrusted, the same page each call)."""
    before, runs = tool_registry.current(), []
    count = ToolSpec(
        name="core_count",
        description="Count.",
        input_schema={"type": "object", "properties": {}},
        writes=False,
        handler=lambda u, a: runs.append(1) or {"n": len(runs)},
    )
    page = ToolSpec(
        name="core_page",
        description="A page.",
        input_schema={"type": "object", "properties": {}},
        writes=False,
        untrusted_source=True,
        handler=lambda u, a: "the same page",
    )
    tool_registry.set_current(tool_registry.build_registry([*before.all(), count, page]))
    yield runs
    tool_registry.set_current(before)


LIST = {"tool": "example_list_widgets", "args": {}}


def notices(text: str) -> list[int]:
    return [n for n in (1, 2, 3) if f"Loop notice {n} of 3" in text]


def test_a_looping_model_ends_on_strike_three(login_as, seen):
    a = login_as("member")
    fake.script(*[LIST] * 6, "never reached")
    evs = chat(a, message="list")
    assert len(of(evs, "tool_end")) == 5 and evs[-1]["type"] == "done"
    assert [notices(m) for m in seen] == [[], [], [], [1], [1, 2]]  # five calls; the fifth result halts
    note = of(evs, "text")[-1]["text"]
    assert note.startswith("*(No complete reply: it kept repeating the same steps, after 5 tool calls")
    assert len(fake._script) == 2  # the sixth call and "never reached" are still queued


def test_an_alternating_cycle_ends_the_same_way(login_as):
    other = {"tool": "example_list_widgets", "args": {"q": "x"}}
    fake.script(*[LIST, other] * 4)
    evs = chat(login_as("member"), message="list")
    assert len(of(evs, "tool_end")) == 6 and "kept repeating" in of(evs, "text")[-1]["text"]


def test_a_changed_result_or_argument_is_not_a_repeat(login_as, tools, seen):
    a = login_as("member")
    fake.script(*[{"tool": "core_count"}] * 5, "five")
    assert of(chat(a, message="count"), "text")[-1]["text"] == "five"
    fake.script(*[{"tool": "example_list_widgets", "args": {"q": str(i)}} for i in range(5)], "ok")
    assert of(chat(a, message="list"), "text")[-1]["text"] == "ok"
    assert not any(notices(m) for m in seen)


def test_parallel_identical_calls_are_one_strike(login_as, seen):
    fake.script([LIST] * 5, "ok")
    evs = chat(login_as("member"), message="list")
    assert of(evs, "text")[-1]["text"] == "ok" and seen[-1].count("Loop notice") == 1


def test_a_notice_then_a_different_call_recovers(login_as, seen):
    fake.script(*[LIST] * 3, {"tool": "example_list_widgets", "args": {"q": "y"}}, LIST, "ok")
    evs = chat(login_as("member"), message="list")
    assert of(evs, "text")[-1]["text"] == "ok" and seen[-1].count("Loop notice") == 1


def test_repeated_text_counts(login_as, seen):
    long = "I am looking through the widgets again to find the one you asked about, one more time now."
    fake.script(*[{"tool": "example_list_widgets", "args": {"q": str(i)}, "text": long} for i in range(3)], "ok")
    chat(login_as("member"), message="list")
    assert seen[-1].count("Loop notice 1 of 3") == 1
    seen.clear()
    fake.script(*[{"tool": "example_list_widgets", "args": {"q": str(i)}, "text": "Checking."} for i in range(3)], "ok")
    chat(login_as("member"), message="list")
    assert not any(notices(m) for m in seen)


def test_identical_untrusted_results_still_match(login_as, tools, monkeypatch):
    monkeypatch.setattr(dispatch, "needs_confirmation", lambda *a: False)  # a tainted untrusted read would ask
    fake.script(*[{"tool": "core_page"}] * 6)
    evs = chat(login_as("member"), message="read")
    assert len(of(evs, "tool_end")) == 5 and "kept repeating" in of(evs, "text")[-1]["text"]


def test_calls_after_the_halt_are_refused(login_as, monkeypatch):
    monkeypatch.setattr(loop_guard, "MAX_STRIKES", 1)
    fake.script(LIST, LIST, [LIST, {"tool": "example_list_widgets", "args": {"q": "z"}}])
    evs = chat(login_as("member"), message="list")
    ends = of(evs, "tool_end")
    assert len(ends) == 4 and ends[-1]["result"] == {"error": "Not run: the turn was stopped."}
    assert evs[-1]["type"] == "done"


def test_a_capped_repeat_keeps_its_table_and_gets_the_notice(login_as, app, monkeypatch):
    from backend.core.agent import result_cap

    monkeypatch.setattr(result_cap, "CAP_CHARS", 200)
    monkeypatch.setattr(result_cap, "HEAD_CHARS", 120)
    monkeypatch.setattr(result_cap, "TAIL_CHARS", 40)
    before = tool_registry.current()
    rows = [{"id": i, "name": f"n{i}", "kind": "k"} for i in range(30)]
    spec = ToolSpec(
        name="core_rows",
        description="Rows.",
        input_schema={"type": "object", "properties": {}},
        writes=False,
        handler=lambda u, a: rows,
    )
    tool_registry.set_current(tool_registry.build_registry([*before.all(), spec]))
    sent: list[str] = []
    point = turn_hooks.REGISTERED["before_model_call"]
    monkeypatch.setitem(
        turn_hooks.REGISTERED, "before_model_call", [*point, lambda s: sent.append(json.dumps(s.messages))]
    )
    try:
        fake.script(*[{"tool": "core_rows"}] * 3, "ok")
        chat(login_as("member"), message="rows")
    finally:
        tool_registry.set_current(before)
    last = sent[-1]
    assert last.count("[CSV: result, 30 rows x 3 fields]") == 3 and "Loop notice 1 of 3" in last


def test_a_result_with_mixed_keys_is_still_keyed():
    assert loop_guard._key("t", {}, {"a": 1, 2: "b"}) == loop_guard._key("t", {}, {"a": 1, 2: "b"})
