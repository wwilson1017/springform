"""Widgets. A widget is readable by its owner, or by anyone when it is not private; writable by
its owner or an admin. Every function has an `_in(conn, …)` form for callers in a transaction."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.apps.example.models import WidgetIn, WidgetPatch
from backend.core import clock, db, entities, settings
from backend.core.errors import Invalid, NotFound
from backend.core.timeline import api as timeline

if TYPE_CHECKING:
    from backend.core.auth.deps import User

ENTITY = "example.widget"
COLUMNS = "id, name, color, owner_user_id, person_id, is_private, created_at, updated_at"
READABLE = "(is_private = 0 OR owner_user_id = ?)"  # the SQL twin of entities.can_read; bind user.id


def _widget(row) -> dict:
    widget = dict(row)
    widget["is_private"] = bool(widget["is_private"])
    return widget


def _row_in(conn: db.Conn, widget_id: int) -> dict:
    return dict(conn.execute(f"SELECT {COLUMNS} FROM example_widgets WHERE id = ?", (widget_id,)).fetchone())


def _check_person_in(conn: db.Conn, user: User, person_id: int | None) -> None:
    if person_id is None:
        return
    try:
        entities.authorize(user, conn, "core.person", person_id, "read")
    except NotFound:
        raise Invalid("person_id: no such person") from None


def list_widgets(user: User) -> list[dict]:
    rows = db.get_conn().execute(f"SELECT {COLUMNS} FROM example_widgets WHERE {READABLE} ORDER BY id", (user.id,))
    return [_widget(r) for r in rows]


def get_widget_in(conn: db.Conn, user: User, widget_id: int) -> dict:
    entities.authorize(user, conn, ENTITY, widget_id, "read")
    return _widget(_row_in(conn, widget_id))


def get_widget(user: User, widget_id: int) -> dict:
    return get_widget_in(db.get_conn(), user, widget_id)


def create_widget_in(conn: db.Conn, user: User, data: WidgetIn) -> dict:
    _check_person_in(conn, user, data.person_id)
    color = data.color if data.color is not None else settings.get_setting("example.default_color")
    now = clock.now_iso()
    cur = conn.execute(
        """INSERT INTO example_widgets (name, color, owner_user_id, person_id, is_private, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (data.name, color, user.id, data.person_id, int(data.is_private), now, now),
    )
    return _widget(_row_in(conn, cur.lastrowid))


def create_widget(user: User, data: WidgetIn) -> dict:
    with db.transaction() as conn:
        return create_widget_in(conn, user, data)


def update_widget_in(conn: db.Conn, user: User, widget_id: int, patch: WidgetPatch) -> dict:
    entities.authorize(user, conn, ENTITY, widget_id, "write")
    fields = patch.model_dump(exclude_unset=True)
    for required in ("name", "is_private"):
        if required in fields and fields[required] is None:
            raise Invalid(f"{required} cannot be null")
    if "person_id" in fields:
        _check_person_in(conn, user, fields["person_id"])
    if "is_private" in fields:
        fields["is_private"] = int(fields["is_private"])
    before = _row_in(conn, widget_id)
    if fields:
        sets = ", ".join(f"{k} = ?" for k in fields)  # keys are WidgetPatch's own fields
        conn.execute(
            f"UPDATE example_widgets SET {sets}, updated_at = ? WHERE id = ?",
            (*fields.values(), clock.now_iso(), widget_id),
        )
    after = _row_in(conn, widget_id)
    timeline.record_changes_in(conn, ENTITY, widget_id, before, after, user.id)
    return _widget(after)


def update_widget(user: User, widget_id: int, patch: WidgetPatch) -> dict:
    with db.transaction() as conn:
        return update_widget_in(conn, user, widget_id, patch)


def widgets_for_person_in(conn: db.Conn, user: User, person_id: int) -> list[dict]:
    entities.authorize(user, conn, "core.person", person_id, "read")
    rows = conn.execute(
        f"SELECT {COLUMNS} FROM example_widgets WHERE person_id = ? AND {READABLE} ORDER BY id", (person_id, user.id)
    )
    return [_widget(r) for r in rows]


def widgets_for_person(user: User, person_id: int) -> list[dict]:
    return widgets_for_person_in(db.get_conn(), user, person_id)


def badge(user: User) -> dict:
    n = db.one("SELECT count(*) AS n FROM example_widgets WHERE owner_user_id = ?", (user.id,))["n"]
    return {"count": n, "label": "Your widgets"}
