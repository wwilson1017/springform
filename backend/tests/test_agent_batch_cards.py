"""Batch cards (agent.md §6): same-shape pending writes of one step share a card, each still confirmed on its own."""

import json

import pytest

from backend.core import db as core_db
from backend.core.agent import engine
from backend.core.agent.providers import fake
from backend.core.agent.spec import ToolSpec

SCHEMA = {"type": "object", "properties": {}}


@pytest.fixture(autouse=True)
def _fake(monkeypatch):
    monkeypatch.setenv("AGENT_FAKE_PROVIDER", "1")
    fake.reset()
    yield
    fake.reset()


def _spec(**kw) -> ToolSpec:
    return ToolSpec(**{"name": "core_t", "description": "t", "input_schema": SCHEMA, "writes": True, **kw})


@pytest.mark.parametrize(
    "spec, args, message_id, batched",
    [
        (_spec(), {"name": "A", "n": 1, "on": True, "x": None, "f": 1.5}, 7, True),
        (_spec(), {}, 7, False),
        (_spec(), {"name": "A"}, None, False),
        (_spec(), {f"k{i}": i for i in range(13)}, 7, False),
        (_spec(), {"tags": ["a"]}, 7, False),
        (_spec(), {"meta": {"a": 1}}, 7, False),
        (_spec(), {"name": "x" * 199}, 7, False),
        (_spec(), {"n": float("nan")}, 7, False),
        (_spec(always_confirm=True), {"name": "A"}, 7, False),
        (_spec(writes=False), {"name": "A"}, 7, False),
    ],
    ids=["flat", "no-args", "no-step", "too-many", "list", "nested", "long", "nan", "always-ask", "read"],
)
def test_batch_key(spec, args, message_id, batched):
    assert (engine.batch_key(spec, args, message_id) is not None) is batched


def test_the_key_is_one_step_one_tool_one_set_of_names():
    key = engine.batch_key
    assert key(_spec(), {"name": "A"}, 7) == key(_spec(), {"name": "B"}, 7)
    assert key(_spec(), {"name": "A"}, 7) != key(_spec(), {"name": "A"}, 8)  # another step
    assert key(_spec(), {"name": "A"}, 7) != key(_spec(), {"name": "A", "color": "red"}, 7)
    assert key(_spec(), {"name": "A"}, 7) != key(_spec(name="core_u"), {"name": "A"}, 7)


def _two_widgets(client) -> list[dict]:
    fake.script(
        [
            {"tool": "example_create_widget", "args": {"name": "One"}},
            {"tool": "example_create_widget", "args": {"name": "Two"}},
            {"tool": "example_create_widget", "args": {"name": "Three", "color": "red"}},
        ],
        "They wait.",
    )
    r = client.post("/api/agent/chat", json={"message": "make three widgets"})
    return [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]


def test_same_shape_calls_share_a_key_on_events_and_on_reload(login_as):
    a = login_as("member")
    evs = _two_widgets(a)
    cards = [e for e in evs if e["type"] == "confirm"]
    assert cards[0]["batch"] and cards[0]["batch"] == cards[1]["batch"] != cards[2]["batch"]
    conv = a.get(f"/api/agent/conversations/{evs[0]['id']}").json()
    calls = [c for m in conv["messages"] for c in m["tool_calls"]]
    assert [c["batch"] for c in calls] == [e["batch"] for e in cards]


def test_each_member_is_confirmed_on_its_own(login_as):
    a = login_as("member")
    one, two, _ = [e for e in _two_widgets(a) if e["type"] == "confirm"]
    with core_db.transaction() as conn:
        conn.execute("UPDATE core_agent_tool_runs SET tool_def_sha256 = 'old' WHERE id = ?", (one["tool_run_id"],))

    def post(card):
        return a.post("/api/agent/confirm", json={"tool_run_id": card["tool_run_id"], "decision": "approve"})

    assert post(one).json()["status"] == "stale"
    assert post(two).json()["status"] == "done"
    assert post(two).json() == {"status": "already_resolved", "current": "done"}
    assert [w["name"] for w in core_db.rows("SELECT name FROM example_widgets")] == ["Two"]
