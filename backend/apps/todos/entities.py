from backend.core.entities import Entity, title_from


def can_read(user, conn, item_id: int) -> bool:
    """A team todo is every member's; a private one is its owner's alone (admins included).
    The registry adds the role check, which keeps out inactive users and lets the system
    principal read team todos only."""
    row = conn.execute("SELECT visibility, owner_user_id FROM todos_items WHERE id = ?", (item_id,)).fetchone()
    return row is not None and (row["visibility"] == "team" or row["owner_user_id"] == user.id)


ENTITIES = [
    Entity(
        type="todos.item", table="todos_items", label="Todo", label_plural="Todos",
        url_fn=lambda item_id: f"/todos/items/{item_id}", title_fn=title_from("todos_items", "title"),
        # Whoever may read a todo may write it; the registry's role check keeps the system principal read-only.
        can_read=can_read, can_write=can_read, searchable=("title", "notes"),
    ),
]
