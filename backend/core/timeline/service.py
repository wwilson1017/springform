"""Timelines: notes and field changes on any registered entity.

Every read and write goes through `entities.authorize` (a note needs write access to its
record). `record_changes_in` is how a service reports an edit it already authorized: one
`field_change` timeline row, one change-log row per changed field, the sync on_record_changed
subscribers, and the durable after_record_changed outbox rows, all in the caller's transaction.
Mentions and search have tables (core_timeline_mentions, core_timeline_fts) but no service yet.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from backend.core import changelog, clock, db, entities, pagination
from backend.core.errors import Invalid

if TYPE_CHECKING:
    from backend.core.auth.deps import User

MAX_BODY = 10_000
NOTE_KINDS = ("note", "comment")
UNTRACKED = frozenset({"id", "created_at", "updated_at"})
_SELECT = """SELECT t.id, t.kind, t.body, t.changes, t.created_at, t.author_user_id, u.name AS author_name
               FROM core_timeline t LEFT JOIN core_users u ON u.id = t.author_user_id"""


def _entry(row) -> dict:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "body": row["body"],
        "changes": json.loads(row["changes"]) if row["changes"] else None,
        "author": {"id": row["author_user_id"], "name": row["author_name"]} if row["author_user_id"] is not None else None,
        "created_at": row["created_at"],
    }


def _insert_in(conn: db.Conn, entity_type: str, entity_id: int, kind: str, body: str, changes: Any, user_id: int | None) -> dict:
    cur = conn.execute(
        """INSERT INTO core_timeline (entity_type, entity_id, kind, body, changes, author_user_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (entity_type, entity_id, kind, body, json.dumps(changes) if changes is not None else None, user_id, clock.now_iso()),
    )
    return _entry(conn.execute(f"{_SELECT} WHERE t.id = ?", (cur.lastrowid,)).fetchone())


def add_note_in(conn: db.Conn, user: User, entity_type: str, entity_id: int, body: str, kind: str = "note") -> dict:
    entities.authorize(user, conn, entity_type, entity_id, "write")
    if kind not in NOTE_KINDS:
        raise Invalid(f"kind must be one of {', '.join(NOTE_KINDS)}")
    text = (body or "").strip()
    if not text:
        raise Invalid("A note needs some text.")
    if len(text) > MAX_BODY:
        raise Invalid(f"A note can be at most {MAX_BODY} characters.")
    return _insert_in(conn, entity_type, entity_id, kind, text, None, user.id)


def add_note(user: User, entity_type: str, entity_id: int, body: str, kind: str = "note") -> dict:
    with db.transaction() as conn:
        return add_note_in(conn, user, entity_type, entity_id, body, kind)


def list_for(user: User, entity_type: str, entity_id: int, before: int | None = None, limit: int | None = None) -> list[dict]:
    """Newest first. Pages back with `before` (the last entry id seen); `limit` 50 by default, at most 200."""
    conn = db.get_conn()
    entities.authorize(user, conn, entity_type, entity_id, "read")
    rows = conn.execute(
        f"""{_SELECT} WHERE t.entity_type = ? AND t.entity_id = ? AND t.archived_at IS NULL AND t.id < ?
            ORDER BY t.id DESC LIMIT ?""",
        (entity_type, entity_id, 2**62 if before is None else before, pagination.window(limit)[0]),
    )
    return [_entry(r) for r in rows]


def record_changes_in(
    conn: db.Conn, entity_type: str, entity_id: int, before: dict, after: dict, user_id: int | None
) -> dict | None:
    """Report an authorized edit. `before`/`after` are the record's fields; keys present in both
    whose values differ are changes (id/created_at/updated_at are not). Returns the timeline
    entry, or None when nothing changed."""
    changes = [
        {"field": k, "old": before[k], "new": v}
        for k, v in after.items()
        if k in before and k not in UNTRACKED and before[k] != v
    ]
    if not changes:
        return None
    entry = _insert_in(conn, entity_type, entity_id, "field_change", "", changes, user_id)
    for c in changes:
        changelog.record_in(conn, entity_type, entity_id, c["field"], c["old"], c["new"], user_id)
    entities.on_record_changed_in(conn, entity_type, entity_id, changes, user_id)
    entities.after_record_changed_in(conn, entity_type, entity_id, changes, user_id)
    return entry


def on_entity_deleted_in(conn: db.Conn, entity_type: str, entity_id: int) -> None:
    conn.execute("DELETE FROM core_timeline WHERE entity_type = ? AND entity_id = ?", (entity_type, entity_id))


def on_entity_merged_in(conn: db.Conn, entity_type: str, target_id: int, source_id: int) -> None:
    """Rows move to the survivor keeping their author and time."""
    conn.execute(
        "UPDATE core_timeline SET entity_id = ? WHERE entity_type = ? AND entity_id = ?",
        (target_id, entity_type, source_id),
    )
