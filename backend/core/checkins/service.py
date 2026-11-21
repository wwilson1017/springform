"""Whisk check-ins (agent.md §5): a saved prompt Whisk runs on a schedule as its owner, with
look-up tools only, delivering its reply as a notification.

Job `core.agent_checkins` (every 60 s) runs the due ones one after another. Each is claimed first:
one transaction moves `next_run_at` to the next slot, so neither a second pass nor a restart runs
that slot again (a crash mid-turn loses it). Then the turn runs on the app's event loop
(`scheduler.run_on_loop` → `detached.run_unattended`) in a new conversation, outside every
transaction. A reply of exactly `[SILENT]`, an empty reply or a failed turn deletes that
conversation; any other reply keeps it and notifies the owner with a link to it. A turn stopped by
shutdown hands its slot back, so it runs once after the restart. Failed runs in a row are counted:
the 3rd notifies the owner, the 10th pauses the check-in; a success or a resume clears the count.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from backend.core import clock, db, localtime, scheduler
from backend.core.agent import agents, detached, history, providers
from backend.core.auth import service as auth_service
from backend.core.auth.deps import User
from backend.core.checkins import schedule
from backend.core.errors import Conflict, Invalid, NotFound
from backend.core.notifications import service as notifications

if TYPE_CHECKING:
    from backend.core.agent.providers.base import AIProvider

logger = logging.getLogger(__name__)

JOB = "core.agent_checkins"
SILENT = "[SILENT]"
NOTIFY_AT, DISABLE_AT = 3, 10
TURN_TIMEOUT = 300  # seconds one check-in turn may take before it is stopped
MAX_PER_USER = 20
NAME_MAX, PROMPT_MAX = 80, 4000
LINK = "/whisk/checkins"
TIMED_OUT = "It ran past the time limit and was stopped."
NOTE = (  # the volatile prompt half of a check-in turn; fixed text, nothing user-written
    "## Scheduled check-in\n"
    "This turn was started by a schedule the user set up, not by a message they just typed. Nobody is "
    "here to answer a question or approve a change, and you have look-up tools only. Work from what "
    "you can look up now; do not pick up tasks from earlier conversations. Your reply is delivered to "
    "the user as a notification, so keep it short and complete on its own. If nothing needs their "
    f"attention, reply with exactly {SILENT} and nothing else; never put {SILENT} in a reply that says something."
)
_COLUMNS = (
    "id, name, prompt, schedule, enabled, next_run_at, failures, last_run_at, last_status, last_error, created_at"
)
_DUE = """SELECT c.* FROM core_agent_checkins c JOIN core_users u ON u.id = c.owner_user_id
           WHERE c.enabled = 1 AND c.next_run_at <= ? AND u.is_active = 1
           ORDER BY c.next_run_at, c.id LIMIT 1"""


# ── CRUD: the caller's own check-ins only (another user's id answers 404) ──────


def _out(row) -> dict:
    return {**dict(row), "enabled": bool(row["enabled"])}


def _get_in(conn: db.Conn, user: User, checkin_id: int) -> dict:
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM core_agent_checkins WHERE id = ? AND owner_user_id = ?", (checkin_id, user.id)
    ).fetchone()
    if row is None:
        raise NotFound("checkin_not_found")
    return _out(row)


def list_for_in(conn: db.Conn, user: User) -> list[dict]:
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM core_agent_checkins WHERE owner_user_id = ? ORDER BY id", (user.id,)
    ).fetchall()
    return [_out(r) for r in rows]


def list_for(user: User) -> list[dict]:
    with db.transaction() as conn:
        return list_for_in(conn, user)


def create_in(conn: db.Conn, user: User, name: str, prompt: str, schedule_text: str) -> dict:
    name, prompt = " ".join((name or "").split())[:NAME_MAX], (prompt or "").strip()[:PROMPT_MAX]
    if not name or not prompt:
        raise Invalid("A check-in needs a name and a prompt.")
    text = schedule.normalize(schedule_text)
    if conn.execute("SELECT count(*) FROM core_agent_checkins WHERE owner_user_id = ?", (user.id,)).fetchone()[0] >= (
        MAX_PER_USER
    ):
        raise Invalid(f"You can have at most {MAX_PER_USER} check-ins.")
    checkin_id = db.insert_in(
        conn,
        """INSERT INTO core_agent_checkins (owner_user_id, name, prompt, schedule, next_run_at, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (user.id, name, prompt, text, clock.to_iso(schedule.next_run(text, clock.now(), localtime.tz())),
         clock.now_iso()),
    )  # fmt: skip
    return _get_in(conn, user, checkin_id)


