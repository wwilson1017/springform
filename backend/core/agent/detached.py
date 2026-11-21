"""Server-owned turns (agent.md §5): a Whisk turn outlives the HTTP response that started it.

Pattern from CakeCRM `assistant/turns.py`, cut down for one process, one SQLite file and one
event loop: no leases, heartbeats or dead-turn judging. A turn this process runs is in
`_running`; anything else has ended, or belonged to a process that is gone (startup marks those).

`start()` hands the turn to a supervisor task and returns its event stream. The supervisor owns
the turn end to end: it saves the user message and the `running` row (`_begin`, one
transaction), runs `TurnRunner`, writes the events to `core_agent_turn_events` in batches, and
commits the final status together with the last events. Every event gets a `seq` (0, 1, ...);
the first also carries `turn_id`. The terminal event (`done` or `error`) is held back from every
reader until that final commit, so a client that re-reads the conversation on `done` never
finds its turn still running.

Readers: the POST that started the turn and `GET /turns/{id}/events?after=N` both tail the
in-memory log of a live turn; an ended turn is replayed from the table. A client that leaves
only stops its own stream. Stop cancels the runner task (it ends with `done` + `stopped`);
shutdown does the same with `error` + `interrupted`. A tool already running in a worker thread
cannot be interrupted: the cancel takes effect when it returns (`aio.in_thread`).
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import AsyncGenerator, AsyncIterator
from typing import NamedTuple

from backend.core import clock, db
from backend.core.agent import history, uploads as uploads_mod
from backend.core.agent.aio import in_thread
from backend.core.agent.providers.base import AIProvider, sse
from backend.core.agent.turn_hooks import TurnState
from backend.core.agent.turns import TurnRunner
from backend.core.auth.deps import User

logger = logging.getLogger(__name__)

FLUSH_S = 1.0  # how far the stored log may lag a live turn (only a restart replays from it)
FINAL_TRIES = 3
FINAL_RETRY_S = 0.5
EVENTS_KEPT_DAYS = 7
TERMINAL = ("done", "error")
STOPPED = {"type": "done", "stopped": True}
RESTARTED = {"type": "error", "error": "The server restarted before this reply finished.", "interrupted": True}
CRASHED = "The assistant hit an unexpected error and stopped."


class TurnRunning(Exception):
    """A continuation (no message) while the conversation has a running turn (the route answers 409)."""


class Queued(NamedTuple):
    """A message sent while the conversation's turn runs: queued on that turn (steering, agent.md §5)."""

    turn_id: int


class Live:
    """One turn this process runs. `events[i]["seq"] == i`; readers see `events[:visible]`."""

    def __init__(self, conversation_id: int | None, user_id: int):
        self.conversation_id, self.user_id = conversation_id, user_id
        self.turn_id: int | None = None
        self.steers: list[str] = []  # the runner's TurnState.steers: it takes them before each model call
        self.events: list[dict] = []
        self.visible = 0
        self.saved = 0
        self.closed = False
        self.status: str | None = None
        self.stopping: str | None = None  # "cancelled" or "interrupted" once a stop was asked
        self.changed = asyncio.Event()
        self.ended = asyncio.Event()
        self.ready: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self.pump: asyncio.Task | None = None
        self.task: asyncio.Task | None = None

    def terminal(self) -> bool:
        return bool(self.events) and self.events[-1]["type"] in TERMINAL

    def emit(self, event: dict) -> None:
        if self.terminal():  # exactly one terminal event, and it is the last
            return
        n = len(self.events)
        self.events.append({**event, "seq": n, **({"turn_id": self.turn_id} if n == 0 else {})})
        if event["type"] not in TERMINAL:  # the terminal event waits for the final commit
            self.visible = len(self.events)
        self._pulse()

    def _pulse(self) -> None:
        self.changed.set()
        self.changed = asyncio.Event()

    async def tail(self, after: int) -> AsyncIterator[dict]:
        i = after + 1
        while True:
            changed, end, closed = self.changed, self.visible, self.closed
            for event in self.events[i:end]:
                yield event
            i = max(i, end)
            if closed:
                return
            await changed.wait()

    def accepting(self) -> bool:
        """A new message can still reach this turn's model (else it waits for the next turn)."""
        return self.turn_id is not None and not (self.stopping or self.status or self.terminal())

    def stop(self, status: str) -> bool:
        """Ask the turn to stop; False when it has already ended or is already stopping."""
        if self.stopping or self.status or self.terminal():
            return False
        self.stopping = status
        if self.pump is not None:
            self.pump.cancel()
        return True

    def close(self) -> None:
        self.visible, self.closed = len(self.events), True
        self._pulse()


