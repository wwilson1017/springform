"""Always-allow rules and deny reasons (agent.md §6), end to end over HTTP with the FakeProvider."""

import json

import pytest

from backend.core import db as core_db
from backend.core.agent import approval_rules, assembly, engine, history
from backend.core.agent.providers import fake
from backend.core.agent.providers.fake import FakeProvider
from backend.core.agent.spec import ToolSpec

SCHEMA = {"type": "object", "properties": {}}


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


def call(client, tool: str, args: dict, cid: int | None = None) -> tuple[int, list[dict]]:
    """One turn in which the model calls `tool`; (conversation id, events)."""
    fake.script({"tool": tool, "args": args}, "Done or waiting.")
    evs = chat(client, message=f"use {tool}", **({"conversation_id": cid} if cid else {}))
    return evs[0]["id"], evs


def confirms(evs) -> list[dict]:
    return [e for e in evs if e["type"] == "confirm"]


def confirm(client, run_id: int, decision: str, **extra) -> dict:
    r = client.post("/api/agent/confirm", json={"tool_run_id": run_id, "decision": decision, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def save_rule(client, tool="example_create_widget", args=None) -> int:
    cid, evs = call(client, tool, args or {"name": "First"})
    card = confirms(evs)[0]
    assert card["can_always_allow"] is True
    assert confirm(client, card["tool_run_id"], "approve", always_allow=True)["rule_saved"] is True
    return cid


def rules() -> list[dict]:
    return core_db.rows("SELECT * FROM core_agent_approval_rules ORDER BY id")


def test_rule_skips_the_card_for_its_tool_only(login_as):
    a, b = login_as("member"), login_as("member")
    cid = save_rule(a)
    _, evs = call(a, "example_create_widget", {"name": "Second"}, cid)
    assert not confirms(evs) and [e["status"] for e in evs if e["type"] == "tool_end"] == ["done"]
    _, evs = call(a, "core_create_organization", {"name": "Acme Holdings"}, cid)  # another tool still asks
    assert confirms(evs)
    _, evs = call(b, "example_create_widget", {"name": "Theirs"})  # another user still asks
    assert confirms(evs)
    _, evs = call(a, "example_create_widget", {"name": "New chat"})  # a new conversation with the agent: covered
    assert not confirms(evs)


def test_voided_rule_stops_applying(login_as):
    a, b = login_as("member"), login_as("member")
    cid = save_rule(a)
    [rule] = a.get("/api/agent/approval-rules").json()
    assert rule["tool"] == "example_create_widget" and rule["agent_slug"] == "whisk"
    assert b.get("/api/agent/approval-rules").json() == []
    assert b.delete(f"/api/agent/approval-rules/{rule['id']}").status_code == 404
    assert a.delete(f"/api/agent/approval-rules/{rule['id']}").json() == {"voided": True}
    assert a.delete(f"/api/agent/approval-rules/{rule['id']}").status_code == 404
    [row] = rules()  # voided, never deleted
    assert row["voided_at"] and row["void_reason"] == "removed in settings"
    assert a.get("/api/agent/approval-rules").json() == []
    _, evs = call(a, "example_create_widget", {"name": "Again"}, cid)
    assert confirms(evs)


def test_rule_never_applies_in_a_tainted_conversation(login_as):
    a = login_as("member")
    cid = save_rule(a)
    history.mark_tainted(cid)
    _, evs = call(a, "example_create_widget", {"name": "Tainted"}, cid)
    [card] = confirms(evs)
    assert card["can_always_allow"] is False
    conv = a.get(f"/api/agent/conversations/{cid}").json()
    pending = [c for m in conv["messages"] for c in m["tool_calls"] if c["status"] == "pending"]
    assert [c["can_always_allow"] for c in pending] == [False]


def test_always_allow_is_revalidated_at_approve(login_as):
    a = login_as("member")
    cid, evs = call(a, "example_create_widget", {"name": "Clean card"})
    history.mark_tainted(cid)  # tainted after the card was shown
    out = confirm(a, confirms(evs)[0]["tool_run_id"], "approve", always_allow=True)
    assert out["status"] == "done" and out["rule_saved"] is False and rules() == []

    admin = login_as("admin")  # an always-ask tool never gets a rule
    _, evs = call(admin, "core_context_file_write", {"filename": "notes.md", "content": "Hello"})
    card = confirms(evs)[0]
    assert card["can_always_allow"] is False
    out = confirm(admin, card["tool_run_id"], "approve", always_allow=True)
    assert out["rule_saved"] is False and rules() == []


def test_approve_without_always_allow_answers_as_before(login_as):
    a = login_as("member")
    _, evs = call(a, "example_create_widget", {"name": "Plain"})
    assert "rule_saved" not in confirm(a, confirms(evs)[0]["tool_run_id"], "approve")


def _spec(**kw) -> ToolSpec:
    base = {"name": "core_t", "description": "t", "input_schema": SCHEMA, "writes": True}
    return ToolSpec(**{**base, **kw})


@pytest.mark.parametrize(
    "spec, args, tainted, eligible",
    [
        (_spec(), {}, False, True),
        (_spec(), {}, True, False),
        (_spec(writes=False), {}, False, False),
        (_spec(always_confirm=True), {}, False, False),
        (_spec(server_url="https://mcp.example.com", always_confirm=True), {}, False, False),
        (_spec(external_effect=True), {}, False, False),
        (_spec(destructive=True), {}, False, False),
        (_spec(hides_when=lambda a: a.get("private", False)), {"private": True}, False, False),
        (_spec(hides_when=lambda a: a.get("private", False)), {}, False, True),
        (_spec(hides_when=lambda a: 1 / 0), {}, False, False),
    ],
    ids=["local", "tainted", "read", "always-ask", "remote", "external", "destructive", "hides", "shows", "raises"],
)
def test_rule_eligible(spec, args, tainted, eligible):
    assert engine.rule_eligible(spec, args, tainted) is eligible


def test_archiving_a_deal_never_offers_always_allow():
    from backend.core.agent import registry as tool_registry

    spec = tool_registry.get("crm_archive_deal")
    assert spec is not None and engine.rule_eligible(spec, {"deal_id": 1, "reason": "duplicate"}, False) is False


def test_failed_rule_lookup_keeps_the_card(login_as, monkeypatch):
    a = login_as("member")
    cid = save_rule(a)

    def boom(*args):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(approval_rules, "live", boom)
    _, evs = call(a, "example_create_widget", {"name": "Locked"}, cid)
    assert confirms(evs)


# ── Deny reasons and the breaker ──


def test_deny_reason_is_stored_bounded_and_read_by_the_model(login_as):
    a = login_as("member")
    cid, evs = call(a, "example_create_widget", {"name": "Red"})
    out = confirm(a, confirms(evs)[0]["tool_run_id"], "deny", reason="  Wrong\n colour,   use green ")
    assert out == {"status": "denied"}
    assert history.get_tool_run(confirms(evs)[0]["tool_run_id"])["deny_reason"] == "Wrong colour, use green"
    flat = json.dumps(assembly.assemble_messages(FakeProvider("fake"), cid))
    assert "Wrong colour, use green" in flat and "Do not retry it or work around it" in flat

    _, evs = call(a, "example_create_widget", {"name": "Blue"}, cid)
    run_id = confirms(evs)[0]["tool_run_id"]
    too_long = a.post("/api/agent/confirm", json={"tool_run_id": run_id, "decision": "deny", "reason": "x" * 501})
    assert too_long.status_code == 422
    confirm(a, run_id, "deny")
    assert history.get_tool_run(run_id)["deny_reason"] is None


def test_breaker_counts_denied_steps_since_the_last_user_message(login_as):
    a = login_as("member")
    fake.script(
        [
            {"tool": "example_create_widget", "args": {"name": "One"}},
            {"tool": "example_create_widget", "args": {"name": "Two"}},
        ],
        "Both wait.",
    )
    evs = chat(a, message="make two widgets")
    cid = evs[0]["id"]
    for card in confirms(evs):  # two denials in one step count once
        confirm(a, card["tool_run_id"], "deny")
    for name in ("Three", "Four"):
        fake.script({"tool": "example_create_widget", "args": {"name": name}}, "Waiting.")
        for card in confirms(chat(a, conversation_id=cid)):
            confirm(a, card["tool_run_id"], "deny")

    def stops() -> int:
        return json.dumps(assembly.assemble_messages(FakeProvider("fake"), cid)).count("stop and report to the user")

    assert stops() == 1  # only the third denied step carries it
    _, evs = call(a, "example_create_widget", {"name": "Five"}, cid)  # a new user message resets the count
    confirm(a, confirms(evs)[0]["tool_run_id"], "deny")
    assert stops() == 1


def test_model_content_reads_the_reason_from_a_full_row(login_as):
    """compaction and result_cap pass whole run rows; dispatch passes a status-only dict."""
    a = login_as("member")
    _, evs = call(a, "example_create_widget", {"name": "Row"})
    run_id = confirms(evs)[0]["tool_run_id"]
    confirm(a, run_id, "deny", reason="Not today")
    content = json.loads(history.model_content(core_db.must(history.get_tool_run(run_id))))
    assert content["status"] == "denied_by_user" and content["reason"] == "Not today"
    assert json.loads(history.model_content({"status": "denied"}))["status"] == "denied_by_user"
    breaker = json.loads(history.model_content({"status": "denied"}, denials=3))["message"]
    assert "stop and report to the user" in breaker
