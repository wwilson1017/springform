"""The skills review (`core.skills_review`, agent.md "Skills"): it reads only conversations that are
not private, not tainted and name no record the system principal cannot read, makes one model call
with no tools, and writes proposals nobody sees until an admin approves them."""

import json
import re

import pytest

from backend.core import db as core_db, settings, skills
from backend.core.agent import agents, assembly
from backend.core.agent.providers import fake
from backend.core.skills import jobs, review

NOW = "2026-11-20T09:00:00Z"
GOOD = {
    "conversation": 1,
    "name": "weekly-stock-count",
    "description": "Count the stock and log it every Monday",
    "body": "Use on Mondays.\n1. List each shelf.\n2. Count it.",
}


@pytest.fixture(autouse=True)
def _fake(monkeypatch):
    monkeypatch.setenv("AGENT_FAKE_PROVIDER", "1")
    fake.reset()
    yield
    fake.reset()


@pytest.fixture
def on(app):
    settings.set_setting(jobs.ENABLED_SETTING, True, None)


@pytest.fixture
def member(make_user, app):
    agents.ensure_default()  # the lifespan is not run here
    return make_user("member")


def conversation(
    user, messages, *, private=False, tainted=False, turns=1, records=None, tool="example_get_widget"
) -> int:
    """A conversation with its rows and `turns` finished turns; `records` adds a done tool run
    naming them (None: no run)."""
    with core_db.transaction() as conn:
        cid = core_db.insert_in(
            conn,
            """INSERT INTO core_agent_conversations (user_id, agent_id, is_private, tainted, created_at, updated_at)
               VALUES (?, (SELECT id FROM core_agents WHERE slug = 'whisk'), ?, ?, ?, ?)""",
            (user.id, int(private), int(tainted), NOW, NOW),
        )
        for role, text, *calls in messages:
            content = {"text": text, **({"tool_calls": [{"tool": t, "args": {}} for t in calls]} if calls else {})}
            conn.execute(
                "INSERT INTO core_agent_messages (conversation_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (cid, role, json.dumps(content), NOW),
            )
        if records is not None:
            conn.execute(
                """INSERT INTO core_agent_tool_runs (conversation_id, tool_use_id, tool, status, user_id, source,
                       requested_at, records) VALUES (?, 'tu1', ?, 'done', ?, 'chat', ?, ?)""",
                (cid, tool, user.id, NOW, json.dumps(records)),
            )
        for _ in range(turns):
            turn(conn, cid, user)
    return cid


def turn(conn, cid, user, status="done") -> int:
    return core_db.insert_in(
        conn,
        "INSERT INTO core_agent_turns (conversation_id, user_id, status, started_at) VALUES (?, ?, ?, ?)",
        (cid, user.id, status, NOW),
    )


def widget(owner, private: bool) -> int:
    with core_db.transaction() as conn:
        return core_db.insert_in(
            conn,
            """INSERT INTO example_widgets (name, owner_user_id, is_private, created_at, updated_at)
               VALUES ('Gizmo', ?, ?, ?, ?)""",
            (owner.id, int(private), NOW, NOW),
        )


def work(marker: str) -> list:
    return [
        ("user", f"Please count the stock {marker}"),
        ("assistant", "Listing the shelves first.", "example_list_widgets"),
        ("assistant", f"Counted every shelf {marker}."),
    ]


def proposals() -> list[dict]:
    return core_db.rows("SELECT * FROM core_agent_skills ORDER BY id")


def ledger() -> list[dict]:
    return core_db.rows("SELECT * FROM core_agent_skill_reviews ORDER BY id")


def test_jobs_are_registered(app):
    from backend.core import scheduler

    registered = scheduler.jobs()
    assert registered["core.skills_review"].every == 300 and registered["core.skills_review"].fn is jobs.run_review
    assert registered["core.skills_curate"].at == "03:15" and registered["core.skills_curate"].fn is jobs.run_curate