def create(user: User, name: str, prompt: str, schedule_text: str) -> dict:
    with db.transaction() as conn:
        return create_in(conn, user, name, prompt, schedule_text)


def set_enabled_in(conn: db.Conn, user: User, checkin_id: int, enabled: bool) -> dict:
    """Pause, or resume a paused one: the failure count clears and the next slot counts from now."""
    row = _get_in(conn, user, checkin_id)
    if enabled and not row["enabled"]:
        nxt = clock.to_iso(schedule.next_run(row["schedule"], clock.now(), localtime.tz()))
        conn.execute(
            "UPDATE core_agent_checkins SET enabled = 1, failures = 0, next_run_at = ? WHERE id = ?", (nxt, checkin_id)
        )
    elif not enabled:
        conn.execute("UPDATE core_agent_checkins SET enabled = 0 WHERE id = ?", (checkin_id,))
    return _get_in(conn, user, checkin_id)


def set_enabled(user: User, checkin_id: int, enabled: bool) -> dict:
    with db.transaction() as conn:
        return set_enabled_in(conn, user, checkin_id, enabled)


def run_now_in(conn: db.Conn, user: User, checkin_id: int) -> dict:
    """Make it due now; the job picks it up (the route asks the scheduler to start the job)."""
    if not _get_in(conn, user, checkin_id)["enabled"]:
        raise Conflict("checkin_paused")
    conn.execute("UPDATE core_agent_checkins SET next_run_at = ? WHERE id = ?", (clock.now_iso(), checkin_id))
    return _get_in(conn, user, checkin_id)


def run_now(user: User, checkin_id: int) -> dict:
    with db.transaction() as conn:
        return run_now_in(conn, user, checkin_id)


def delete_in(conn: db.Conn, user: User, checkin_id: int) -> None:
    if not conn.execute(
        "DELETE FROM core_agent_checkins WHERE id = ? AND owner_user_id = ?", (checkin_id, user.id)
    ).rowcount:
        raise NotFound("checkin_not_found")


def delete(user: User, checkin_id: int) -> None:
    with db.transaction() as conn:
        delete_in(conn, user, checkin_id)


# ── The job ───────────────────────────────────────────────────────────────────


def is_silent(reply: str) -> bool:
    """The whole reply is the token, at most wrapped once in `**`, `__` or a backtick."""
    text = (reply or "").strip()
    return any(text == f"{w}{SILENT}{w}" for w in ("", "**", "__", "`"))


def run_due(cancel: threading.Event | None = None) -> dict:
    """Job core.agent_checkins: run every due check-in, one after another. Each is claimed just
    before its own turn, so one this pass does not reach stays due for the next."""
    counts = {"delivered": 0, "silent": 0, "failed": 0}
    while not (cancel and cancel.is_set()) and db.one(_DUE, (clock.now_iso(),)) is not None:
        agent = agents.get()
        provider = providers.get_provider(
            tier=agent["model_tier"], provider=agent["provider_override"], model=agent["model_override"]
        )
        if provider is None:  # zero keys: nothing is claimed, so each runs once when a key arrives
            return {**counts, "skipped": "no_provider"}
        row = _claim()
        if row is None:  # paused or deleted since the look above
            continue
        outcome = _run(row, agent, provider)
        if outcome is None:  # shutdown
            break
        counts[outcome] += 1
    return counts


def _claim() -> dict | None:
    """Move the first due check-in's `next_run_at` to its next slot and return the row as it was:
    the issue's "set before dispatch", so a crash after this never runs the slot twice. A row whose
    schedule no longer parses (edited by hand) is paused instead, so it cannot block the others."""
    zone = localtime.tz()
    with db.transaction() as conn:
        while (row := conn.execute(_DUE, (clock.now_iso(),)).fetchone()) is not None:
            try:
                nxt = clock.to_iso(schedule.next_run(row["schedule"], clock.now(), zone))
            except Invalid:
                conn.execute(
                    """UPDATE core_agent_checkins SET enabled = 0, last_status = 'error', last_error = 'bad schedule'
                        WHERE id = ?""",
                    (row["id"],),
                )
                continue
            conn.execute("UPDATE core_agent_checkins SET next_run_at = ? WHERE id = ?", (nxt, row["id"]))
            return {**dict(row), "claimed": nxt}
    return None


