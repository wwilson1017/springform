import sys
import types

import pytest

from backend.core import db as core_db, memory, scheduler, settings
from backend.core.memory import dreaming, facts, jobs, observer

LLM = "backend.core.agent.llm"
# Minimal stand-ins for the engine's tables (created only where the engine's migration has not).
CONVERSATION_TABLES = """
CREATE TABLE IF NOT EXISTS core_agent_conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, is_private INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS core_agent_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id INTEGER NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL);
"""


@pytest.fixture
def llm(db, monkeypatch):
    """A fake backend.core.agent.llm: records calls, returns `.reply`, or raises when it is None."""
    mod = types.ModuleType(LLM)
    mod.NoProviderConfigured = type("NoProviderConfigured", (Exception,), {})
    mod.calls, mod.reply, mod.during_call = [], '{"facts": []}', None

    def complete(system, prompt, tier="standard"):
        assert not core_db.in_transaction(), "LLM call inside transaction()"
        mod.calls.append({"system": system, "prompt": prompt, "tier": tier})
        if mod.during_call:
            mod.during_call()
        if mod.reply is None:
            raise mod.NoProviderConfigured()
        return mod.reply

    mod.complete = complete
    monkeypatch.setitem(sys.modules, LLM, mod)
    core_db.get_conn().executescript(CONVERSATION_TABLES)
    settings.set_setting(jobs.ENABLED_SETTING, True, None)
    return mod


def conversation(user_id: int, messages: list[tuple[str, str]], private: bool = False) -> int:
    with core_db.transaction() as conn:
        cid = conn.execute(
            "INSERT INTO core_agent_conversations (user_id, is_private) VALUES (?, ?)", (user_id, int(private))
        ).lastrowid
        say(conn, cid, messages)
    return cid


def say(conn, cid: int, messages: list[tuple[str, str]]) -> None:
    for role, content in messages:
        conn.execute("INSERT INTO core_agent_messages (conversation_id, role, content) VALUES (?, ?, ?)", (cid, role, content))
    memory.after_turn(conn, cid)


def pending() -> dict[int, int]:
    return {r["conversation_id"]: r["pending"] for r in core_db.rows("SELECT * FROM core_agent_observations")}


def test_job_is_registered_nightly(app):
    job = scheduler.jobs()["core.agent_nightly"]
    assert job.at == "02:00" and job.fn is jobs.nightly


def test_skips_when_disabled_without_llm_or_without_a_provider(llm, make_user, monkeypatch):
    cid = conversation(make_user().id, [("user", "Our wholesale price is 30 dollars a cake, every order.")])
    llm.reply = None
    assert jobs.nightly() == {"status": "skipped", "reason": "no_provider"}
    settings.set_setting(jobs.ENABLED_SETTING, False, None)
    assert jobs.nightly() == {"status": "skipped", "reason": "disabled"}
    settings.set_setting(jobs.ENABLED_SETTING, True, None)
    monkeypatch.setitem(sys.modules, LLM, None)  # the engine branch is not there
    assert jobs.nightly() == {"status": "skipped", "reason": "no_llm_module"}
    assert len(llm.calls) == 1 and facts.list_facts() == [] and pending() == {cid: 1}
    assert observer.conversation_tables_exist(core_db.sqlite3.connect(":memory:")) is False


def test_extracts_business_facts_as_the_system_user_and_never_reads_private(llm, make_user):
    alice, bob = make_user(), make_user()
    open_c = conversation(alice.id, [
        ("user", "Note that our wholesale price is 30 dollars per cake."),
        ("assistant", "ASSISTANT-ROW tool output from an email"),
        ("user", "Also the farmers market stall runs every Saturday morning."),
    ])  # fmt: skip
    private_c = conversation(bob.id, [("user", "PRIVATE-ROW my hearing is on Friday; the flour supplier changed")], private=True)
    llm.reply = '```json\n{"facts": ["Wholesale price is 30 dollars per cake.", "The market stall runs every Saturday.", 7, "ok"]}\n```'

    result = jobs.nightly()
    assert result["observer"] == {"status": "ok", "conversations": 1, "facts": 2}
    assert result["dreaming"] == {"facts": 2, "merged": 0}
    assert len(llm.calls) == 1 and llm.calls[0]["tier"] == "light"
    assert "personal" in llm.calls[0]["system"] and "wholesale price" in llm.calls[0]["prompt"]
    assert "PRIVATE-ROW" not in llm.calls[0]["prompt"] and "ASSISTANT-ROW" not in llm.calls[0]["prompt"]
    stored = facts.list_facts()
    assert {(f["author_user_id"], f["source_conversation_id"]) for f in stored} == {(0, open_c)}
    assert all(f["tags"] == ["observed"] for f in stored)
    assert pending() == {open_c: 0, private_c: 0}

    llm.calls.clear()
    assert jobs.nightly()["observer"]["conversations"] == 0 and llm.calls == []  # nothing new
    with core_db.transaction() as conn:
        say(conn, open_c, [("user", "From next month the cafe opens at 8 on Sundays.")])
    jobs.nightly()
    assert len(llm.calls) == 1 and "Sundays" in llm.calls[0]["prompt"] and "wholesale" not in llm.calls[0]["prompt"]


def test_a_conversation_made_private_during_the_call_yields_nothing(llm, make_user):
    cid = conversation(make_user().id, [("user", "Our catering minimum is twelve cakes per order.")])

    def go_private():
        with core_db.transaction() as conn:
            conn.execute("UPDATE core_agent_conversations SET is_private = 1 WHERE id = ?", (cid,))

    llm.during_call, llm.reply = go_private, '{"facts": ["Catering minimum is twelve cakes."]}'
    assert jobs.nightly()["observer"]["facts"] == 0 and facts.list_facts() == []


def test_a_failed_or_garbled_reply_writes_nothing(llm, make_user):
    cid = conversation(make_user().id, [("user", "Our catering minimum is twelve cakes per order.")])
    llm.reply = "Sure! Here are the facts: catering minimum is twelve."
    assert jobs.nightly()["observer"]["facts"] == 0 and facts.list_facts() == [] and pending() == {cid: 0}

    def boom():
        raise RuntimeError("provider down")

    with core_db.transaction() as conn:
        say(conn, cid, [("user", "And we deliver within ten miles of the bakery.")])
    llm.during_call = boom
    assert jobs.nightly()["observer"]["conversations"] == 0 and pending() == {cid: 1}  # retried next night


def test_dreaming_merges_duplicates_into_the_oldest(db, make_user):
    u = make_user()
    keep = facts.remember("Deliveries go out on Tuesdays.", author_user_id=u.id, tags=["delivery"])
    dup = facts.remember("deliveries go out on tuesdays", author_user_id=0, tags=["observed"])
    reordered = facts.remember("On Tuesdays, deliveries go out", author_user_id=0)
    other = facts.remember("Deliveries go out on Fridays", author_user_id=u.id)

    assert dreaming.consolidate() == {"facts": 4, "merged": 2}
    assert {f["id"] for f in facts.list_facts()} == {keep["id"], other["id"]}
    assert facts.get(keep["id"])["tags"] == ["delivery", "observed"]
    assert facts.get(dup["id"])["superseded_by"] == keep["id"] == facts.get(reordered["id"])["superseded_by"]
    assert facts.get(dup["id"])["invalidated_by"] == 0
    assert dreaming.consolidate() == {"facts": 2, "merged": 0}