def test_the_review_proposes_and_records_its_call(on, member, model_requests):
    cid = conversation(member, work("open-marker"), turns=10)
    fake.script(json.dumps({"skills": [GOOD]}))
    result = jobs.run_review()
    assert result == {"status": "ok", "review": "ok", "conversations": 1, "proposals": 1}
    (call,) = model_requests
    assert call["tools"] == []  # no tools: the review only reads what it is given
    assert (
        "open-marker" in call["messages"][0]["content"]
        and "[tools: example_list_widgets]" in call["messages"][0]["content"]
    )
    (row,) = proposals()
    assert (row["status"], row["author"], row["source_conversation_id"]) == ("proposed", "agent", cid)
    assert row["name"] == GOOD["name"] and row["revises_id"] is None
    usage = core_db.rows("SELECT source, model FROM core_agent_usage")
    assert usage == [{"source": "skills", "model": "fake-default"}]
    assert ledger()[0]["through_turn_id"] == 10 and ledger()[0]["proposals"] == 1
    # proposed, so invisible to the agent
    assert skills.index_in(core_db.get_conn()) == ""
    assert jobs.run_review() == {"status": "skipped", "reason": "not_due"}  # the watermark moved


def test_the_review_never_reads_private_conversations(on, member, make_user, model_requests):
    other = make_user("member")
    conversation(member, work("open-marker"), turns=4)
    conversation(member, work("private-marker"), private=True, turns=3)
    conversation(member, work("tainted-marker"), tainted=True, turns=3)
    conversation(member, work("hidden-marker"), records=[["example.widget", widget(other, private=True)]])
    conversation(member, work("plain-marker"))  # no tool run at all
    # a reply that restates a search of the user's other conversations (private ones included)
    conversation(member, work("searched-marker"), records=[], tool="core_search_conversations")
    conversation(member, work("reminder-marker"), records=[], tool="core_list_my_reminders")
    fake.script('{"skills": []}')
    assert jobs.run_review()["review"] == "ok"
    (call,) = model_requests
    prompt = call["messages"][0]["content"]
    assert "open-marker" in prompt and "plain-marker" in prompt
    for marker in ("private-marker", "tainted-marker", "hidden-marker", "searched-marker", "reminder-marker"):
        assert marker not in prompt


def test_a_run_of_unknown_provenance_or_a_readable_record_is_judged_as_the_system_principal(member, make_user):
    other = make_user("member")
    shared = conversation(member, work("a"), records=[["example.widget", widget(other, private=False)]])
    hidden = conversation(member, work("b"), records=[["example.widget", widget(other, private=True)]])
    unknown = conversation(member, work("c"))
    with core_db.transaction() as conn:
        conn.execute(
            """INSERT INTO core_agent_tool_runs (conversation_id, tool_use_id, tool, status, user_id, source,
                   requested_at, records) VALUES (?, 'tu2', 'core_x', 'done', ?, 'chat', ?, NULL)""",
            (unknown, member.id, NOW),
        )
        assert review.eligible_in(conn, shared) and not review.eligible_in(conn, hidden)
        assert not review.eligible_in(conn, unknown)


def test_a_conversation_made_private_during_the_review_yields_nothing(member):
    cid = conversation(member, work("open-marker"), turns=10)

    def flip(system, prompt):
        assert not core_db.in_transaction()  # the model call holds no write lock
        with core_db.transaction() as conn:
            conn.execute("UPDATE core_agent_conversations SET is_private = 1 WHERE id = ?", (cid,))
        return json.dumps({"skills": [GOOD]})

    assert review.run(flip)["review"] == "discarded"
    assert proposals() == [] and ledger()[0]["status"] == "discarded"


def test_a_conversation_tainted_during_the_review_yields_nothing(member):
    cid = conversation(member, work("open-marker"), turns=10)

    def taint(system, prompt):
        with core_db.transaction() as conn:
            conn.execute("UPDATE core_agent_conversations SET tainted = 1 WHERE id = ?", (cid,))
        return json.dumps({"skills": [GOOD]})

    assert review.run(taint)["review"] == "discarded" and proposals() == []