_running: set[Live] = set()  # strong references: a bare task can be collected


def _live(turn_id: int) -> Live | None:
    return next((t for t in _running if t.turn_id == turn_id), None)


async def _stream(events: AsyncIterator[dict]) -> AsyncGenerator[str, None]:
    async for event in events:
        yield sse(event)


async def start(
    provider: AIProvider,
    user: User,
    message: str | None,
    *,
    conversation_id: int | None,
    agent: dict,
    context: str = "",
    uploads: list[uploads_mod.Upload] | None = None,
) -> AsyncGenerator[str, None] | Queued | None:
    """Start a turn and return its SSE stream; None when the conversation is not this user's. A
    message for a conversation whose turn is running is queued on it (`Queued`); one whose turn is
    ending waits for it to end and starts the next. A continuation (no message) raises TurnRunning.
    The turn does not depend on the caller: a request cancelled from here on still gets its
    message saved and answered. The staged `uploads` are this function's from here: saved with the
    message, or discarded. A message with attachments never steers: while a turn is taking messages
    it raises TurnRunning, since a mid-turn upload would taint a turn already deciding on writes."""
    uploads = uploads or []
    try:  # a refusal, or a request cancelled while it waits, discards the staged files
        while conversation_id is not None and (
            running := next((t for t in _running if t.conversation_id == conversation_id), None)
        ):
            if message is None and not uploads:
                raise TurnRunning
            if running.user_id != user.id:
                uploads_mod.discard(uploads)
                return None
            if running.turn_id is None:  # its first transaction is still running
                await asyncio.wait([running.ready])
                if running.turn_id is None:  # that conversation is not this user's
                    uploads_mod.discard(uploads)
                    return None
            elif running.accepting():  # no await since the check, so the runner cannot end in between
                if uploads or message is None:  # attachments never steer (docstring)
                    raise TurnRunning
                # simplification: the queue is in memory until the runner takes it (or the turn ends and
                # saves it, shutdown included), so a hard crash loses it; the client re-reads the conversation
                # when the turn ends and sends again what is missing. Upgrade: a pending-message table.
                running.steers.append(message)
                return Queued(running.turn_id)
            else:  # ending or stopping: the message starts the next turn once this one is gone
                await asyncio.wait([db.must(running.task)])  # set in the same step as `_running.add`
    except BaseException:
        uploads_mod.discard(uploads)
        raise
    live = Live(conversation_id, user.id)
    _running.add(live)  # before any await, so a second post on this conversation finds it
    live.task = asyncio.create_task(_supervise(live, provider, user, message, agent, context, uploads))
    if not await asyncio.shield(live.ready):
        return None
    return _stream(live.tail(-1))


async def _supervise(
    live: Live,
    provider: AIProvider,
    user: User,
    message: str | None,
    agent: dict,
    context: str,
    uploads: list[uploads_mod.Upload],
) -> None:
    try:
        try:
            begun = await in_thread(_begin, user, message, live.conversation_id, agent, uploads)
        except Exception as e:
            live.ready.set_exception(e)
            return
        live.ready.set_result(begun is not None)
        if begun is None:
            return
        cid, title, turn_id = begun
        live.conversation_id, live.turn_id = cid, turn_id
        state = TurnState(
            user=user,
            agent=agent,
            provider=provider,
            conversation_id=cid,
            turn_id=turn_id,
            context=context,
            steers=live.steers,
            message=message or "",
        )
        if live.stopping is None:
            live.pump = asyncio.create_task(TurnRunner(state, live.emit, title=title).run())
        writer = asyncio.create_task(_writer(live))
        live.status = await _outcome(live)
        live.ended.set()
        await writer
    finally:
        if not live.ready.done():
            live.ready.cancel()
        live.close()
        _running.discard(live)


