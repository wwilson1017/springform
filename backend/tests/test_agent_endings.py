"""Honest endings and the last answer (agent.md §5, "Honest endings")."""

import json

import pytest

from backend.core import db
from backend.core.agent import registry as tool_registry, turn_hooks, turns
from backend.core.agent.providers import fake
from backend.core.agent.spec import ROUTINE, ToolSpec
from backend.core.agent.write_budget import BudgetAction, BudgetState


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


def saved(client, cid) -> list[str]:
    return [
        m["text"] for m in client.get(f"/api/agent/conversations/{cid}").json()["messages"] if m["role"] == "assistant"
    ]


@pytest.mark.parametrize(
    "turn,words",
    [
        ("", "No complete reply: the model ended without writing a reply. Please send your message again."),
        ({"text": "", "stop": "refusal"}, "No complete reply: the model declined to answer. Please send"),
        (
            {"text": "Half a rep", "stop": "max_tokens"},
            "This reply is incomplete: it hit the length limit for a single response.)",
        ),
    ],
)
def test_unfinished_completed_round(login_as, turn, words):
    a = login_as("member")
    fake.script(turn)
    evs = chat(a, message="hi")
    assert evs[-1]["type"] == "done" and words in of(evs, "text")[-1]["text"]
    assert words in saved(a, evs[0]["id"])[-1]  # a reload shows it


def test_a_cut_off_tool_call_is_neither_run_nor_recorded(login_as):
    a = login_as("member")
    fake.script({"tool": "example_list_widgets", "args": {}, "text": "Let me", "stop": "max_tokens"})
    evs = chat(a, message="list")
    assert of(evs, "tool_end") == [] and evs[-1]["type"] == "done"
    assert db.rows("SELECT 1 FROM core_agent_tool_runs WHERE conversation_id = ?", (evs[0]["id"],)) == []
    row = db.one(
        "SELECT content FROM core_agent_messages WHERE conversation_id = ? AND role = 'assistant'", (evs[0]["id"],)
    )
    assert row is not None and "tool_calls" not in json.loads(row["content"])
    assert "length limit" in of(evs, "text")[-1]["text"]


@pytest.mark.parametrize("failing", [{"error": "boom"}, {"error": "cut", "text": "partial"}])
def test_a_provider_failure_after_tools_saves_a_note(login_as, failing):
    a = login_as("member")
    fake.script({"tool": "example_list_widgets", "args": {}}, failing)
    evs = chat(a, message="list")
    assert [e["type"] for e in evs[-2:]] == ["text", "error"]
    note = evs[-2]["text"]
    assert "the AI service returned an error, after 1 tool call (last: example_list_widgets)" in note
    assert "Some steps may already have run" in note and "send your message again" not in note
    last = saved(a, evs[0]["id"])[-1]
    assert (
        last.startswith("partial\n\n*(This reply is incomplete")
        if "text" in failing
        else last.startswith("*(No complete")
    )


def test_a_failure_before_any_tool_saves_nothing(login_as):
    a = login_as("member")
    fake.script({"error": "boom"})
    evs = chat(a, message="hi")
    assert evs[-1]["type"] == "error" and of(evs, "text") == [] and saved(a, evs[0]["id"]) == []


def test_refused_and_pending_calls_do_not_count_as_steps(login_as):
    a = login_as("member")
    fake.script([{"tool": "no_such_tool"}, {"tool": "example_list_widgets"}], {"error": "boom"})
    note = of(chat(a, message="go"), "text")[-1]["text"]
    assert "after 1 tool call (last: example_list_widgets)" in note


def test_last_answer_at_the_round_limit(login_as, monkeypatch):
    monkeypatch.setattr(turns, "MAX_ITERATIONS", 2)
    a = login_as("member")
    sent = []
    point = turn_hooks.REGISTERED["before_model_call"]
    monkeypatch.setitem(
        turn_hooks.REGISTERED, "before_model_call", [*point, lambda s: sent.append(json.dumps(s.messages))]
    )
    fake.script(
        {"tool": "example_list_widgets", "args": {}},
        {"tool": "example_list_widgets", "args": {"again": 1}},
        "Here is what I found.",
    )
    evs = chat(a, message="dig")
    assert turns.LAST_ANSWER in sent[2] and turns.LAST_ANSWER not in sent[1]
    texts = [e["text"] for e in of(evs, "text")]
    assert texts[-2] == "Here is what I found." and evs[-1]["type"] == "done"
    assert "incomplete: it reached the limit of 2 tool rounds, after 2 tool calls" in texts[-1]

    fake.script(
        {"tool": "example_list_widgets", "args": {}},
        {"tool": "example_list_widgets", "args": {}},
        {"tool": "example_list_widgets"},
    )
    evs = chat(a, message="dig again")
    assert len(of(evs, "tool_end")) == 2  # the last answer's call is not run
    assert "No complete reply: it reached the limit of 2 tool rounds" in of(evs, "text")[-1]["text"]


def test_a_pending_turn_gets_no_note(login_as):
    a = login_as("member")
    fake.script({"tool": "example_create_widget", "args": {"name": "w"}}, "That needs your approval.")
    evs = chat(a, message="make one")
    assert of(evs, "confirm") and [e["text"] for e in of(evs, "text")] == ["That needs your approval."]


def test_the_write_budget_ending_says_so(login_as, app, monkeypatch):
    before = tool_registry.current()
    spec = ToolSpec(name="core_note_thing", description="Note.", input_schema={"type": "object", "properties": {}},
                    writes=True, confirm_tier=ROUTINE, targets=lambda a: [], handler_in=lambda c, u, a: {"ok": True})  # fmt: skip
    tool_registry.set_current(tool_registry.build_registry([*before.all(), spec]))
    monkeypatch.setattr(BudgetState, "check_write", lambda self: BudgetAction.TERMINATE)
    try:
        fake.script({"tool": "core_note_thing"})
        evs = chat(login_as("member"), message="note")
    finally:
        tool_registry.set_current(before)
    assert evs[-1]["type"] == "done" and "it reached the limit of writes for one turn" in of(evs, "text")[-1]["text"]
