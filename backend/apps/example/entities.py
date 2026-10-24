from backend.apps.example.service import READABLE
from backend.core.entities import Entity, title_from


def can_read(user, conn, widget_id: int) -> bool:
    return conn.execute(f"SELECT 1 FROM example_widgets WHERE id = ? AND {READABLE}", (widget_id, user.id)).fetchone() is not None


def can_write(user, conn, widget_id: int) -> bool:
    if user.role == "admin":
        return True
    return conn.execute(
        "SELECT 1 FROM example_widgets WHERE id = ? AND owner_user_id = ?", (widget_id, user.id)
    ).fetchone() is not None


ENTITIES = [
    Entity(
        type="example.widget", table="example_widgets", label="Widget", label_plural="Widgets",
        url_fn=lambda widget_id: f"/example/{widget_id}", title_fn=title_from("example_widgets"),
        can_read=can_read, can_write=can_write, searchable=("name",),
    ),
]
