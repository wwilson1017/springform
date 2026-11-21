"""Completion claims (agent.md §5, "Completion claims")."""

import json

import pytest

from backend.core.agent import completion_claims, registry as tool_registry
from backend.core.agent.providers import fake
from backend.core.agent.spec import ROUTINE, ToolSpec


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


@pytest.mark.parametrize(
    "text,kinds",
    [
        ("I sent it.", ["sent"]),
        ("I've just sent the email.", ["sent"]),
        ("**Sent** the invite.", ["sent"]),
        ("The note has been posted.", ["posted"]),
        ("I've created the deal for the bakery.", ["created"]),
        ("Filed.", ["filed"]),
        ("Done! I sent it. I also added the task to your list.", ["sent", "created"]),
        ("Should I send it?", []),
        ("I have not sent it yet.", []),
        ("I'll send it once you approve.", []),
        ("I sent it yesterday.", []),
        ('Draft: "I sent it."', []),
        ("```\nI sent it.\n```", []),
        ("> I sent it.", []),
        ("I've created a plan for the week.", []),
        ("Sent to: the supplier", []),
        ("I've sent it for your approval.", []),
        ("sent items are in the folder.", []),
        ("Yes, the email was sent on November 3.", []),
        ("The comment was added by the team on Monday.", []),
        ("The email has been sent.", ["sent"]),
    ],
)
def test_claims(text, kinds):
    assert completion_claims.claims(text) == kinds


@pytest.fixture
def tools(app):
    before = tool_registry.current()
    send = ToolSpec(
        name="core_send_thing",
        description="Send a thing out.",
        input_schema={"type": "object", "properties": {}},
        writes=True,
        external_effect=True,
        handler=lambda u, a: {"sent": True},
    )
    note = ToolSpec(
        name="core_note_thing",
        description="Note a thing.",
        input_schema={"type": "object", "properties": {}},
        writes=True,
        confirm_tier=ROUTINE,
        targets=lambda a: [],
        handler_in=lambda conn, u, a: {"noted": True},
    )
    tool_registry.set_current(tool_registry.build_registry([*before.all(), send, note]))
    yield
    tool_registry.set_current(before)


def corrections(evs) -> list[str]:
    return [e["text"] for e in of(evs, "text") if "Correction:" in e["text"]]


def test_a_fake_i_sent_it_is_flagged(login_as):
    a = login_as("member")
    fake.script("I sent it.")
    evs = chat(a, message="send it")
    assert [e["type"] for e in evs if e["type"] != "usage"][-3:] == ["text", "text", "done"]
    assert corrections(evs) == ["\n\n" + completion_claims.NOTE.format(verbs="sent")]
    saved = [m["text"] for m in a.get(f"/api/agent/conversations/{evs[0]['id']}").json()["messages"]]
    assert saved[-1] == completion_claims.NOTE.format(verbs="sent")


def test_a_finished_send_backs_the_claim(login_as, tools):
    a = login_as("member")
    fake.script({"tool": "core_send_thing"}, "It needs your approval.")
    evs = chat(a, message="send it")
    [card], cid = of(evs, "confirm"), evs[0]["id"]
    assert (
        a.post("/api/agent/confirm", json={"tool_run_id": card["tool_run_id"], "decision": "approve"}).json()["status"]
        == "done"
    )
    fake.script("I sent it.")
    assert corrections(chat(a, conversation_id=cid)) == []


def test_a_local_write_does_not_back_a_send_but_backs_a_create(login_as, tools):
    fake.script({"tool": "core_note_thing"}, "I've added the note. I sent it to the team.")
    assert corrections(chat(login_as("member"), message="note it")) == [
        "\n\n" + completion_claims.NOTE.format(verbs="sent")
    ]


def test_a_pending_or_denied_write_does_not_back_a_claim(login_as, tools):
    a = login_as("member")
    fake.script({"tool": "core_send_thing"}, "I sent it.")
    evs = chat(a, message="send it")
    assert corrections(evs)  # waiting for approval is not sent
    [card], cid = of(evs, "confirm"), evs[0]["id"]
    a.post("/api/agent/confirm", json={"tool_run_id": card["tool_run_id"], "decision": "deny"})
    fake.script("I sent it.")
    assert corrections(chat(a, conversation_id=cid))
