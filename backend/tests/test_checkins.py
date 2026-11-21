"""Whisk check-ins: schedules, the API, and the job that runs them as their owner with look-up tools
only (agent.md §5, "Check-ins").

Job tests run inside the app's lifespan (`with TestClient(app)`), so the scheduler's loop exists for
`scheduler.run_on_loop`, and call `service.run_due()` from the test thread like the job would.
"""

import asyncio
import json
import threading
import time
from datetime import datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from backend.core import clock, db as core_db, scheduler
from backend.core.agent import agents, approval_rules, detached, dispatch, engine, history, intents, registry
from backend.core.agent.providers import fake
from backend.core.agent.providers.fake import FakeProvider
from backend.core.agent.turn_hooks import TurnState
from backend.core.checkins import schedule, service
from backend.core.errors import Invalid, NotFound
from backend.testing.fixtures import Client

CHICAGO = ZoneInfo("America/Chicago")


@pytest.fixture(autouse=True)
def _fake(monkeypatch):
    monkeypatch.setenv("AGENT_FAKE_PROVIDER", "1")
    fake.reset()
    yield
    fake.reset()


def _wait(predicate, seconds: float = 5) -> None:
    deadline = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < deadline, "timed out waiting"
        time.sleep(0.02)


def _job_idle() -> bool:
    return core_db.one(
        "SELECT 1 FROM core_job_runs WHERE job = ? AND status != 'running'", (service.JOB,)
    ) is not None and not core_db.one(
        "SELECT 1 FROM core_job_runs WHERE job = ? AND status = 'running'", (service.JOB,)
    )


@pytest.fixture
def live(app, login_as):
    """(client, owner): a signed-in member inside a running lifespan, after the job's first pass."""
    who = login_as("member")
    with Client(app, headers={"Authorization": f"Bearer {who.cookies.get('sf_session')}"}) as c:
        _wait(_job_idle)
        c.principal = who.principal
        yield c


def make(c, prompt="Anything overdue?", schedule_text="every:60", name="Morning look") -> dict:
    r = c.post("/api/agent/checkins", json={"name": name, "prompt": prompt, "schedule": schedule_text})
    assert r.status_code == 200, r.text
    return r.json()


def due(checkin_id: int, at: str = "2000-01-01T00:00:00Z") -> None:
    with core_db.transaction() as conn:
        conn.execute("UPDATE core_agent_checkins SET next_run_at = ? WHERE id = ?", (at, checkin_id))


def row(checkin_id: int) -> dict:
    return core_db.must(core_db.one("SELECT * FROM core_agent_checkins WHERE id = ?", (checkin_id,)))


def count(sql: str, params=()) -> int:
    return core_db.must(core_db.one(f"SELECT count(*) AS n FROM {sql}", params))["n"]


def notes(user_id: int) -> list[dict]:
    return core_db.rows("SELECT * FROM core_notifications WHERE user_id = ? ORDER BY id", (user_id,))


# ── Schedules ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "parsed"),
    [
        ("every:60", ("every", 60, "00:00")),
        (" Every:15 ", ("every", 15, "00:00")),
        ("daily@09:00", ("daily", 0, "09:00")),
        ("weekly:fri@17:30", ("weekly", 4, "17:30")),
    ],
)
def test_schedule_parses_the_three_forms(text, parsed):
    kind, n, at = schedule.parse(text)
    assert (kind, n, at.strftime("%H:%M")) == parsed
    assert schedule.normalize(text) == text.strip().lower()


@pytest.mark.parametrize(
    "text", ["", "every:14", "every:10081", "daily@24:00", "daily@9:00", "weekly:xyz@09:00", "hourly"]
)
def test_schedule_refuses_anything_else(text):
    with pytest.raises(Invalid):
        schedule.parse(text)


def test_next_run_is_strictly_after_and_dst_safe():
    utc = timezone.utc
    after = datetime(2026, 11, 2, 15, 0, tzinfo=utc)  # Monday 09:00 in Chicago (CST)
    assert schedule.next_run("every:90", after, CHICAGO) == datetime(2026, 11, 2, 16, 30, tzinfo=utc)
    assert schedule.next_run("daily@10:00", after, CHICAGO) == datetime(2026, 11, 2, 16, 0, tzinfo=utc)
    assert schedule.next_run("daily@09:00", after, CHICAGO) == datetime(2026, 11, 3, 15, 0, tzinfo=utc)
    assert schedule.next_run("weekly:mon@09:00", after, CHICAGO) == datetime(2026, 11, 9, 15, 0, tzinfo=utc)
    assert schedule.next_run("weekly:mon@10:00", after, CHICAGO) == datetime(2026, 11, 2, 16, 0, tzinfo=utc)
    assert schedule.next_run("weekly:wed@09:00", after, CHICAGO) == datetime(2026, 11, 4, 15, 0, tzinfo=utc)
    # 09:00 stays 09:00 local across the spring change (CST -> CDT on 2027-03-14).
    before = datetime(2027, 3, 13, 16, 0, tzinfo=utc)
    assert schedule.next_run("daily@09:00", before, CHICAGO) == datetime(2027, 3, 14, 14, 0, tzinfo=utc)


