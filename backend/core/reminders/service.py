"""Reminders: a title and note delivered to their owner as a notification at `due_at`, once or
on a repeat, optionally attached to a record.

Status: `open` (waiting, or fired when `fired_at` is set), `snoozed` (moved to a later `due_at`,
fires again), `done`, `voided` (with `void_reason`). Only the owner changes a reminder; another
member sees reminders on a record they can read, flagged `mine: false`.

Firing (job `core.reminders_fire_due`, every 60 s): one transaction per batch selects due rows,
re-checks that the owner is active and can still read the record (voiding the reminder
otherwise), sets `fired_at` and calls `notifications.deliver_in` in that same transaction, then
spawns the next occurrence of a repeating one. A row spawns at most one successor (the series'
newest row is the only one that may), so a snoozed occurrence firing again never doubles a series.

Repeat is stored as JSON {freq, anchor, time, tz}: `freq` daily|weekly|monthly|yearly, the
series' first local date and wall time in the owner's zone, so 09:00 stays 09:00 across DST and
a monthly series on the 31st comes back to the 31st (recurrence.py).
"""

from __future__ import annotations

import json
import threading
from datetime import date, time
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from backend.core import clock, db, entities, localtime, pagination
from backend.core.errors import Conflict, Invalid, NotFound
from backend.core.notifications import service as notifications
from backend.core.reminders import recurrence

if TYPE_CHECKING:
    from backend.core.auth.deps import User

STATUSES = ("open", "done", "voided", "snoozed")
TITLE_MAX = 200
NOTE_MAX = 2000
FIRE_BATCH = 100
LINK = "/reminders"  # where a reminder without a record points
EDITABLE = frozenset({"title", "note", "due_at", "repeat"})
_SELECT = "SELECT r.*, u.name AS owner_name FROM core_reminders r JOIN core_users u ON u.id = r.owner_user_id"


def _zone(user: User) -> ZoneInfo:
    try:
        return ZoneInfo(user.tz) if user.tz else localtime.tz()
    except Exception:
        return localtime.tz()


def _instant(value: str | None, zone: ZoneInfo, field: str) -> str:
    try:
        if not isinstance(value, str):
            raise ValueError
        return clock.normalize(value, zone)
    except ValueError:
        raise Invalid(f"{field} must be an ISO date-time") from None


def _text(value: str | None, field: str, limit: int, required: bool) -> str:
    text = (value or "").strip()
    if required and not text:
        raise Invalid(f"{field} is required")
    if len(text) > limit:
        raise Invalid(f"{field} can be at most {limit} characters")
    return text


def _repeat(freq: str | None, due_at: str, zone: ZoneInfo) -> str | None:
    # simplification: moving due_at re-anchors the series, so editing the time of a clamped
    # occurrence (Feb 28 of a Jan 31 monthly) moves later months to the 28th; upgrade path: keep
    # the anchor when only the time changed, as the donor does.
    if freq is None:
        return None
    if freq not in recurrence.REPEATS:
        raise Invalid(f"repeat.freq must be one of {', '.join(recurrence.REPEATS)}")
    local = clock.parse(due_at).astimezone(zone)
    return json.dumps({"freq": freq, "anchor": local.date().isoformat(), "time": local.strftime("%H:%M"), "tz": zone.key})


def _shape_in(conn: db.Conn, user: User, rows: list) -> list[dict]:
    titles = {
        t: entities.titles_for(user, conn, t, [r["entity_id"] for r in rows if r["entity_type"] == t])
        for t in {r["entity_type"] for r in rows if r["entity_type"]}
    }
    return [
        {
            "id": r["id"], "owner": {"id": r["owner_user_id"], "name": r["owner_name"]}, "mine": r["owner_user_id"] == user.id,
            "entity_type": r["entity_type"], "entity_id": r["entity_id"],
            "entity_title": titles[r["entity_type"]].get(r["entity_id"]) if r["entity_type"] else None,
            "link": entities.url_for(r["entity_type"], r["entity_id"]) if r["entity_type"] else None,
            "title": r["title"], "note": r["note"], "due_at": r["due_at"],
            "repeat": json.loads(r["repeat"]) if r["repeat"] else None, "series_id": r["series_id"],
            "status": r["status"], "void_reason": r["void_reason"], "fired_at": r["fired_at"],
            "created_at": r["created_at"], "updated_at": r["updated_at"],
        }
        for r in rows
    ]  # fmt: skip


