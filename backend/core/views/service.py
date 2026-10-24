"""Saved views: a named set of filters, sort and columns for one screen ("surface").

Lifted from CakeCRM backend/saved_views/. A view stores a query, never rows, so there is no
record authorization beyond ownership:
- a view is private to its owner until shared; a user lists their own views plus shared ones;
- only the owner or an admin may edit, share or delete one. Someone else's private view is
  404 (it is invisible), a shared view they may not edit is 403;
- `version` starts at 1 and every edit bumps it. An edit must name the version it was based on,
  so a stale edit is refused (409 `stale_view`) instead of overwriting a newer one. Sharing is
  not an edit and does not bump it.
`payload` is opaque here (the client keeps its own schema version inside it); only its type and
size are checked.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from backend.core import clock, db, entities
from backend.core.errors import Conflict, Forbidden, Invalid, NotFound

if TYPE_CHECKING:
    from backend.core.auth.deps import User

MAX_NAME = 80
MAX_PAYLOAD_BYTES = 65536
# A ceiling, not a quota: without one a scripted client could grow the table without bound.
MAX_VIEWS_PER_SURFACE = 100
_SURFACE = re.compile(r"^[a-z][a-z0-9_.]{0,63}$")
_SELECT = """SELECT v.id, v.surface, v.entity_type, v.name, v.version, v.payload, v.owner_user_id,
                    u.name AS owner_name, v.is_shared, v.created_at, v.updated_at
               FROM core_saved_views v JOIN core_users u ON u.id = v.owner_user_id"""


def _may_edit(owner_id: int, user: User) -> bool:
    return user.is_admin or owner_id == user.id


def _view(row, user: User) -> dict:
    return {
        "id": row["id"], "surface": row["surface"], "entity_type": row["entity_type"], "name": row["name"],
        "version": row["version"], "payload": json.loads(row["payload"]),
        "owner": {"id": row["owner_user_id"], "name": row["owner_name"]}, "is_shared": bool(row["is_shared"]),
        "can_edit": _may_edit(row["owner_user_id"], user), "created_at": row["created_at"], "updated_at": row["updated_at"],
    }  # fmt: skip


def _row_in(conn: db.Conn, user: User, view_id: int, *, edit: bool = False):
    row = conn.execute(f"{_SELECT} WHERE v.id = ?", (view_id,)).fetchone()
    if row is None or not (row["is_shared"] or _may_edit(row["owner_user_id"], user)):
        raise NotFound()
    if edit and not _may_edit(row["owner_user_id"], user):
        raise Forbidden()
    return row


def _surface(value: Any) -> str:
    if not isinstance(value, str) or not _SURFACE.match(value):
        raise Invalid("surface: lowercase '<app>.<screen>', at most 64 characters")
    return value


def _name(value: Any) -> str:
    name = (value or "").strip()
    if not name or len(name) > MAX_NAME:
        raise Invalid(f"name: 1 to {MAX_NAME} characters")
    return name


def _payload(value: Any) -> str:
    if not isinstance(value, dict):
        raise Invalid("payload: must be an object")
    encoded = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    if len(encoded.encode()) > MAX_PAYLOAD_BYTES:
        raise Invalid(f"payload: at most {MAX_PAYLOAD_BYTES} bytes")
    return encoded


def _entity_type(value: Any) -> str | None:
    if value is not None:
        try:
            entities.get(value)
        except NotFound:
            raise Invalid("entity_type: not a registered entity type") from None
    return value


def _write_in(conn: db.Conn, sql: str, params: tuple) -> int:
    try:
        return conn.execute(sql, params).lastrowid
    except db.sqlite3.IntegrityError:  # core_saved_views_name: one name per owner and surface
        raise Conflict("duplicate_name") from None


def list_views_in(conn: db.Conn, user: User, surface: str) -> list[dict]:
    """The user's own views on a surface plus every shared one, by name."""
    rows = conn.execute(
        f"{_SELECT} WHERE v.surface = ? AND (v.owner_user_id = ? OR v.is_shared = 1) ORDER BY v.name COLLATE NOCASE, v.id",
        (_surface(surface), user.id),
    )
    return [_view(r, user) for r in rows]


def list_views(user: User, surface: str) -> list[dict]:
    return list_views_in(db.get_conn(), user, surface)


def create_view_in(conn: db.Conn, user: User, surface: str, name: str, payload: dict, entity_type: str | None = None) -> dict:
    """A new private view owned by `user`, at version 1."""
    surface, name, encoded, entity_type = _surface(surface), _name(name), _payload(payload), _entity_type(entity_type)
    count = conn.execute(
        "SELECT count(*) FROM core_saved_views WHERE owner_user_id = ? AND surface = ?", (user.id, surface)
    ).fetchone()[0]
    if count >= MAX_VIEWS_PER_SURFACE:
        raise Conflict("too_many_views")
    now = clock.now_iso()
    view_id = _write_in(
        conn,
        """INSERT INTO core_saved_views (surface, entity_type, name, payload, owner_user_id, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (surface, entity_type, name, encoded, user.id, now, now),
    )
    return _view(_row_in(conn, user, view_id), user)


def create_view(user: User, surface: str, name: str, payload: dict, entity_type: str | None = None) -> dict:
    with db.transaction() as conn:
        return create_view_in(conn, user, surface, name, payload, entity_type)


def update_view_in(conn: db.Conn, user: User, view_id: int, version: int, changes: dict) -> dict:
    """Change any of name, payload, entity_type. `version` must be the view's current version
    (else 409 stale_view); the edit bumps it. Owner or admin."""
    row = _row_in(conn, user, view_id, edit=True)
    if version != row["version"]:
        raise Conflict("stale_view")
    sets: dict[str, Any] = {}
    if "name" in changes:
        sets["name"] = _name(changes["name"])
    if "payload" in changes:
        sets["payload"] = _payload(changes["payload"])
    if "entity_type" in changes:
        sets["entity_type"] = _entity_type(changes["entity_type"])
    assignments = "".join(f"{k} = ?, " for k in sets)  # keys are this function's own
    _write_in(
        conn,
        f"UPDATE core_saved_views SET {assignments}version = version + 1, updated_at = ? WHERE id = ?",
        (*sets.values(), clock.now_iso(), view_id),
    )
    return _view(_row_in(conn, user, view_id), user)


def update_view(user: User, view_id: int, version: int, changes: dict) -> dict:
    with db.transaction() as conn:
        return update_view_in(conn, user, view_id, version, changes)


def share_view_in(conn: db.Conn, user: User, view_id: int, is_shared: bool | None = None) -> dict:
    """Share or unshare a view (flips it when `is_shared` is None). Owner or admin."""
    row = _row_in(conn, user, view_id, edit=True)
    shared = not row["is_shared"] if is_shared is None else is_shared
    conn.execute(
        "UPDATE core_saved_views SET is_shared = ?, updated_at = ? WHERE id = ?", (int(shared), clock.now_iso(), view_id)
    )
    return _view(_row_in(conn, user, view_id), user)


def share_view(user: User, view_id: int, is_shared: bool | None = None) -> dict:
    with db.transaction() as conn:
        return share_view_in(conn, user, view_id, is_shared)


def delete_view_in(conn: db.Conn, user: User, view_id: int) -> None:
    _row_in(conn, user, view_id, edit=True)
    conn.execute("DELETE FROM core_saved_views WHERE id = ?", (view_id,))


def delete_view(user: User, view_id: int) -> None:
    with db.transaction() as conn:
        delete_view_in(conn, user, view_id)