@pytest.mark.parametrize(
    ("reply", "silent"),
    [
        ("[SILENT]", True),
        ("  [SILENT]\n", True),
        ("**[SILENT]**", True),
        ("`[SILENT]`", True),
        ("Two invoices are overdue.\n[SILENT]", False),
        ("[SILENT]\nNothing new.", False),
        ("I would say [SILENT] but two are overdue", False),
        ("", False),
    ],
)
def test_only_the_whole_reply_is_silent(reply, silent):
    assert service.is_silent(reply) is silent


# ── The API ───────────────────────────────────────────────────────────────────


def test_crud_is_the_callers_own(login_as, freeze):
    freeze("2026-11-02T15:00:00Z")
    a, b = login_as("member"), login_as("member")
    made = make(a, schedule_text="daily@09:30")
    assert made["enabled"] is True and made["failures"] == 0 and made["last_status"] is None
    assert made["next_run_at"] > "2026-11-02T15:00:00"
    assert [c["id"] for c in a.get("/api/agent/checkins").json()] == [made["id"]]
    assert b.get("/api/agent/checkins").json() == []
    url = f"/api/agent/checkins/{made['id']}"
    assert b.patch(url, json={"enabled": False}).status_code == 404
    assert b.post(f"{url}/run").status_code == 404
    assert b.delete(url).status_code == 404

    assert a.patch(url, json={"enabled": False}).json()["enabled"] is False
    assert a.post(f"{url}/run").status_code == 409
    with core_db.transaction() as conn:
        conn.execute("UPDATE core_agent_checkins SET failures = 7 WHERE id = ?", (made["id"],))
    resumed = a.patch(url, json={"enabled": True}).json()
    assert resumed["enabled"] is True and resumed["failures"] == 0
    r = a.post(f"{url}/run")
    assert r.status_code == 202 and r.json()["next_run_at"] <= clock.now_iso()
    assert a.delete(url).status_code == 204
    assert a.get("/api/agent/checkins").json() == []


def test_create_validates(login_as):
    a = login_as("member")
    for body in (
        {"name": "x", "prompt": "y", "schedule": "every:5"},
        {"name": "   ", "prompt": "y", "schedule": "every:60"},
        {"name": "x", "prompt": "  ", "schedule": "every:60"},
    ):
        assert a.post("/api/agent/checkins", json=body).status_code == 422
    for i in range(service.MAX_PER_USER):
        make(a, name=f"n{i}")
    assert a.post("/api/agent/checkins", json={"name": "x", "prompt": "y", "schedule": "every:60"}).status_code == 422


# ── The job ───────────────────────────────────────────────────────────────────


def test_a_reply_lands_in_a_conversation_and_a_notification(live, login_as):
    other = login_as("member")
    c = make(live, prompt="Anything overdue?")
    due(c["id"])
    fake.script("Two invoices are overdue.")
    assert service.run_due() == {"delivered": 1, "silent": 0, "failed": 0}
    owner = live.principal.id
    convs = core_db.rows("SELECT * FROM core_agent_conversations WHERE user_id = ?", (owner,))
    assert len(convs) == 1
    first = core_db.must(
        core_db.one("SELECT content FROM core_agent_messages WHERE conversation_id = ? ORDER BY id", (convs[0]["id"],))
    )
    assert json.loads(first["content"])["text"] == "Anything overdue?"
    [n] = notes(owner)
    assert (n["title"], n["message"], n["link"]) == (
        "Morning look",
        "Two invoices are overdue.",
        f"/whisk/{convs[0]['id']}",
    )
    assert notes(other.principal.id) == []
    r = row(c["id"])
    assert (r["last_status"], r["failures"]) == ("ok", 0) and r["next_run_at"] > clock.now_iso()
    usage = core_db.rows("SELECT source, user_id FROM core_agent_usage")
    assert usage and all(u == {"source": "checkin", "user_id": owner} for u in usage)