def _own_in(conn: db.Conn, user: User, reminder_id: int):
    """The caller's reminder; NotFound for anyone else's, or when its record is no longer readable."""
    row = conn.execute(f"{_SELECT} WHERE r.id = ? AND r.owner_user_id = ?", (reminder_id, user.id)).fetchone()
    if row is None or not notifications.can_read_in(conn, user, row["entity_type"], row["entity_id"]):
        raise NotFound()
    return row


def _get_in(conn: db.Conn, user: User, reminder_id: int) -> dict:
    return _shape_in(conn, user, [conn.execute(f"{_SELECT} WHERE r.id = ?", (reminder_id,)).fetchone()])[0]


def _editable(row) -> None:
    if row["status"] not in ("open", "snoozed"):
        raise Conflict(f"This reminder is {row['status']}; only an open or snoozed one can change")


# ── Create, list ─────────────────────────────────────────────────────────────


def create_in(
    conn: db.Conn, user: User, *, title: str, due_at: str, note: str = "", repeat: str | None = None,
    entity_type: str | None = None, entity_id: int | None = None,
) -> dict:
    """A reminder owned by `user`. `due_at` is ISO; without an offset it is read in the user's
    zone (else the install's). `repeat` is a freq or None. A record needs `authorize(read)`."""
    if (entity_type is None) != (entity_id is None):
        raise Invalid("entity_type and entity_id go together")
    if entity_type is not None:
        entities.authorize(user, conn, entity_type, entity_id, "read")
    zone = _zone(user)
    due = _instant(due_at, zone, "due_at")
    now = clock.now_iso()
    rid = conn.execute(
        """INSERT INTO core_reminders (owner_user_id, entity_type, entity_id, title, note, due_at, repeat, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user.id, entity_type, entity_id, _text(title, "title", TITLE_MAX, True), _text(note, "note", NOTE_MAX, False),
         due, _repeat(repeat, due, zone), now, now),
    ).lastrowid  # fmt: skip
    conn.execute("UPDATE core_reminders SET series_id = id WHERE id = ?", (rid,))
    return _get_in(conn, user, rid)


def create(user: User, **fields) -> dict:
    with db.transaction() as conn:
        return create_in(conn, user, **fields)


def list_mine_in(
    conn: db.Conn, user: User, *, from_: str | None = None, to: str | None = None,
    status: str | None = None, limit: int | None = None,
) -> list[dict]:
    """The caller's reminders with `from_ <= due_at < to`, soonest first. Reminders on records
    the caller can no longer read are left out."""
    where, params = ["r.owner_user_id = ?"], [user.id]
    if status is not None:
        if status not in STATUSES:
            raise Invalid(f"status must be one of {', '.join(STATUSES)}")
        where.append("r.status = ?")
        params.append(status)
    zone = _zone(user)
    if from_:
        where.append("r.due_at >= ?")
        params.append(_instant(from_, zone, "from"))
    if to:
        where.append("r.due_at < ?")
        params.append(_instant(to, zone, "to"))
    limit, _ = pagination.window(limit)
    # simplification: unreadable rows are dropped after LIMIT, so such a page can come back short;
    # they are rare (fire time voids them). Upgrade path: re-query like notifications' _visible.
    rows = conn.execute(f"{_SELECT} WHERE {' AND '.join(where)} ORDER BY r.due_at, r.id LIMIT ?", (*params, limit)).fetchall()
    return _shape_in(conn, user, [r for r in rows if notifications.can_read_in(conn, user, r["entity_type"], r["entity_id"])])


def list_mine(user: User, **filters) -> list[dict]:
    return list_mine_in(db.get_conn(), user, **filters)


def list_for_record_in(conn: db.Conn, user: User, entity_type: str, entity_id: int) -> list[dict]:
    """Every member's reminders on a record the caller can read (`mine` marks the caller's):
    open and snoozed first, then by due time; at most pagination.MAX_LIMIT."""
    entities.authorize(user, conn, entity_type, entity_id, "read")
    rows = conn.execute(
        f"""{_SELECT} WHERE r.entity_type = ? AND r.entity_id = ?
            ORDER BY r.status IN ('open', 'snoozed') DESC, r.due_at, r.id LIMIT ?""",
        (entity_type, entity_id, pagination.MAX_LIMIT),
    ).fetchall()
    return _shape_in(conn, user, rows)


def list_for_record(user: User, entity_type: str, entity_id: int) -> list[dict]:
    return list_for_record_in(db.get_conn(), user, entity_type, entity_id)


# ── Change ───────────────────────────────────────────────────────────────────


def update_in(conn: db.Conn, user: User, reminder_id: int, fields: dict) -> dict:
    """Change title, note, due_at or repeat (a freq or None) of an open or snoozed reminder.
    A new due_at re-arms it: status open, fired_at cleared."""
    if unknown := set(fields) - EDITABLE:
        raise Invalid(f"Cannot change: {', '.join(sorted(unknown))}")
    row = _own_in(conn, user, reminder_id)
    _editable(row)
    zone, sets = _zone(user), {}
    if "title" in fields:
        sets["title"] = _text(fields["title"], "title", TITLE_MAX, True)
    if "note" in fields:
        sets["note"] = _text(fields["note"], "note", NOTE_MAX, False)
    due = row["due_at"]
    if "due_at" in fields:
        due = sets["due_at"] = _instant(fields["due_at"], zone, "due_at")
        sets.update(status="open", fired_at=None)
    if "repeat" in fields or "due_at" in fields:
        freq = fields["repeat"] if "repeat" in fields else (json.loads(row["repeat"])["freq"] if row["repeat"] else None)
        sets["repeat"] = _repeat(freq, due, zone)
    if sets:
        assignments = ", ".join(f"{k} = ?" for k in sets)  # keys are this function's own
        conn.execute(f"UPDATE core_reminders SET {assignments}, updated_at = ? WHERE id = ?", (*sets.values(), clock.now_iso(), reminder_id))
    return _get_in(conn, user, reminder_id)


def update(user: User, reminder_id: int, fields: dict) -> dict:
    with db.transaction() as conn:
        return update_in(conn, user, reminder_id, fields)


def snooze_in(conn: db.Conn, user: User, reminder_id: int, until: str) -> dict:
    """Move an open or snoozed reminder to a later `until` (in the future); it fires again then."""
    row = _own_in(conn, user, reminder_id)
    _editable(row)
    until = _instant(until, _zone(user), "until")
    if until <= clock.now_iso():
        raise Invalid("until must be in the future")
    conn.execute(
        "UPDATE core_reminders SET status = 'snoozed', due_at = ?, fired_at = NULL, updated_at = ? WHERE id = ?",
        (until, clock.now_iso(), reminder_id),
    )
    return _get_in(conn, user, reminder_id)


def snooze(user: User, reminder_id: int, until: str) -> dict:
    with db.transaction() as conn:
        return snooze_in(conn, user, reminder_id, until)


def complete_in(conn: db.Conn, user: User, reminder_id: int) -> dict:
    """Mark done (idempotent). Completing a repeating occurrence before it fired still schedules
    the next one."""
    row = _own_in(conn, user, reminder_id)
    if row["status"] != "done":
        _editable(row)
        conn.execute("UPDATE core_reminders SET status = 'done', updated_at = ? WHERE id = ?", (clock.now_iso(), reminder_id))
        if row["repeat"]:
            _spawn_next_in(conn, row)
    return _get_in(conn, user, reminder_id)


def complete(user: User, reminder_id: int) -> dict:
    with db.transaction() as conn:
        return complete_in(conn, user, reminder_id)


def delete_in(conn: db.Conn, user: User, reminder_id: int) -> None:
    """Delete one occurrence. Deleting a series' newest occurrence ends the series."""
    _own_in(conn, user, reminder_id)
    conn.execute("DELETE FROM core_reminders WHERE id = ?", (reminder_id,))


