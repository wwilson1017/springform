"""Subscribers, called as fn(conn, entity_type, entity_id, **kw) inside the caller's transaction,
so each stays cheap and raising rolls the caller's whole write back."""

from backend.core import settings


def repoint_person(conn, entity_type: str, entity_id: int, *, source_id: int, **kw) -> None:
    """A merged person's widgets move to the survivor (entity_id)."""
    if entity_type == "core.person":
        conn.execute("UPDATE example_widgets SET person_id = ? WHERE person_id = ?", (entity_id, source_id))


def detach_person(conn, entity_type: str, entity_id: int, **kw) -> None:
    if entity_type == "core.person":
        conn.execute("UPDATE example_widgets SET person_id = NULL WHERE person_id = ?", (entity_id,))


def remember_last_change(conn, entity_type: str, entity_id: int, *, user_id: int | None, **kw) -> None:
    if entity_type == "example.widget":
        settings.set_setting_in(conn, "example.last_changed_widget", entity_id, user_id)


HOOKS = {
    "on_entity_merged": [repoint_person],
    "on_entity_deleted": [detach_person],
    "on_record_changed": [remember_last_change],
}