def test_silent_sends_nothing_and_leaves_no_conversation(live):
    c = make(live)
    due(c["id"])
    fake.script({"tool": "core_memory_search", "args": {"query": "overdue"}}, "[SILENT]")
    assert service.run_due()["silent"] == 1
    owner = live.principal.id
    assert count("core_agent_conversations WHERE user_id = ?", (owner,)) == 0
    assert notes(owner) == []
    assert row(c["id"])["last_status"] == "silent"
    usage = core_db.rows("SELECT source, user_id FROM core_agent_usage")
    assert len(usage) == 2 and all(u == {"source": "checkin", "user_id": owner} for u in usage)
    runs = core_db.rows("SELECT tool, source, status FROM core_agent_tool_runs")
    assert runs == [{"tool": "core_memory_search", "source": "job", "status": "done"}]


def test_a_due_checkin_runs_once(live, model_requests):
    c = make(live)
    due(c["id"])
    fake.script("All good.")
    service.run_due()
    calls = len(model_requests)
    assert service.run_due() == {"delivered": 0, "silent": 0, "failed": 0}
    assert len(model_requests) == calls and row(c["id"])["next_run_at"] > clock.now_iso()


def test_a_missed_backlog_runs_once_then_waits_for_a_future_slot(live, model_requests):
    c = make(live, schedule_text="daily@09:00")
    due(c["id"], clock.ago(3 * 86400))  # three days of missed slots
    fake.script("Caught up.")
    assert service.run_due()["delivered"] == 1
    assert len(model_requests) == 1 and row(c["id"])["next_run_at"] > clock.now_iso()


def test_a_crash_after_the_claim_never_runs_the_slot_again(live, monkeypatch, model_requests):
    c = make(live)
    due(c["id"])
    monkeypatch.setattr(scheduler, "run_on_loop", lambda start: (_ for _ in ()).throw(RuntimeError("boom")))
    assert service.run_due()["failed"] == 1
    monkeypatch.undo()
    assert row(c["id"])["failures"] == 1 and row(c["id"])["next_run_at"] > clock.now_iso()
    assert service.run_due()["failed"] == 0 and model_requests == []


def test_shutdown_hands_the_slot_back_and_it_runs_once_after_restart(app, login_as, tmp_path):
    who = login_as("member")
    headers = {"Authorization": f"Bearer {who.cookies.get('sf_session')}"}
    with TestClient(app, headers=headers) as c:
        _wait(_job_idle)
        made = make(c)
        fake.script({"chunks": ["a"] * 50, "delay": 0.2})
        r = c.post(f"/api/agent/checkins/{made['id']}/run")  # due now, and the scheduler starts the job
        assert r.status_code == 202
        old = r.json()["next_run_at"]
        _wait(lambda: bool(detached._running))
    with TestClient(app, headers=headers):  # the restart (the lifespan reopens the database)
        _wait(_job_idle)
        r = row(made["id"])
        assert (r["next_run_at"], r["failures"], r["last_status"]) == (old, 0, None)
        assert count("core_agent_conversations WHERE user_id = ?", (who.principal.id,)) == 0
        assert notes(who.principal.id) == []
        fake.reset()
        fake.script("All good.")
        service.run_due()
        assert len(notes(who.principal.id)) == 1
        assert count("core_agent_conversations WHERE user_id = ?", (who.principal.id,)) == 1


def test_a_checkin_is_offered_read_tools_only_and_cannot_write(live, model_requests):
    c = make(live)
    due(c["id"])
    fake.script({"tool": "example_create_widget", "args": {"name": "W"}}, "Done.")
    service.run_due()
    owner = live.principal
    offered = {t["name"] for t in model_requests[0]["tools"]}
    job = {s.name for s in engine.chat_tools(owner, "job")}
    assert offered - {"core_find_tools"} <= job and "example_list_widgets" in offered
    by_name = {s.name: s for s in registry.current().all()}
    assert not any(
        by_name[n].writes or by_name[n].always_confirm or by_name[n].remote or by_name[n].untrusted_source
        for n in offered
        if n in by_name
    )
    assert count("example_widgets") == 0
    [run] = core_db.rows("SELECT status, source, error FROM core_agent_tool_runs")
    assert (run["status"], run["source"]) == ("error", "job") and "Unknown tool" in run["error"]


