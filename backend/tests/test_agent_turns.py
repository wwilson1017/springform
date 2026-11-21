"""Server-owned turns: a turn outlives its request, replays from a seq, stops on cancel, and is
marked at startup (agent.md §5, "Server-owned turns").

Tests that need a turn to outlive a request run the app's lifespan (`with TestClient(app)`), so
every request shares one event loop; leaving a `c.stream(...)` block early is a real disconnect.
"""

import asyncio
import json
import threading
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


def user_texts(cid: int) -> list[str]:
    rows = core_db.rows(
        "SELECT content FROM core_agent_messages WHERE conversation_id = ? AND role = 'user' ORDER BY id", (cid,)
    )
    return [json.loads(r["content"])["text"] for r in rows]


def test_a_message_sent_while_a_turn_runs_is_answered_in_that_turn(app, login_as, model_requests):
    a = login_as("member")
    cid = events(a.post("/api/agent/chat", json={"message": "one"}))[0]["id"]
    fake.script(SLOW, "Three it is.")
    with live_client(app, a) as c:
        with c.stream("POST", "/api/agent/chat", json={"conversation_id": cid, "message": "two"}) as r:
            it = frames(r)
            tid = next(it)["turn_id"]
            next(e for e in it if e["type"] == "text")  # the model call is under way
            queued = c.post("/api/agent/chat", json={"conversation_id": cid, "message": "three"})
            assert (queued.status_code, queued.json()) == (202, {"queued": True, "turn_id": tid})
            again = c.post("/api/agent/chat", json={"conversation_id": cid})  # a continuation still waits
            assert (again.status_code, again.json()) == (409, {"detail": "turn_running"})
            rest = list(it)
        assert [e["type"] for e in rest][-4:] == ["steer", "text", "usage", "done"] and rest[-4]["text"] == "three"
        assert user_texts(cid) == ["one", "two", "three"] and replies(cid)[-2:] == ["abc", "Three it is."]
        assert "three" in json.dumps(model_requests[-1]["messages"][-1])
        assert c.post("/api/agent/chat", json={"conversation_id": cid, "message": "four"}).status_code == 200


def test_a_skipped_write_never_runs_and_its_call_keeps_a_result(app, login_as, model_requests):
    from backend.core.agent import registry as tool_registry
    from backend.core.agent.spec import ToolSpec

    started, steered, wrote = threading.Event(), threading.Event(), []
    schema = {"type": "object", "properties": {}}
    look = ToolSpec(name="core_look", description="A lookup.", input_schema=schema, writes=False,
                    handler=lambda u, a: (started.set(), steered.wait(5)) and {"looked": True})  # fmt: skip
    jot = ToolSpec(name="core_jot", description="Jot.", input_schema=schema, writes=True, confirm_tier="routine",
                   handler_in=lambda conn, u, a: wrote.append(1) or {"ok": True}, targets=lambda a: [])  # fmt: skip
    before = tool_registry.current()
    tool_registry.set_current(tool_registry.build_registry([*before.all(), look, jot]))
    a = login_as("member")
    fake.script([{"tool": "core_look"}, {"tool": "core_jot"}], "Not jotting.")
    try:
        with live_client(app, a) as c:
            with c.stream("POST", "/api/agent/chat", json={"message": "look, then jot"}) as r:
                it = frames(r)
                cid = next(it)["id"]
                assert started.wait(5)  # the lookup is running
                assert c.post("/api/agent/chat", json={"conversation_id": cid, "message": "no jot"}).status_code == 202
                steered.set()  # the lookup was running when the message came: it finishes
                rest = list(it)
            assert user_texts(cid) == ["look, then jot", "no jot"]
    finally:
        tool_registry.set_current(before)
    ends = {e["tool"]: e for e in rest if e["type"] == "tool_end"}
    assert ends["core_look"]["status"] == "done" and wrote == []
    assert ends["core_jot"]["result"] == {"error": "Skipped to process your new message."}
    sent = json.dumps(model_requests[-1]["messages"][-1])
    assert sent.index("looked") < sent.index("Skipped to process") < sent.index("no jot")


