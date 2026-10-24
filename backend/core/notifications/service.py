"""Notifications: in-app rows (exactly-once) and external deliveries (at-least-once).

`deliver_in` writes one `core_notifications` row per recipient in the caller's transaction, plus
one `queued` delivery row per external channel that is enabled for that recipient (web push when
they have a live subscription; others via `register_channel`). The `core.notifications_flush`
job sends queued deliveries outside any transaction and records `sent_at` afterwards, so a crash
in between sends again: external channels are at-least-once, and the payload carries
`notification_id` so a receiver can drop the duplicate.

A notification remembers its record (docs/agents/authorization.md, stored copies):
- listing, counting and reading re-run `authorize(read)` for the recipient and hide rows that
  fail by setting `suppressed_at`;
- `flush` re-checks before sending and marks the delivery `dropped` when access is gone.
A message already delivered externally cannot be recalled.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from backend.core import clock, db, entities, pagination
from backend.core.auth.deps import User
from backend.core.errors import NotFound

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger(__name__)

TITLE_MAX = 200
MESSAGE_MAX = 5000
LINK_MAX = 500
MAX_ATTEMPTS = 5
FLUSH_BATCH = 100
_USER_COLS = "id, email, name, role, tz, is_active, token_epoch"
_COLS = "id, user_id, title, message, entity_type, entity_id, link, created_at, read_at"


class Undeliverable(Exception):
    """Raised by a channel's send when retrying cannot help; the delivery is marked `dropped`."""


@dataclass(frozen=True)
class Channel:
    name: str
    send: Callable[[dict], None]
    enabled_in: Callable[[db.Conn, int], bool] | None


_CHANNELS: dict[str, Channel] = {}


def register_channel(
    name: str, send: Callable[[dict], None], *, enabled_in: Callable[[db.Conn, int], bool] | None = None
) -> None:
    """Add an external channel. `send(payload)` runs in `flush`, outside any transaction; it
    returns on success, raises `Undeliverable` to drop the delivery, and raises anything else to
    retry (up to MAX_ATTEMPTS flushes). `payload` is {notification_id, user_id, title, message,
    link, entity_type, entity_id}. `enabled_in(conn, user_id)` says whether the user receives this
    channel at all (default: everyone); it runs inside `deliver_in`'s transaction."""
    if name in _CHANNELS:
        raise ValueError(f"Notification channel {name!r} is registered twice")
    _CHANNELS[name] = Channel(name, send, enabled_in)


def channels() -> dict[str, Channel]:
    return dict(_CHANNELS)


# ── Who may see what ─────────────────────────────────────────────────────────


def user_in(conn: db.Conn, user_id: int) -> User | None:
    row = conn.execute(f"SELECT {_USER_COLS} FROM core_users WHERE id = ?", (user_id,)).fetchone()
    return User.from_row(dict(row)) if row else None


def can_read_in(conn: db.Conn, user: User, entity_type: str | None, entity_id: int | None) -> bool:
    """`authorize(read)` as a yes/no; a row without a record is always readable."""
    if entity_type is None:
        return True
    try:
        entities.authorize(user, conn, entity_type, entity_id, "read")
    except NotFound:
        return False
    return True


def _recipients_in(conn: db.Conn, user_id: int | None, entity: tuple[str, int] | None) -> list[int]:
    """Active human users who may read `entity`: one user, or everyone when user_id is None."""
    where, params = "role != 'system' AND is_active = 1", []
    if user_id is not None:
        where, params = f"{where} AND id = ?", [user_id]
    users = [User.from_row(dict(r)) for r in conn.execute(f"SELECT {_USER_COLS} FROM core_users WHERE {where} ORDER BY id", params)]
    if entity is None:
        return [u.id for u in users]
    return [u.id for u in users if can_read_in(conn, u, *entity)]


def clean_link(link: str | None) -> str | None:
    """An in-app path, or None: `/crm/...` passes; `//host`, a scheme, a backslash and any
    whitespace or control character do not."""
    if not isinstance(link, str) or not link or len(link) > LINK_MAX:
        return None
    if not link.startswith("/") or link.startswith("//") or "\\" in link:
        return None
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in link):
        return None
    return link


# ── Writing ──────────────────────────────────────────────────────────────────


