"""The activity log: calls, emails and meetings that happened, on a deal and/or a person.
`actor_user_id` is who did it (credit for the work, not ownership of the record). Ported from
CakeCRM's crm/service.py activity section (docs/PROVENANCE.md).

An activity is part of its deal: reading or writing one authorizes the deal (and the person)
it hangs off. Archived deals keep their history readable."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.apps.crm import scoring
from backend.apps.crm.common import ENTITY, MAX_TEXT
from backend.core import clock, db, entities, pagination
from backend.core.errors import Forbidden, Invalid, NotFound

if TYPE_CHECKING:
    from backend.core.auth.deps import User

SELECT = """SELECT a.*, d.title AS deal_title, p.name AS person_name, u.name AS actor_name
              FROM crm_activity_log a
              LEFT JOIN crm_deals d ON d.id = a.deal_id
              LEFT JOIN core_people p ON p.id = a.person_id
              LEFT JOIN core_users u ON u.id = a.actor_user_id"""


def _links_in(conn: db.Conn, user: User, deal_id: int | None, person_id: int | None, action: str) -> None:
    """The activity's deal and person must be readable (write: the deal writable)."""
    if deal_id is not None:
        entities.authorize(user, conn, ENTITY, deal_id, action)
    if person_id is not None:
        entities.authorize(user, conn, "core.person", person_id, "read")


def _row_in(conn: db.Conn, user: User, activity_id: int, action: str) -> dict:
    row = conn.execute(f"{SELECT} WHERE a.id = ?", (activity_id,)).fetchone()
    if row is None:
        raise NotFound()
    _links_in(conn, user, row["deal_id"], row["person_id"], action)
    return dict(row)


def list_in(
    conn: db.Conn, user: User, *, deal_id: int | None = None, person_id: int | None = None, limit: int | None = 50
) -> list[dict]:
    """Newest first, optionally one deal's or one person's."""
    if not entities.get(ENTITY).can_read(user, conn, 0):
        raise Forbidden()
    _links_in(conn, user, deal_id, person_id, "read")
    where, params = [], []
    for column, value in (("deal_id", deal_id), ("person_id", person_id)):
        if value is not None:
            where.append(f"a.{column} = ?")
            params.append(value)
    limit, _ = pagination.window(limit)
    rows = conn.execute(
        f"{SELECT} {'WHERE ' + ' AND '.join(where) if where else ''} ORDER BY a.created_at DESC, a.id DESC LIMIT ?",
        (*params, limit),
    )
    return [dict(r) for r in rows]


def list_(user: User, **filters) -> list[dict]:
    return list_in(db.get_conn(), user, **filters)


def log_in(conn: db.Conn, user: User, activity: str, note: str = "", *, deal_id: int | None = None, person_id: int | None = None) -> dict:
    """Record something that happened, credited to `user` (the system principal: no human)."""
    text = (activity or "").strip()
    if not text:
        raise Invalid("activity is required (call, email, meeting, …)")
    if len(note or "") > MAX_TEXT:
        raise Invalid(f"note too long (max {MAX_TEXT} characters)")
    try:
        _links_in(conn, user, deal_id, person_id, "write")
    except NotFound:
        raise Invalid("deal_id or person_id: no such record") from None
    actor = None if user.role == "system" else user.id
    cur = conn.execute(
        "INSERT INTO crm_activity_log (activity, note, deal_id, person_id, actor_user_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (text[:100], note or "", deal_id, person_id, actor, clock.now_iso()),
    )
    if deal_id is not None:
        conn.execute("UPDATE crm_deals SET touch_dirty = 1 WHERE id = ?", (deal_id,))
    scoring.refresh_in(conn, deal_ids=[deal_id], person_ids=[person_id])
    return dict(conn.execute(f"{SELECT} WHERE a.id = ?", (cur.lastrowid,)).fetchone())


def log(user: User, activity: str, note: str = "", **links) -> dict:
    with db.transaction() as conn:
        return log_in(conn, user, activity, note, **links)


def update_in(conn: db.Conn, user: User, activity_id: int, fields: dict) -> dict:
    row = _row_in(conn, user, activity_id, "write")
    changes = {k: v for k, v in fields.items() if k in ("activity", "note") and v is not None and v != row[k]}
    if "activity" in changes and not changes["activity"].strip():
        raise Invalid("activity cannot be empty")
    if changes:
        sets = ", ".join(f"{k} = ?" for k in changes)  # activity, note
        conn.execute(f"UPDATE crm_activity_log SET {sets} WHERE id = ?", (*changes.values(), activity_id))
        if row["deal_id"] is not None:
            conn.execute("UPDATE crm_deals SET touch_dirty = 1 WHERE id = ?", (row["deal_id"],))
    return dict(conn.execute(f"{SELECT} WHERE a.id = ?", (activity_id,)).fetchone())


def update(user: User, activity_id: int, fields: dict) -> dict:
    with db.transaction() as conn:
        return update_in(conn, user, activity_id, fields)


def delete_in(conn: db.Conn, user: User, activity_id: int) -> None:
    row = _row_in(conn, user, activity_id, "write")
    conn.execute("DELETE FROM crm_activity_log WHERE id = ?", (activity_id,))
    if row["deal_id"] is not None:
        conn.execute("UPDATE crm_deals SET touch_dirty = 1 WHERE id = ?", (row["deal_id"],))
    scoring.refresh_in(conn, deal_ids=[row["deal_id"]], person_ids=[row["person_id"]])


def delete(user: User, activity_id: int) -> None:
    with db.transaction() as conn:
        delete_in(conn, user, activity_id)