async def _outcome(live: Live) -> str:
    """Wait for the runner; make sure the log ends with one terminal event; return the status."""
    if live.pump is not None:
        await asyncio.wait([live.pump])
        if not live.pump.cancelled() and (e := live.pump.exception()) is not None:
            logger.error("agent turn %s crashed", live.turn_id, exc_info=e)
            live.emit({"type": "error", "error": CRASHED})
    if live.stopping and not live.terminal():
        live.emit(STOPPED if live.stopping == "cancelled" else RESTARTED)
        return live.stopping
    if not live.terminal():  # the runner's contract says this cannot happen
        live.emit({"type": "error", "error": CRASHED})
    return "done" if live.events[-1]["type"] == "done" else "error"


def _begin(
    user: User,
    message: str | None,
    conversation_id: int | None,
    agent: dict,
    uploads: list[uploads_mod.Upload] | None = None,
) -> tuple[int, str | None, int] | None:
    """One transaction: the conversation (created if new), the user message with its uploads
    (which taint the conversation), the title and the `running` turn row. None when the
    conversation is not this user's. Staged uploads not saved here are discarded."""
    title, uploads = None, uploads or []
    try:
        with db.transaction() as conn:
            if conversation_id is None:
                conversation_id = history.create_conversation_in(conn, user.id, agent["id"])
            elif not conn.execute(
                "SELECT 1 FROM core_agent_conversations WHERE id = ? AND user_id = ?", (conversation_id, user.id)
            ).fetchone():
                return None
            if message or uploads:
                content = {"text": message or ""}
                message_id = history.save_message_in(conn, conversation_id, "user", content)
                if uploads:
                    uploads_mod.save_in(conn, user.id, conversation_id, message_id, content, uploads)
                    history.mark_tainted_in(conn, conversation_id)
                title = history.auto_title_in(conn, conversation_id, message or uploads_mod.TITLE)
            turn_id = db.insert_in(
                conn,
                "INSERT INTO core_agent_turns (conversation_id, user_id, status, started_at) VALUES (?, ?, 'running', ?)",
                (conversation_id, user.id, clock.now_iso()),
            )
    finally:
        uploads_mod.discard(uploads)
    return conversation_id, title, turn_id


async def _writer(live: Live) -> None:
    """The log's only writer: visible events every FLUSH_S, then the rest with the final status."""
    while not live.ended.is_set():
        try:
            await asyncio.wait_for(live.ended.wait(), FLUSH_S)
        except TimeoutError:
            pass
        if not live.ended.is_set() and live.saved < live.visible:
            upto = live.visible
            try:
                await in_thread(_write, live.turn_id, live.events[live.saved : upto], None)
                live.saved = upto
            except Exception:
                logger.warning("could not write the log of agent turn %s; retrying", live.turn_id, exc_info=True)
    if live.steers:  # sent while the turn ended, stopped or waited for approval: saved unanswered
        leftover, live.steers[:] = list(live.steers), []
        try:
            await in_thread(_save_unanswered, db.must(live.conversation_id), leftover)
        except Exception:
            logger.error(
                "could not save %d message(s) sent to agent turn %s", len(leftover), live.turn_id, exc_info=True
            )
    for attempt in range(FINAL_TRIES):
        try:
            await in_thread(_write, live.turn_id, live.events[live.saved :], live.status)
            live.saved = len(live.events)
            return
        except Exception:
            logger.warning("could not close the log of agent turn %s", live.turn_id, exc_info=True)
            if attempt + 1 < FINAL_TRIES:
                await asyncio.sleep(FINAL_RETRY_S)
    # simplification: the stream still ends normally (the conversation rows are the record); the
    # row stays `running` until the next startup marks it interrupted.
    logger.error("agent turn %s ended but its log could not be closed", live.turn_id)


def _save_unanswered(conversation_id: int, texts: list[str]) -> None:
    """Before the terminal event is committed, so a client that re-reads on `done` finds them; it
    then continues the conversation (POST /chat, no message) to have them answered."""
    with db.transaction() as conn:
        for text in texts:
            history.save_message_in(conn, conversation_id, "user", {"text": text})


def _write(turn_id: int, events: list[dict], status: str | None) -> None:
    with db.transaction() as conn:
        conn.executemany(
            "INSERT INTO core_agent_turn_events (turn_id, seq, event) VALUES (?, ?, ?)",
            [(turn_id, e["seq"], json.dumps(e, default=str)) for e in events],
        )
        if status:
            conn.execute(
                "UPDATE core_agent_turns SET status = ?, ended_at = ? WHERE id = ? AND status = 'running'",
                (status, clock.now_iso(), turn_id),
            )