def test_always_allow_rules_never_apply_in_a_checkin(live):
    owner, agent = live.principal, agents.get()
    approval_rules.create(owner.id, agent["id"], "example_create_widget")
    c = make(live)
    due(c["id"])
    fake.script({"tool": "example_create_widget", "args": {"name": "W"}}, "Done.")
    service.run_due()
    assert count("example_widgets") == 0

    # Even a write forced into a check-in turn's tool set waits for a card no one can approve.
    spec = core_db.must(registry.current().get("example_create_widget"))
    cid = core_db.must(core_db.one("SELECT id FROM core_agent_conversations WHERE user_id = ?", (owner.id,)))["id"]

    def settle(source: Literal["chat", "checkin"]) -> tuple[list[dict], dict]:
        state = TurnState(
            user=owner, agent=agent, provider=FakeProvider("fake"), conversation_id=cid, turn_id=0, source=source
        )
        state.by_name, state.loaded = {spec.name: spec}, {spec.name}
        emitted: list[dict] = []
        call = {"name": spec.name, "id": f"t-{source}", "args": {"name": "Forced"}}
        asyncio.run(dispatch.run_call(state, emitted.append, call, None))
        return emitted, core_db.must(
            core_db.one("SELECT * FROM core_agent_tool_runs WHERE tool_use_id = ?", (call["id"],))
        )

    emitted, run = settle("checkin")
    assert [e["type"] for e in emitted] == ["confirm"] and (run["status"], run["source"]) == ("pending", "job")
    with pytest.raises(NotFound):
        engine.confirm(owner, run["id"], "approve")
    assert count("example_widgets") == 0
    emitted, run = settle("chat")  # the control: in chat the rule skips the card and it runs
    assert run["status"] == "done" and count("example_widgets") == 1


def test_a_checkin_prompt_does_not_fire_topic_reminders(live, model_requests):
    intents.create(live.principal, ["overdue"], "Ask about the supplier invoice.")
    c = make(live, prompt="Anything overdue?")
    due(c["id"])
    fake.script("[SILENT]")
    service.run_due()
    assert "Topic reminder" not in str(model_requests[0]["system"])
    assert core_db.must(core_db.one("SELECT fires FROM core_agent_intents"))["fires"] == 0


def test_the_third_failure_notifies_and_the_tenth_pauses(live, model_requests):
    c = make(live)
    owner = live.principal.id
    for i in range(1, 11):
        due(c["id"])
        fake.script({"error": "bad key", "status": 401})
        assert service.run_due()["failed"] == 1
        if i == 3:
            assert [n["title"] for n in notes(owner)] == ["Check-in failing: Morning look"]
            assert row(c["id"])["enabled"] == 1
    r = row(c["id"])
    assert (r["enabled"], r["failures"], r["last_status"]) == (0, 10, "error")
    assert [n["title"] for n in notes(owner)] == ["Check-in failing: Morning look", "Check-in paused: Morning look"]
    assert count("core_agent_conversations WHERE user_id = ?", (owner,)) == 0
    calls = len(model_requests)
    due(c["id"])
    assert service.run_due()["failed"] == 0 and len(model_requests) == calls


def test_a_success_clears_the_streak(live):
    c = make(live)
    for reply in ({"error": "bad key", "status": 401}, {"error": "bad key", "status": 401}, "Fine."):
        due(c["id"])
        fake.script(reply)
        service.run_due()
    assert (row(c["id"])["failures"], row(c["id"])["last_status"]) == (0, "ok")


def test_an_empty_reply_is_a_failure(live):
    c = make(live)
    due(c["id"])
    fake.script("")
    assert service.run_due()["failed"] == 1
    assert "without writing a reply" in row(c["id"])["last_error"] and notes(live.principal.id) == []


def test_a_turn_past_its_time_limit_is_stopped_and_counted(live, monkeypatch):
    monkeypatch.setattr(service, "TURN_TIMEOUT", 0.3)
    c = make(live)
    due(c["id"])
    fake.script({"chunks": ["a"] * 20, "delay": 0.2})
    assert service.run_due()["failed"] == 1
    assert row(c["id"])["last_error"] == service.TIMED_OUT
    assert core_db.rows("SELECT status FROM core_agent_turns") == []  # its conversation (and turn) are gone
    assert count("core_agent_conversations WHERE user_id = ?", (live.principal.id,)) == 0


def test_the_owners_stop_is_not_a_failure(live):
    c = make(live)
    due(c["id"])
    fake.script({"chunks": ["a"] * 50, "delay": 0.1})

    def stop() -> None:  # the Stop button, clicked while the turn runs
        def stopped() -> bool:
            turn = core_db.one("SELECT id FROM core_agent_turns")
            return bool(turn) and live.post(f"/api/agent/turns/{turn['id']}/cancel").json().get("cancelled") is True

        _wait(stopped)

    clicker = threading.Thread(target=stop)
    clicker.start()
    assert service.run_due()["silent"] == 1
    clicker.join()
    r = row(c["id"])
    assert (r["failures"], r["last_status"], r["last_error"]) == (0, "silent", None)
    assert (
        notes(live.principal.id) == []
        and count("core_agent_conversations WHERE user_id = ?", (live.principal.id,)) == 0
    )


