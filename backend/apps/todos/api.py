"""Published functions: the only module other apps may import. Each has an `_in(conn, …)` form for
callers already in a transaction. Results are Item dicts (models.Item)."""

from __future__ import annotations

from backend.apps.todos import service
from backend.core import db
from backend.core.auth.deps import User
from backend.core.errors import NotFound


def _actor_in(conn: db.Conn, user_id: int) -> User:
    """The acting user: any active account, the system principal (id 0, a job) included."""
    row = conn.execute(
        "SELECT id, email, name, role, tz, is_active, token_epoch FROM core_users WHERE id = ? AND is_active = 1", (user_id,)
    ).fetchone()
    if row is None:
        raise NotFound("no such active user")
    return User.from_row(dict(row))


def create_in(
    conn: db.Conn,
    acting_user_id: int,
    title: str,
    *,
    owner_user_id: int | None = None,
    visibility: str = "private",
    entity_type: str | None = None,
    entity_id: int | None = None,
    due_date: str | None = None,
    notes: str = "",
    source: str = "app",
) -> dict:
    """A new inbox todo. Making one for another owner needs visibility="team", or an admin acting.
    A linked record must be readable by the acting user. The system principal may make team todos only."""
    return service.create_item_in(
        conn, _actor_in(conn, acting_user_id), title, owner_user_id=owner_user_id, visibility=visibility,
        entity_type=entity_type, entity_id=entity_id, due_date=due_date, notes=notes, source=source,
    )  # fmt: skip


def create(
    acting_user_id: int,
    title: str,
    *,
    owner_user_id: int | None = None,
    visibility: str = "private",
    entity_type: str | None = None,
    entity_id: int | None = None,
    due_date: str | None = None,
    notes: str = "",
    source: str = "app",
) -> dict:
    with db.transaction() as conn:
        return create_in(
            conn, acting_user_id, title, owner_user_id=owner_user_id, visibility=visibility, entity_type=entity_type,
            entity_id=entity_id, due_date=due_date, notes=notes, source=source,
        )  # fmt: skip


def list_for_record_in(conn: db.Conn, user: User, entity_type: str, entity_id: int, include_done: bool = False) -> list[dict]:
    """Team todos and the user's private ones linked to a record. NotFound when the user may not read the record."""
    return service.list_for_record_in(conn, user, entity_type, entity_id, include_done)


def list_for_record(user: User, entity_type: str, entity_id: int, include_done: bool = False) -> list[dict]:
    return list_for_record_in(db.get_conn(), user, entity_type, entity_id, include_done)


def complete_in(conn: db.Conn, acting_user_id: int, todo_id: int) -> dict:
    """Mark a todo done (a repeating one spawns its next occurrence). NotFound when the acting
    user cannot see it."""
    return service.complete_in(conn, _actor_in(conn, acting_user_id), todo_id)


def complete(acting_user_id: int, todo_id: int) -> dict:
    with db.transaction() as conn:
        return complete_in(conn, acting_user_id, todo_id)
