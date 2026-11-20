"""Server-owned turns: a turn outlives its request, replays from a seq, stops on cancel, and is
marked at startup (agent.md §5, "Server-owned turns").

Tests that need a turn to outlive a request run the app's lifespan (`with TestClient(app)`), so
every request shares one event loop; leaving a `c.stream(...)` block early is a real disconnect.
"""

import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

from backend.core import db as core_db, scheduler
from backend.core.agent import agents, detached, startup
from backend.core.agent.providers import fake
from backend.core.agent.providers.fake import FakeProvider

SLOW = {"chunks": ["a", "b", "c"], "delay": 0.2}


@pytest.fixture(autouse=True)
def _fake(monkeypatch):
    monkeypatch.setenv("AGENT_FAKE_PROVIDER", "1")
    fake.reset()
    yield
    fake.reset()


def parse(lines) -> list[dict]:
    return [json.loads(line[6:]) for line in lines if line.startswith("data: ")]


def events(response) -> list[dict]:
    assert response.status_code == 200, response.text
    return parse(response.text.splitlines())


def frames(response):
    for line in response.iter_lines():
        if line.startswith("data: "):
            yield json.loads(line[6:])


def live_client(app, who) -> TestClient:
    return TestClient(app, headers={"Authorization": f"Bearer {who.cookies.get('sf_session')}"})


def turn(turn_id: int) -> dict:
    return core_db.must(core_db.one("SELECT * FROM core_agent_turns WHERE id = ?", (turn_id,)))


def replies(cid: int) -> list[str]:
    rows = core_db.rows(
        "SELECT content FROM core_agent_messages WHERE conversation_id = ? AND role = 'assistant' ORDER BY id", (cid,)
    )
    return [json.loads(r["content"])["text"] for r in rows]


def _wait(predicate, seconds: float = 5) -> None:
    deadline = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < deadline, "timed out waiting"
        time.sleep(0.02)


def test_events_carry_seq_and_replay_from_the_stored_log(login_as):
    a, b = login_as("member"), login_as("member")
    evs = events(a.post("/api/agent/chat", json={"message": "hello"}))
    assert [e["seq"] for e in evs] == list(range(len(evs)))
    tid = evs[0]["turn_id"]
    assert evs[-1]["type"] == "done" and all("turn_id" not in e for e in evs[1:])
    row = turn(tid)
    assert (row["status"], row["conversation_id"], row["user_id"]) == ("done", evs[0]["id"], a.principal.id)
    assert row["ended_at"]

    assert events(a.get(f"/api/agent/turns/{tid}/events")) == evs
    assert events(a.get(f"/api/agent/turns/{tid}/events?after=1")) == evs[2:]
    assert events(a.get(f"/api/agent/turns/{tid}/events?after={evs[-1]['seq']}")) == []
    assert a.post(f"/api/agent/turns/{tid}/cancel").json() == {"cancelled": False}
    for path in (f"/api/agent/turns/{tid}/events", f"/api/agent/turns/{tid + 99}/events"):
        assert b.get(path).status_code == 404
    assert b.post(f"/api/agent/turns/{tid}/cancel").status_code == 404


def test_a_turn_keeps_running_and_saves_its_reply_after_the_client_disconnects(app, login_as):
    a = login_as("member")
    fake.script(SLOW)
    with live_client(app, a) as c:
        with c.stream("POST", "/api/agent/chat", json={"message": "hi"}) as r:
            first = next(frames(r))  # then the client goes away
        assert detached._live(first["turn_id"]) is not None
        _wait(lambda: turn(first["turn_id"])["status"] == "done")
        assert replies(first["id"]) == ["abc"]


def test_resume_after_n_yields_every_later_event_exactly_once(app, login_as):
    a = login_as("member")
    fake.script(SLOW)
    with live_client(app, a) as c:
        with c.stream("POST", "/api/agent/chat", json={"message": "hi"}) as r:
            seen = []
            for event in frames(r):
                seen.append(event)
                if event["type"] == "text":
                    break
        tid, n = seen[0]["turn_id"], seen[-1]["seq"]
        rest = events(c.get(f"/api/agent/turns/{tid}/events?after={n}"))  # live: tails to the end
        assert [e["seq"] for e in rest] == list(range(n + 1, n + 1 + len(rest)))
        assert [e["text"] for e in rest if e["type"] == "text"] == ["b", "c"] and rest[-1]["type"] == "done"
        stored = events(c.get(f"/api/agent/turns/{tid}/events"))
        assert stored == seen + rest


def test_cancel_stops_the_turn_and_records_cancelled(app, login_as):
    a = login_as("member")
    fake.script({"chunks": ["a", "b", "c", "d", "e"], "delay": 0.2})
    with live_client(app, a) as c:
        with c.stream("POST", "/api/agent/chat", json={"message": "hi"}) as r:
            it = frames(r)
            first = next(it)
            tid = first["turn_id"]
            assert c.post(f"/api/agent/turns/{tid}/cancel").json() == {"cancelled": True}
            rest = list(it)
        assert rest[-1] == {"type": "done", "stopped": True, "seq": rest[-1]["seq"]}
        assert len([e for e in rest if e["type"] == "text"]) < 5
        row = turn(tid)
        assert row["status"] == "cancelled" and row["ended_at"]
        assert replies(first["id"]) == []  # the cut-off iteration is not saved
        assert c.post(f"/api/agent/turns/{tid}/cancel").json() == {"cancelled": False}
        after = events(c.post("/api/agent/chat", json={"conversation_id": first["id"], "message": "again"}))
        assert after[-1]["type"] == "done"