def delete(user: User, reminder_id: int) -> None:
    with db.transaction() as conn:
        delete_in(conn, user, reminder_id)


# ── Firing ───────────────────────────────────────────────────────────────────


def _spawn_next_in(conn: db.Conn, row) -> int:
    """Insert the series' next occurrence after this one, unless a later one exists. Returns 0 or 1."""
    if conn.execute("SELECT 1 FROM core_reminders WHERE series_id = ? AND id > ?", (row["series_id"], row["id"])).fetchone():
        return 0
    rep = json.loads(row["repeat"])
    _, at = recurrence.next_due(
        rep["freq"], date.fromisoformat(rep["anchor"]), time.fromisoformat(rep["time"]),
        after=max(clock.parse(row["due_at"]), clock.now()), zone=ZoneInfo(rep["tz"]),
    )  # fmt: skip
    now = clock.now_iso()
    conn.execute(
        """INSERT INTO core_reminders (owner_user_id, entity_type, entity_id, title, note, due_at, repeat, series_id, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (row["owner_user_id"], row["entity_type"], row["entity_id"], row["title"], row["note"], clock.to_iso(at),
         row["repeat"], row["series_id"], now, now),
    )  # fmt: skip
    return 1


def fire_due_in(conn: db.Conn) -> dict:
    """Fire one batch of due reminders in the caller's transaction. Returns counts."""
    now = clock.now_iso()
    rows = conn.execute(
        """SELECT * FROM core_reminders WHERE status IN ('open', 'snoozed') AND fired_at IS NULL AND due_at <= ?
            ORDER BY due_at, id LIMIT ?""",
        (now, FIRE_BATCH),
    ).fetchall()
    counts = {"due": len(rows), "fired": 0, "voided": 0, "spawned": 0}
    for row in rows:
        owner = notifications.user_in(conn, row["owner_user_id"])
        entity = (row["entity_type"], row["entity_id"]) if row["entity_type"] else None
        reason = None
        if owner is None or not owner.is_active:
            reason = "owner is no longer active"
        elif not notifications.can_read_in(conn, owner, *(entity or (None, None))):
            reason = "owner can no longer read the record"
        if reason:
            conn.execute(
                "UPDATE core_reminders SET status = 'voided', void_reason = ?, updated_at = ? WHERE id = ?", (reason, now, row["id"])
            )
            counts["voided"] += 1
            continue
        conn.execute("UPDATE core_reminders SET status = 'open', fired_at = ?, updated_at = ? WHERE id = ?", (now, now, row["id"]))
        notifications.deliver_in(
            conn, f"Reminder: {row['title']}", row["note"], user_id=owner.id, entity=entity, link=None if entity else LINK
        )
        counts["fired"] += 1
        if row["repeat"]:
            counts["spawned"] += _spawn_next_in(conn, row)
    return counts


def fire_due(cancel: threading.Event | None = None) -> dict:
    """Job core.reminders_fire_due: fire every due reminder, one transaction per batch."""
    totals = {"due": 0, "fired": 0, "voided": 0, "spawned": 0}
    while not (cancel is not None and cancel.is_set()):
        with db.transaction() as conn:
            counts = fire_due_in(conn)
        totals = {k: totals[k] + counts[k] for k in totals}
        if counts["due"] < FIRE_BATCH:
            break
    return totals


# ── Hooks ────────────────────────────────────────────────────────────────────


def on_entity_deleted_in(conn: db.Conn, entity_type: str, entity_id: int) -> None:
    conn.execute(
        """UPDATE core_reminders SET status = 'voided', void_reason = 'record deleted', updated_at = ?
            WHERE entity_type = ? AND entity_id = ? AND status IN ('open', 'snoozed')""",
        (clock.now_iso(), entity_type, entity_id),
    )


def on_entity_merged_in(conn: db.Conn, entity_type: str, target_id: int, source_id: int) -> None:
    conn.execute(
        "UPDATE core_reminders SET entity_id = ? WHERE entity_type = ? AND entity_id = ?", (target_id, entity_type, source_id)
    )
