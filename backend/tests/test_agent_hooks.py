"""The five turn hook points (agent.md §5, "Hook points"): what ships on each, and each does what
its contract says when a hook is registered."""

import json

import pytest

from backend.core.agent import history, turn_hooks, turns
from backend.core.agent.providers import fake
from backend.core.agent.providers.fake import FakeProvider
from backend.core.agent.turn_hooks import Fail, Fallback, Retry


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


def hook(monkeypatch, point, fn):
    monkeypatch.setitem(turn_hooks.REGISTERED, point, [fn])


SHIPPED = {
    "before_model_call": ["backend.core.agent.context_shrink", "backend.core.agent.intents"],
    "on_provider_error": ["backend.core.agent.errors"],
    "before_tool": ["backend.core.agent.call_repair"],
    "on_tool_result": ["backend.core.agent.loop_guard", "backend.core.agent.result_cap"],
    "end_of_turn": ["backend.core.agent.completion_claims", "backend.core.agent.endings"],
}


def test_shipped_hooks_and_register_checks_the_name(monkeypatch):
    assert {m.__name__ for m in turns.HOOK_MODULES} == {
        m for ms in SHIPPED.values() for m in ms
    }  # importing turns loads them
    # import order sets the order within a point; only on_tool_result's is load-bearing (the cap, then the notice)
    assert {p: sorted(fn.__module__ for fn in fns) for p, fns in turn_hooks.REGISTERED.items()} == SHIPPED
    assert [fn.__module__ for fn in turn_hooks.REGISTERED["on_tool_result"]] == SHIPPED["on_tool_result"][::-1]
    monkeypatch.setitem(turn_hooks.REGISTERED, "end_of_turn", [])
    with pytest.raises(ValueError, match="unknown turn hook point"):
        turn_hooks.register("after_everything", print)
    turn_hooks.register("end_of_turn", print)
    turn_hooks.register("end_of_turn", print)
    assert turn_hooks.REGISTERED["end_of_turn"] == [print]


def test_before_model_call_runs_before_every_model_call(login_as, monkeypatch):
    seen = []
    hook(monkeypatch, "before_model_call", lambda state: seen.append(state.iteration))
    fake.script({"tool": "example_list_widgets", "args": {}}, "none")
    assert chat(login_as("member"), message="list")[-1]["type"] == "done"
    assert seen == [0, 1]


def test_on_provider_error_retry_and_fail(login_as, monkeypatch):
    a = login_as("member")
    attempts = []

    async def retry(state, err):  # an async hook
        attempts.append((err.message, err.attempt))
        return Retry()

    hook(monkeypatch, "on_provider_error", retry)
    fake.script({"error": "overloaded"}, "fine")
    evs = chat(a, message="hi")
    assert of(evs, "error") == [] and of(evs, "text")[-1]["text"] == "fine"
    assert attempts == [("overloaded", 1)]

    hook(monkeypatch, "on_provider_error", lambda state, err: Fail("Whisk is busy; try again."))
    fake.script({"error": "overloaded"})
    assert chat(a, message="hi")[-1]["error"] == "Whisk is busy; try again."


def test_on_provider_error_fallback_switches_provider(login_as, monkeypatch):
    hook(monkeypatch, "on_provider_error", lambda state, err: Fallback(FakeProvider("fake-backup")))
    fake.script({"error": "down"}, "from the backup")
    evs = chat(login_as("member"), message="hi")
    assert evs[-1] == {"type": "done", "model": "fake-backup", "seq": evs[-1]["seq"]}


@pytest.mark.parametrize("answer", [Retry(), Fallback(FakeProvider("fake-backup"))])
def test_a_model_call_fails_for_good_after_three_failures(login_as, monkeypatch, answer):
    asked = []
    hook(monkeypatch, "on_provider_error", lambda state, err: asked.append(err.attempt) or answer)
    fake.script({"error": "e1"}, {"error": "e2"}, {"error": "e3"}, "never reached")
    evs = chat(login_as("member"), message="hi")
    assert evs[-1]["type"] == "error" and evs[-1]["error"] == "e3" and asked == [1, 2]


def test_before_tool_can_refuse_a_call(login_as, monkeypatch):
    hook(monkeypatch, "before_tool", lambda state, call: f"{call['name']} is blocked here.")
    fake.script({"tool": "example_list_widgets", "args": {}}, "ok")
    evs = chat(login_as("member"), message="list")
    end = of(evs, "tool_end")[0]
    assert (end["status"], end["result"]) == ("error", {"error": "example_list_widgets is blocked here."})
    assert history.get_tool_run(end["tool_run_id"])["status"] == "error"


def test_on_tool_result_changes_only_what_the_model_sees(login_as, monkeypatch):
    sent = []
    hook(monkeypatch, "on_tool_result", lambda state, call, run: json.dumps({"capped": run["status"]}))
    hook(monkeypatch, "before_model_call", lambda state: sent.append(json.dumps(state.messages)))
    fake.script({"tool": "example_list_widgets", "args": {}}, "ok")
    evs = chat(login_as("member"), message="list")
    end = of(evs, "tool_end")[0]
    assert end["result"] == [] and history.get_tool_run(end["tool_run_id"])["result"] == "[]"
    assert "capped" not in sent[0] and "capped" in sent[1]


def test_end_of_turn_events_come_just_before_done(login_as, monkeypatch):
    hook(monkeypatch, "end_of_turn", lambda state: [{"type": "note", "text": f"turn {state.turn_id}"}])
    evs = chat(login_as("member"), message="hi")
    assert [e["type"] for e in evs[-2:]] == ["note", "done"] and evs[-2]["text"] == f"turn {evs[0]['turn_id']}"


def test_a_hook_that_raises_ends_the_turn_with_an_error(login_as, monkeypatch):
    hook(monkeypatch, "before_model_call", lambda state: 1 / 0)
    evs = chat(login_as("member"), message="hi")
    assert evs[-1]["type"] == "error" and evs[-1]["error"] == "The assistant hit an unexpected error and stopped."


def test_end_of_turn_also_runs_on_an_error_ending(login_as, monkeypatch):
    hook(monkeypatch, "end_of_turn", lambda state: [{"type": "note", "text": state.error}])
    fake.script({"error": "boom"})
    evs = chat(login_as("member"), message="hi")
    assert [e["type"] for e in evs[-2:]] == ["note", "error"] and evs[-2]["text"] == "boom"


def test_provider_failure_carries_status_retry_after_and_code(login_as, monkeypatch):
    seen = []
    hook(monkeypatch, "on_provider_error", lambda state, err: seen.append(err) or Fail())
    fake.script({"error": "slow", "status": 429, "retry_after": 3, "code": "rate_limit_error"})
    chat(login_as("member"), message="hi")
    assert [(e.message, e.attempt, e.status, e.retry_after, e.code) for e in seen] == [
        ("slow", 1, 429, 3, "rate_limit_error")
    ]
