"""Timelines: notes and field changes on any registered entity.

Every read and write goes through `entities.authorize` (a note needs write access to its
record). `record_changes_in` is how a service reports an edit it already authorized: one
`field_change` timeline row, one change-log row per changed field, the sync on_record_changed
subscribers, and the durable after_record_changed outbox rows, all in the caller's transaction.

Mentions: a note body names users as `@[Name](user:ID)`. `add_note_in` stores a
core_timeline_mentions row for each mentioned active human user who can read the record, and
notifies each of them except the author (`notifications.deliver_in`, in the note's transaction).
Anyone else named in the body gets neither. Search has a table (core_timeline_fts) but no service yet.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from backend.core import changelog, clock, db, entities, pagination
from backend.core.errors import Invalid
from backend.core.notifications import service as notifications

if TYPE_CHECKING:
    from backend.core.auth.deps import User

MAX_BODY = 10_000
MAX_MENTIONS = 20  # a note naming more people than this is a broadcast, not a mention
EXCERPT_LEN = 200
MENTION = re.compile(r"@\[([^\]\n]{1,100})\]\(user:(\d{1,12})\)")
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


def add_note_in(conn: db.Conn, user: User, entity_type: str, entity_id: int, body: str) -> dict:
    entities.authorize(user, conn, entity_type, entity_id, "write")
    text = (body or "").strip()
    if not text:
        raise Invalid("A note needs some text.")
    if len(text) > MAX_BODY:
        raise Invalid(f"A note can be at most {MAX_BODY} characters.")
    entry = _insert_in(conn, entity_type, entity_id, "note", text, None, user.id)
    _mention_in(conn, user, entity_type, entity_id, entry)
    return entry


def mentioned_ids(body: str) -> list[int]:
    """User ids named by `@[Name](user:ID)` markup, first mention first, at most MAX_MENTIONS."""
    return list(dict.fromkeys(int(m.group(2)) for m in MENTION.finditer(body or "")))[:MAX_MENTIONS]


def plain_text(body: str) -> str:
    """The body with mention markup shown as `@Name`."""
    return MENTION.sub(lambda m: f"@{m.group(1)}", body or "")


def _mention_in(conn: db.Conn, author: User, entity_type: str, entity_id: int, entry: dict) -> None:
    ids = mentioned_ids(entry["body"])
    if not ids:
        return
    entity = entities.get(entity_type)
    record = entity.title_fn(conn, [entity_id]).get(entity_id) or f"#{entity_id}"
    text = " ".join(plain_text(entry["body"]).split())
    excerpt = text if len(text) <= EXCERPT_LEN else text[: EXCERPT_LEN - 1].rstrip() + "…"
    for uid in ids:
        target = notifications.user_in(conn, uid)
        if target is None or target.role == "system" or not target.is_active:
            continue
        if not notifications.can_read_in(conn, target, entity_type, entity_id):
            continue  # stored copies obey the record's rules: no mention row, no notification
        conn.execute(
            "INSERT OR IGNORE INTO core_timeline_mentions (timeline_id, user_id, display_name) VALUES (?, ?, ?)",
            (entry["id"], target.id, target.name or target.email),
        )
        if target.id != author.id:
            title = f"{author.name or 'A teammate'} mentioned you on {entity.label} — {record}"
            notifications.deliver_in(conn, title, excerpt, user_id=target.id, entity=(entity_type, entity_id))


def mentionable_in(conn: db.Conn, q: str | None = None, limit: int = 20) -> list[dict]:
    """Active human users for the mention picker, matching `q` on name or email, by name."""
    sql = "SELECT id, coalesce(nullif(trim(name), ''), email) AS name FROM core_users WHERE role != 'system' AND is_active = 1"
    params: list = []
    if q and q.strip():
        like = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        sql += " AND (name LIKE ? ESCAPE '\\' OR email LIKE ? ESCAPE '\\')"
        params += [like, like]
    return [dict(r) for r in conn.execute(f"{sql} ORDER BY name COLLATE NOCASE, id LIMIT ?", (*params, limit))]


def mentionable(q: str | None = None, limit: int = 20) -> list[dict]:
    return mentionable_in(db.get_conn(), q, limit)


def add_note(user: User, entity_type: str, entity_id: int, body: str) -> dict:
    with db.transaction() as conn:
        return add_note_in(conn, user, entity_type, entity_id, body)


def list_for(user: User, entity_type: str, entity_id: int, limit: int | None = None, offset: int | None = None) -> list[dict]:
    """Newest first."""
    conn = db.get_conn()
    entities.authorize(user, conn, entity_type, entity_id, "read")
    limit, offset = pagination.window(limit, offset)
    rows = conn.execute(
        f"""{_SELECT} WHERE t.entity_type = ? AND t.entity_id = ? AND t.archived_at IS NULL
            ORDER BY t.created_at DESC, t.id DESC LIMIT ? OFFSET ?""",
        (entity_type, entity_id, limit, offset),
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