def during(monkeypatch, act) -> None:
    """Run `act(out)` after the check-in's turn ends and before the job records it: "mid-run"."""
    real = detached.run_unattended

    async def run(*args, **kwargs):
        out = await real(*args, **kwargs)
        await asyncio.to_thread(act, out)
        return out

    monkeypatch.setattr(detached, "run_unattended", run)


def test_a_checkin_deleted_mid_run_delivers_nothing(live, monkeypatch):
    c = make(live)
    due(c["id"])
    fake.script("Two invoices are overdue.")
    during(monkeypatch, lambda out: service.delete(live.principal, c["id"]))
    service.run_due()
    assert (
        notes(live.principal.id) == []
        and count("core_agent_conversations WHERE user_id = ?", (live.principal.id,)) == 0
    )


def test_a_conversation_deleted_mid_run_is_ok_without_a_notification(live, monkeypatch):
    c = make(live)
    due(c["id"])
    fake.script("Two invoices are overdue.")
    during(monkeypatch, lambda out: history.delete_conversation(out["conversation_id"], live.principal.id))
    service.run_due()
    assert row(c["id"])["last_status"] == "ok" and notes(live.principal.id) == []


def test_pausing_mid_run_still_delivers_the_reply(live, monkeypatch):
    c = make(live)
    due(c["id"])
    fake.script("Two invoices are overdue.")
    during(monkeypatch, lambda out: service.set_enabled(live.principal, c["id"], False))
    assert service.run_due()["delivered"] == 1
    assert len(notes(live.principal.id)) == 1 and row(c["id"])["enabled"] == 0


def test_the_shutdown_hand_back_keeps_a_newer_run_now(live, monkeypatch):
    c = make(live)
    due(c["id"])

    def shutdown_after_run_now(start):  # Run now lands, then shutdown stops the turn
        service.run_now(live.principal, c["id"])
        return None

    monkeypatch.setattr(scheduler, "run_on_loop", shutdown_after_run_now)
    service.run_due()
    assert "2000-01-01T00:00:00Z" != row(c["id"])["next_run_at"] <= clock.now_iso()


def test_a_cut_off_reply_is_delivered_with_the_incomplete_note(live):
    c = make(live)
    due(c["id"])
    fake.script({"text": "Half", "stop": "max_tokens"})
    assert service.run_due()["delivered"] == 1
    [n] = notes(live.principal.id)
    assert n["message"].startswith("Half") and "incomplete" in n["message"]


def test_an_unbacked_claim_is_delivered_with_its_correction(live):
    c = make(live)
    due(c["id"])
    fake.script("I created the todo for you.")
    service.run_due()
    [n] = notes(live.principal.id)
    assert n["message"].startswith("I created the todo for you.\n\n") and "created" in n["message"][28:]


def test_zero_keys_claims_nothing(live, monkeypatch, model_requests):
    monkeypatch.delenv("AGENT_FAKE_PROVIDER")
    c = make(live)
    due(c["id"])
    assert service.run_due()["skipped"] == "no_provider"
    r = row(c["id"])
    assert (r["next_run_at"], r["failures"]) == ("2000-01-01T00:00:00Z", 0) and model_requests == []


def test_an_inactive_owner_or_a_bad_schedule_is_not_run(live, login_as, model_requests):
    c = make(live)
    due(c["id"])
    with core_db.transaction() as conn:
        conn.execute("UPDATE core_users SET is_active = 0 WHERE id = ?", (live.principal.id,))
    assert service.run_due() == {"delivered": 0, "silent": 0, "failed": 0} and model_requests == []

    other = login_as("member")
    bad, good = make(other, name="bad"), make(other, name="good")
    due(bad["id"], "1999-01-01T00:00:00Z")
    due(good["id"])
    with core_db.transaction() as conn:
        conn.execute("UPDATE core_agent_checkins SET schedule = 'bogus' WHERE id = ?", (bad["id"],))
    fake.script("Fine.")
    assert service.run_due()["delivered"] == 1
    assert (row(bad["id"])["enabled"], row(bad["id"])["last_error"]) == (0, "bad schedule")


def test_the_job_is_registered():
    job = scheduler.jobs()[service.JOB]
    assert (job.every, job.timeout) == (60, 1800)