def test_a_message_the_turn_never_took_is_saved_and_the_next_turn_answers_it(app, login_as, model_requests):
    a = login_as("member")
    fake.script(SLOW)
    with live_client(app, a) as c:
        with c.stream("POST", "/api/agent/chat", json={"message": "two"}) as r:
            it = frames(r)
            first = next(it)
            next(e for e in it if e["type"] == "text")  # stopped before this model call ends
            assert (
                c.post("/api/agent/chat", json={"conversation_id": first["id"], "message": "three"}).status_code == 202
            )
            assert c.post(f"/api/agent/turns/{first['turn_id']}/cancel").json() == {"cancelled": True}
            rest = list(it)
        assert rest[-1]["stopped"] and not [e for e in rest if e["type"] == "steer"]
        assert user_texts(first["id"]) == ["two", "three"]
        fake.script("About three.")
        assert events(c.post("/api/agent/chat", json={"conversation_id": first["id"]}))[-1]["type"] == "done"
    assert "three" in json.dumps(model_requests[-1]["messages"][-1])


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
    # A client that saw more than was stored still gets the ending.
    assert events(a.get(f"/api/agent/turns/{tid}/events?after=5")) == [log[-1]]
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


def test_the_approval_narration_leaves_a_message_for_the_next_turn(app, login_as, model_requests):
    from backend.core.agent import registry as tool_registry
    from backend.core.agent.spec import ToolSpec

    steered = threading.Event()
    schema = {"type": "object", "properties": {}}
    ask = ToolSpec(name="core_ask", description="Asks first.", input_schema=schema, writes=True, always_confirm=True,
                   handler_in=lambda conn, u, a: {"ok": True}, targets=lambda a: [])  # fmt: skip
    jot = ToolSpec(name="core_jot", description="Jot.", input_schema=schema, writes=True, confirm_tier="routine",
                   handler_in=lambda conn, u, a: steered.wait(5) and {"ok": True}, targets=lambda a: [])  # fmt: skip
    before = tool_registry.current()
    tool_registry.set_current(tool_registry.build_registry([*before.all(), ask, jot]))
    a = login_as("member")
    fake.script([{"tool": "core_ask"}, {"tool": "core_jot"}], "The first change waits for your approval.")
    try:
        with live_client(app, a) as c:
            with c.stream("POST", "/api/agent/chat", json={"message": "change both"}) as r:
                it = frames(r)
                cid = next(it)["id"]
                next(e for e in it if e["type"] == "confirm")
                assert (
                    c.post("/api/agent/chat", json={"conversation_id": cid, "message": "and a third"}).status_code
                    == 202
                )
                steered.set()  # the second change was running: it finishes, then the narration
                rest = list(it)
            assert user_texts(cid) == ["change both", "and a third"]  # saved for the next turn to answer
    finally:
        tool_registry.set_current(before)
    assert rest[-1]["type"] == "done" and not [e for e in rest if e["type"] == "steer"]
    assert "and a third" not in json.dumps(model_requests[-1]["messages"])


def test_a_message_sent_during_a_provider_retry_reaches_the_retried_call(app, login_as, model_requests):
    a = login_as("member")
    fake.script({"error": "slow down", "status": 429, "retry_after": 1}, "Answering both.")
    with live_client(app, a) as c:
        with c.stream("POST", "/api/agent/chat", json={"message": "one"}) as r:
            it = frames(r)
            cid = next(it)["id"]
            deadline = time.monotonic() + 5
            while not model_requests and time.monotonic() < deadline:  # the first attempt was made: now in backoff
                time.sleep(0.02)
            assert c.post("/api/agent/chat", json={"conversation_id": cid, "message": "two"}).status_code == 202
            rest = list(it)
    assert len(model_requests) == 2 and "two" in json.dumps(model_requests[1]["messages"])
    assert [e for e in rest if e["type"] == "steer"] and rest[-1]["type"] == "done"