def _run(row: dict, agent: dict, provider: AIProvider) -> str | None:
    """One claimed check-in: its turn, then the bookkeeping. None when shutdown stopped it."""
    owner = User.from_row(db.must(auth_service.get_user(row["owner_user_id"])))
    try:
        out = scheduler.run_on_loop(
            lambda: detached.run_unattended(
                provider, owner, row["prompt"], agent=agent, context=NOTE, timeout=TURN_TIMEOUT
            )
        )
    except Exception as e:  # the run itself failed: counted like any failed turn
        logger.exception("check-in %s could not be run", row["id"])
        out = {"conversation_id": None, "status": "error", "reply": "", "text": "", "error": str(e) or type(e).__name__}
    cid = out["conversation_id"] if out else None
    if out is None or out["status"] == "interrupted":
        # Shutdown before anything was delivered: hand the slot back (unless a Run now or resume
        # moved it since), so it runs once after the restart.
        if cid:
            history.delete_conversation(cid, owner.id)
        with db.transaction() as conn:
            conn.execute(
                "UPDATE core_agent_checkins SET next_run_at = ? WHERE id = ? AND next_run_at = ?",
                (row["next_run_at"], row["id"], row["claimed"]),
            )
        return None
    error = None
    if out["status"] != "done":
        error = TIMED_OUT if out["status"] == "cancelled" else out["error"] or "It stopped with an error."
    elif not out["reply"].strip():
        error = "The model ended without writing a reply."
    text = (out["text"].strip() or out["reply"].strip()) if error is None and not is_silent(out["reply"]) else None
    if cid and text is None:  # a silent or failed run leaves no conversation
        history.delete_conversation(cid, owner.id)
    with db.transaction() as conn:
        outcome = _finish_in(conn, row, text, cid, error)
    if outcome is None and cid and text is not None:  # deleted mid-run: nothing to deliver it to
        history.delete_conversation(cid, owner.id)
    return outcome or "silent"


def _finish_in(conn: db.Conn, row: dict, text: str | None, cid: int | None, error: str | None) -> str | None:
    """Record the run and notify; None when the check-in was deleted while it ran."""
    owner, name, now = row["owner_user_id"], row["name"], clock.now_iso()
    if error is None:
        status = "ok" if text else "silent"
        if not conn.execute(
            """UPDATE core_agent_checkins SET failures = 0, last_run_at = ?, last_status = ?, last_error = NULL
                WHERE id = ? RETURNING id""",
            (now, status, row["id"]),
        ).fetchone():
            return None
        exists = (
            cid
            and conn.execute(
                "SELECT 1 FROM core_agent_conversations WHERE id = ? AND user_id = ?", (cid, owner)
            ).fetchone()
        )
        if text and exists:  # the owner may have deleted the conversation while it ran
            notifications.deliver_in(conn, name, text, user_id=owner, link=f"/whisk/{cid}")
        return "delivered" if text else "silent"
    error = error[:500]
    got = conn.execute(
        """UPDATE core_agent_checkins
              SET failures = failures + 1, last_run_at = ?, last_status = 'error', last_error = ?,
                  enabled = CASE WHEN failures + 1 >= ? THEN 0 ELSE enabled END
            WHERE id = ? RETURNING failures""",
        (now, error, DISABLE_AT, row["id"]),
    ).fetchone()
    if got is None:
        return None
    if got["failures"] == NOTIFY_AT:
        message = f"It has failed {NOTIFY_AT} times in a row. Last error: {error}"
        notifications.deliver_in(conn, f"Check-in failing: {name}", message, user_id=owner, link=LINK)
    elif got["failures"] == DISABLE_AT:
        message = f"It failed {DISABLE_AT} times in a row and was paused. Last error: {error} Resume it once fixed."
        notifications.deliver_in(conn, f"Check-in paused: {name}", message, user_id=owner, link=LINK)
    return "failed"