# ── Routes, startup, job, shutdown ────────────────────────────────────────────


def get_turn(turn_id: int, user_id: int) -> dict | None:
    """The turn row when this user started it (anyone else gets None: the routes answer 404)."""
    return db.one("SELECT * FROM core_agent_turns WHERE id = ? AND user_id = ?", (turn_id, user_id))


async def events(turn: dict, after: int) -> AsyncGenerator[str, None]:
    """Every event with seq > after: tailed live while the turn runs, else from the stored log."""
    live = _live(turn["id"])
    if live is not None:
        async for event in live.tail(after):
            yield sse(await in_thread(_shown, event) if event["type"] == "tool_end" else event)
        return
    for row in await in_thread(_stored, turn, after):
        yield f"data: {row['event']}\n\n"


def _shown(event: dict) -> dict:
    """A replayed `tool_end` carries history.WITHHELD in place of a result whose user can no longer
    read a record it names (history.recheck)."""
    run = history.get_tool_run(event["tool_run_id"]) if event.get("tool_run_id") else None
    return {**event, "result": history.WITHHELD} if run and run.get("withheld") else event


def _stored(turn: dict, after: int) -> list[dict]:
    """The stored events after `after`. A turn marked `interrupted` at startup may have streamed
    up to a second of events that were never stored, so its `interrupted` event can carry a seq
    the client already has: it is sent whatever `after` is."""
    sql = "SELECT event FROM core_agent_turn_events WHERE turn_id = ?"
    rows = db.rows(f"{sql} AND seq > ? ORDER BY seq", (turn["id"], after))
    if turn["status"] == "interrupted" and not (rows and _is_terminal(rows[-1])):
        last = db.one(f"{sql} ORDER BY seq DESC LIMIT 1", (turn["id"],))
        if last and _is_terminal(last):
            rows.append(last)
    for row in rows:
        if '"tool_end"' in row["event"] and (event := json.loads(row["event"]))["type"] == "tool_end":
            if (shown := _shown(event)) is not event:
                row["event"] = json.dumps(shown)
    return rows


def _is_terminal(row: dict) -> bool:
    return json.loads(row["event"])["type"] in TERMINAL


def cancel(turn: dict) -> bool:
    """Stop a running turn; False when it has already ended."""
    live = _live(turn["id"])
    return live is not None and live.stop("cancelled")


def mark_interrupted() -> int:
    """At startup: turns left `running` belong to a process that is gone. Each gets a terminal
    event in its log and the status `interrupted`."""
    with db.transaction() as conn:
        ids = [r["id"] for r in conn.execute("SELECT id FROM core_agent_turns WHERE status = 'running'")]
        for turn_id in ids:
            seq = conn.execute(
                "SELECT coalesce(max(seq), -1) + 1 FROM core_agent_turn_events WHERE turn_id = ?", (turn_id,)
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO core_agent_turn_events (turn_id, seq, event) VALUES (?, ?, ?)",
                (turn_id, seq, json.dumps({**RESTARTED, "seq": seq})),
            )
        conn.execute(
            "UPDATE core_agent_turns SET status = 'interrupted', ended_at = ? WHERE status = 'running'",
            (clock.now_iso(),),
        )
    return len(ids)


def prune_events(cancel: threading.Event | None = None) -> None:
    """Job core.agent_turn_events_prune: drop the events of turns that ended over 7 days ago."""
    with db.transaction() as conn:
        conn.execute(
            """DELETE FROM core_agent_turn_events WHERE turn_id IN
                 (SELECT id FROM core_agent_turns WHERE ended_at < ?)""",
            (clock.ago(EVENTS_KEPT_DAYS * 86400),),
        )


async def shutdown(grace: float = 10) -> bool:
    """Stop every running turn; True when all ended within `grace` (the database may close)."""
    turns = list(_running)
    for live in turns:
        live.stop("interrupted")
    tasks = [t.task for t in turns if t.task is not None]
    if not tasks:
        return True
    _, pending = await asyncio.wait(tasks, timeout=grace)
    return not pending
