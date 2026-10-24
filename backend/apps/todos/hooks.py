"""Subscribers. Each runs inside the caller's transaction: cheap, and raising rolls it back."""

from backend.apps.todos import service


def merged(conn, entity_type: str, target_id: int, source_id: int) -> None:
    """Two records became one: todos linked to the loser now point at the survivor."""
    service.relink_in(conn, entity_type, source_id, target_id)


HOOKS = {
    # A deleted todo leaves a tombstone for the change feed; a deleted linked record leaves the todo, unlinked.
    "on_entity_deleted": [service.forget_in],
    "on_entity_merged": [merged],
}