def test_the_review_waits_for_its_switch_ten_turns_and_a_key(app, member, model_requests, monkeypatch):
    assert jobs.run_review() == {"status": "skipped", "reason": "disabled"}
    settings.set_setting(jobs.ENABLED_SETTING, True, None)
    cid = conversation(member, work("x"), turns=9)
    with core_db.transaction() as conn:
        turn(conn, cid, member, "error")
        turn(conn, cid, member, "cancelled")
    assert jobs.run_review() == {"status": "skipped", "reason": "not_due"}
    monkeypatch.delenv("AGENT_FAKE_PROVIDER")
    with core_db.transaction() as conn:
        turn(conn, cid, member)
    assert jobs.run_review() == {"status": "skipped", "reason": "no_provider"}
    assert ledger() == []  # the watermark did not move: a key added later reviews these turns
    with core_db.transaction() as conn:
        for i in range(review.MAX_PENDING):
            skills.create_in(conn, f"waiting-{i}", "Waiting", "Body.", author="agent", status="proposed")
    assert jobs.run_review() == {"status": "skipped", "reason": "queue_full"}
    assert model_requests == []


def test_a_turn_that_finishes_late_is_counted_by_the_next_review(member):
    cid = conversation(member, work("x"), turns=0)
    with core_db.transaction() as conn:
        slow = turn(conn, cid, member, "running")
        for _ in range(10):
            turn(conn, cid, member)
    # the ten later turns sit above a running one: not yet a full window
    assert review.run(lambda s, p: '{"skills": []}') == {"status": "skipped", "reason": "not_due"}
    with core_db.transaction() as conn:
        conn.execute("UPDATE core_agent_turns SET status = 'done' WHERE id = ?", (slow,))
    assert review.run(lambda s, p: '{"skills": []}')["review"] == "ok"
    assert ledger()[0]["through_turn_id"] == 11


def test_a_bad_reply_writes_nothing_and_items_are_held_to_the_rules(member, admin_user):
    conversation(member, work("x"), turns=10)
    assert review.run(lambda s, p: "Here are some skills!")["review"] == "bad_reply"
    assert proposals() == [] and ledger()[-1]["status"] == "bad_reply"

    old = skills.create("weekly-stock-count", "Count the stock", "1. Count.", admin_user)
    with core_db.transaction() as conn:
        skills.create_in(conn, "already-rejected", "Old", "Body.", author="agent", status="rejected")
    items = [
        {**GOOD, "body": "1. Count better."},  # same name as an active skill: an edit of it
        {**GOOD, "name": "Bad Name!"},
        {**GOOD, "name": "already-rejected"},
        {**GOOD, "name": "from-nowhere", "conversation": 7},
        {**GOOD, "name": "kept-two", "description": "x" * 90},  # cut to 60
        {**GOOD, "name": "kept-two"},  # a duplicate within the reply
        {**GOOD, "name": "kept-three", "revises": "weekly-stock-count"},
        {**GOOD, "name": "one-too-many"},
    ]
    conversation(member, work("y"), turns=10)
    reply = "```json\n" + json.dumps({"skills": items}) + "\n```"
    assert review.run(lambda s, p: reply)["proposals"] == 3
    rows = {r["name"]: r for r in proposals() if r["status"] == "proposed"}
    assert set(rows) == {"weekly-stock-count", "kept-two", "kept-three"}
    assert rows["weekly-stock-count"]["revises_id"] == old["id"] == rows["kept-three"]["revises_id"]
    assert len(rows["kept-two"]["description"]) == 60


def test_the_prompt_lists_what_exists_and_fences_the_conversations(member, admin_user):
    skills.create("weekly-stock-count", "Count the stock", "1. Count.", admin_user)
    conversation(member, work("x"), turns=10)
    seen = []
    review.run(lambda s, p: seen.append(p) or '{"skills": []}')
    (prompt,) = seen
    assert "- weekly-stock-count: Count the stock" in prompt
    assert re.search(r'<(conversation_[0-9a-f]{12}) n="1">\n.*\n</\1>', prompt, re.S)


def test_the_prompt_bans_the_three_shapes_and_does_not_push_for_output():
    text = review.SYSTEM_PROMPT
    assert "does not work" in text and "dead end" in text and "one-off story" in text
    assert "An empty list is the normal answer" in text


def test_an_approved_proposal_reaches_the_prompt(on, member, admin_user):
    conversation(member, work("x"), turns=10)
    fake.script(json.dumps({"skills": [GOOD]}))
    jobs.run_review()
    (row,) = proposals()
    assert "weekly-stock-count" not in assembly.skills_index()
    skills.move(row["id"], "approve", admin_user)
    assert f"- weekly-stock-count: {GOOD['description']}" in assembly.skills_index()


@pytest.fixture
def admin_user(make_user, app):
    return make_user("admin")