def deliver_in(
    conn: db.Conn, title: str, message: str, *, user_id: int | None = None,
    entity: tuple[str, int] | None = None, link: str | None = None,
) -> list[int]:
    """Notify one user (`user_id`) or every active human user (`user_id=None`) who may read
    `entity` = (entity_type, entity_id). Returns the new notification ids, one per recipient;
    empty when nobody qualifies (an inactive user, the system principal, or a user who cannot
    read the record). `link` defaults to the record's URL. Raises NotFound for an unknown entity
    type or a missing record."""
    if entity is not None:
        entity = (entity[0], int(entity[1]))
        entities.assert_exists(conn, *entity)
        if link is None:
            link = entities.url_for(*entity)
    title = (title or "").strip()[:TITLE_MAX] or "Notification"
    message = (message or "").strip()[:MESSAGE_MAX]
    link = clean_link(link)
    now = clock.now_iso()
    ids = []
    for uid in _recipients_in(conn, user_id, entity):
        nid = conn.execute(
            """INSERT INTO core_notifications (user_id, title, message, entity_type, entity_id, link, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (uid, title, message, *(entity or (None, None)), link, now),
        ).lastrowid
        for ch in _CHANNELS.values():
            if ch.enabled_in is None or ch.enabled_in(conn, uid):
                conn.execute("INSERT INTO core_notification_deliveries (notification_id, channel) VALUES (?, ?)", (nid, ch.name))
        ids.append(nid)
    return ids


def deliver(
    title: str, message: str, *, user_id: int | None = None,
    entity: tuple[str, int] | None = None, link: str | None = None,
) -> list[int]:
    with db.transaction() as conn:
        return deliver_in(conn, title, message, user_id=user_id, entity=entity, link=link)


# ── Reading (re-authorized) ──────────────────────────────────────────────────


def _suppress_in(conn: db.Conn, ids: Iterable[int]) -> None:
    conn.execute(
        "UPDATE core_notifications SET suppressed_at = ? WHERE id IN (SELECT value FROM json_each(?)) AND suppressed_at IS NULL",
        (clock.now_iso(), json.dumps(list(ids))),
    )


def _suppress(ids: list[int]) -> None:
    with db.transaction() as conn:
        _suppress_in(conn, ids)


def _visible(conn: db.Conn, user: User, sql: str, params: tuple, suppress: Callable[[list[int]], None]) -> list[dict]:
    """Rows of `sql` the user may still read. Rows that fail are suppressed and the query re-run,
    so a page is never short because of them (each pass suppresses at least one row)."""
    while True:
        rows = [dict(r) for r in conn.execute(sql, params)]
        hidden = [r["id"] for r in rows if not can_read_in(conn, user, r["entity_type"], r["entity_id"])]
        if not hidden:
            return rows
        suppress(hidden)


def _list(conn: db.Conn, user: User, unread: bool, limit: int | None, suppress) -> list[dict]:
    limit, _ = pagination.window(limit)
    sql = f"""SELECT {_COLS} FROM core_notifications
               WHERE user_id = ? AND suppressed_at IS NULL {"AND read_at IS NULL" if unread else ""}
               ORDER BY created_at DESC, id DESC LIMIT ?"""
    return _visible(conn, user, sql, (user.id, limit), suppress)


def list_for_in(conn: db.Conn, user: User, *, unread: bool = False, limit: int | None = None) -> list[dict]:
    """The user's notifications, newest first, after re-authorization."""
    return _list(conn, user, unread, limit, lambda ids: _suppress_in(conn, ids))


def list_for(user: User, *, unread: bool = False, limit: int | None = None) -> list[dict]:
    # Reads outside the write lock; takes it only when a row has to be suppressed.
    return _list(db.get_conn(), user, unread, limit, _suppress)


def _unread_count(conn: db.Conn, user: User, suppress) -> int:
    # simplification: re-checks every unread row that names a record on each count, fine to a few
    # thousand unread rows; upgrade path: cap the scan and show "99+".
    sql = "SELECT id, entity_type, entity_id FROM core_notifications WHERE user_id = ? AND suppressed_at IS NULL AND read_at IS NULL"
    return len(_visible(conn, user, sql, (user.id,), suppress))


def unread_count_in(conn: db.Conn, user: User) -> int:
    return _unread_count(conn, user, lambda ids: _suppress_in(conn, ids))


def unread_count(user: User) -> int:
    return _unread_count(db.get_conn(), user, _suppress)


def _mark_read_in(conn: db.Conn, user: User, notification_id: int) -> dict | None:
    """The row marked read; None when its record is no longer readable (the row is suppressed)."""
    row = conn.execute(
        f"SELECT {_COLS} FROM core_notifications WHERE id = ? AND user_id = ? AND suppressed_at IS NULL",
        (notification_id, user.id),
    ).fetchone()
    if row is None:
        raise NotFound()
    if not can_read_in(conn, user, row["entity_type"], row["entity_id"]):
        _suppress_in(conn, [notification_id])
        return None
    conn.execute("UPDATE core_notifications SET read_at = coalesce(read_at, ?) WHERE id = ?", (clock.now_iso(), notification_id))
    return dict(conn.execute(f"SELECT {_COLS} FROM core_notifications WHERE id = ?", (notification_id,)).fetchone())


def mark_read_in(conn: db.Conn, user: User, notification_id: int) -> dict:
    """Mark one of the user's notifications read. NotFound when it is not theirs, is hidden, or
    its record is no longer readable (which hides it, if the caller commits)."""
    row = _mark_read_in(conn, user, notification_id)
    if row is None:
        raise NotFound()
    return row


def mark_read(user: User, notification_id: int) -> dict:
    with db.transaction() as conn:
        row = _mark_read_in(conn, user, notification_id)
    if row is None:  # raised after COMMIT, so the suppression sticks
        raise NotFound()
    return row


def mark_all_read_in(conn: db.Conn, user: User) -> int:
    """Marks every unread, unhidden row read (a row whose record went unreadable is hidden on the
    next listing either way). Returns how many rows changed."""
    return conn.execute(
        "UPDATE core_notifications SET read_at = ? WHERE user_id = ? AND read_at IS NULL AND suppressed_at IS NULL",
        (clock.now_iso(), user.id),
    ).rowcount


def mark_all_read(user: User) -> int:
    with db.transaction() as conn:
        return mark_all_read_in(conn, user)


# ── External delivery ────────────────────────────────────────────────────────


def _drop_reason_in(conn: db.Conn, row: dict) -> str | None:
    if row["channel"] not in _CHANNELS:
        return "channel not registered"
    if row["suppressed_at"] is not None:
        return "notification hidden"
    user = user_in(conn, row["user_id"])
    if user is None or not user.is_active:
        return "recipient inactive"
    if not can_read_in(conn, user, row["entity_type"], row["entity_id"]):
        _suppress_in(conn, [row["notification_id"]])
        return "recipient can no longer read the record"
    return None


def _finish(delivery_id: int, status: str, error: str | None = None) -> None:
    with db.transaction() as conn:
        conn.execute(
            """UPDATE core_notification_deliveries
                  SET status = ?, attempts = attempts + 1, last_error = ?, sent_at = CASE WHEN ? = 'sent' THEN ? END
                WHERE id = ? AND status = 'queued'""",
            (status, error, status, clock.now_iso(), delivery_id),
        )


def flush(cancel: threading.Event | None = None) -> dict:
    """Job core.notifications_flush: send queued deliveries. Never call it inside a transaction.

    One transaction re-checks each queued delivery and drops the ones whose recipient lost access;
    the sends then run outside it, each followed by its own small transaction recording the
    outcome. Returns counts by outcome."""
    counts = {"sent": 0, "retry": 0, "failed": 0, "dropped": 0}
    with db.transaction() as conn:
        rows = [dict(r) for r in conn.execute(
            """SELECT d.id, d.channel, d.attempts, n.id AS notification_id, n.user_id, n.title, n.message,
                      n.entity_type, n.entity_id, n.link, n.suppressed_at
                 FROM core_notification_deliveries d JOIN core_notifications n ON n.id = d.notification_id
                WHERE d.status = 'queued' ORDER BY d.id LIMIT ?""",
            (FLUSH_BATCH,),
        )]  # fmt: skip
        sendable = []
        for row in rows:
            if reason := _drop_reason_in(conn, row):
                conn.execute(
                    "UPDATE core_notification_deliveries SET status = 'dropped', last_error = ? WHERE id = ?", (reason, row["id"])
                )
                counts["dropped"] += 1
            else:
                sendable.append(row)
    # simplification: one batch per run and a retry on every run (30 s apart, MAX_ATTEMPTS in all);
    # upgrade path: an available_at column with doubling backoff, as core_outbox has.
    for row in sendable:
        if cancel is not None and cancel.is_set():
            break
        payload = {k: row[k] for k in ("notification_id", "user_id", "title", "message", "link", "entity_type", "entity_id")}
        try:
            _CHANNELS[row["channel"]].send(payload)
        except Undeliverable as e:
            _finish(row["id"], "dropped", str(e)[:2000])
            counts["dropped"] += 1
        except Exception as e:
            logger.warning("notification delivery %s (%s) failed: %r", row["id"], row["channel"], e)
            final = row["attempts"] + 1 >= MAX_ATTEMPTS
            _finish(row["id"], "failed" if final else "queued", repr(e)[:2000])
            counts["failed" if final else "retry"] += 1
        else:
            _finish(row["id"], "sent")
            counts["sent"] += 1
    return counts


# ── Hooks ────────────────────────────────────────────────────────────────────


def on_entity_deleted_in(conn: db.Conn, entity_type: str, entity_id: int) -> None:
    """Hide the record's notifications; flush drops their queued deliveries."""
    conn.execute(
        "UPDATE core_notifications SET suppressed_at = ? WHERE entity_type = ? AND entity_id = ? AND suppressed_at IS NULL",
        (clock.now_iso(), entity_type, entity_id),
    )


def on_entity_merged_in(conn: db.Conn, entity_type: str, target_id: int, source_id: int) -> None:
    """Point the source's notifications at the survivor, and their default link with them."""
    old, new = entities.url_for(entity_type, source_id), entities.url_for(entity_type, target_id)
    conn.execute(
        """UPDATE core_notifications SET entity_id = ?, link = CASE WHEN link = ? THEN ? ELSE link END
            WHERE entity_type = ? AND entity_id = ?""",
        (target_id, old, new, entity_type, source_id),
    )