def test_a_second_running_turn_on_a_conversation_is_refused(app, login_as):
    a = login_as("member")
    first = events(a.post("/api/agent/chat", json={"message": "one"}))
    cid = first[0]["id"]
    fake.script(SLOW)
    with live_client(app, a) as c:
        with c.stream("POST", "/api/agent/chat", json={"conversation_id": cid, "message": "two"}) as r:
            it = frames(r)
            next(it)
            refused = c.post("/api/agent/chat", json={"conversation_id": cid, "message": "three"})
            assert (refused.status_code, refused.json()) == (409, {"detail": "turn_running"})
            assert list(it)[-1]["type"] == "done"
        texts = core_db.rows(
            "SELECT content FROM core_agent_messages WHERE conversation_id = ? AND role = 'user'", (cid,)
        )
        assert [json.loads(t["content"])["text"] for t in texts] == ["one", "two"]
        assert c.post("/api/agent/chat", json={"conversation_id": cid, "message": "four"}).status_code == 200


def test_a_turn_left_running_is_interrupted_at_startup(login_as):
    a = login_as("member")
    cid = events(a.post("/api/agent/chat", json={"message": "hi"}))[0]["id"]
    with core_db.transaction() as conn:
        tid = core_db.insert_in(
            conn,
            "INSERT INTO core_agent_turns (conversation_id, user_id, status, started_at) VALUES (?, ?, 'running', ?)",
            (cid, a.principal.id, "2026-11-02T09:00:00Z"),
        )
        conn.execute(
            "INSERT INTO core_agent_turn_events (turn_id, seq, event) VALUES (?, 0, ?)",
            (tid, json.dumps({"type": "conversation_id", "id": cid, "seq": 0, "turn_id": tid})),
        )
    startup.on_startup()
    row = turn(tid)
    assert row["status"] == "interrupted" and row["ended_at"]
    log = events(a.get(f"/api/agent/turns/{tid}/events"))
    assert [e["seq"] for e in log] == [0, 1] and log[-1] == {**detached.RESTARTED, "seq": 1}
    assert a.post("/api/agent/chat", json={"conversation_id": cid, "message": "again"}).status_code == 200


def test_shutdown_interrupts_a_running_turn(app, login_as, tmp_path):
    a = login_as("member")
    fake.script({"chunks": ["a"] * 50, "delay": 0.2})
    with live_client(app, a) as c:
        with c.stream("POST", "/api/agent/chat", json={"message": "hi"}) as r:
            tid = next(frames(r))["turn_id"]
    core_db.init(tmp_path / "data")  # the lifespan closed it
    assert turn(tid)["status"] == "interrupted"
    log = events(a.get(f"/api/agent/turns/{tid}/events"))
    assert [e["seq"] for e in log] == list(range(len(log))) and log[-1] == {**detached.RESTARTED, "seq": len(log) - 1}


def test_prune_drops_events_a_week_after_the_turn_ended(login_as, freeze):
    a = login_as("member")
    freeze("2026-11-02T09:00:00Z")
    tid = events(a.post("/api/agent/chat", json={"message": "hi"}))[0]["turn_id"]

    def count() -> int:
        row = core_db.one("SELECT count(*) AS n FROM core_agent_turn_events WHERE turn_id = ?", (tid,))
        return core_db.must(row)["n"]

    kept = count()
    freeze("2026-11-08T09:00:00Z")
    detached.prune_events()
    assert count() == kept > 0
    freeze("2026-11-10T09:00:00Z")
    detached.prune_events()
    assert count() == 0 and turn(tid)["status"] == "done"
    assert scheduler.jobs()["core.agent_turn_events_prune"].every == 86400


def test_the_turn_is_answered_when_the_request_goes_away_while_it_starts(login_as, monkeypatch):
    a = login_as("member")
    begin = detached._begin

    def slow_begin(*args):
        time.sleep(0.3)
        return begin(*args)

    monkeypatch.setattr(detached, "_begin", slow_begin)

    async def go():
        request = asyncio.create_task(
            detached.start(FakeProvider("fake-default"), a.principal, "hi", conversation_id=None, agent=agents.get())
        )
        await asyncio.sleep(0.1)
        request.cancel()  # the client left before the turn's first event
        live = next(iter(detached._running))
        assert live.task is not None
        await live.task
        return live

    live = asyncio.run(go())
    assert live.turn_id is not None and turn(live.turn_id)["status"] == "done"
    assert replies(core_db.must(live.conversation_id)) == ["You said: hi"]


@pytest.mark.parametrize("failures, status", [(1, "done"), (99, "running")])
def test_the_final_log_write_is_retried_and_never_holds_the_reply(login_as, monkeypatch, failures, status):
    a = login_as("member")
    write, calls = detached._write, []
    monkeypatch.setattr(detached, "FINAL_RETRY_S", 0)

    def flaky(turn_id, batch, final):
        if final:
            calls.append(final)
            if len(calls) <= failures:
                raise RuntimeError("disk full")
        write(turn_id, batch, final)

    monkeypatch.setattr(detached, "_write", flaky)
    evs = events(a.post("/api/agent/chat", json={"message": "hi"}))
    assert evs[-1]["type"] == "done" and turn(evs[0]["turn_id"])["status"] == status
    assert len(calls) == min(failures + 1, detached.FINAL_TRIES)
