"""Whisk tools. The acting user is the chat's or the MCP link's user, so every tool sees and
changes exactly what that person could in the app. Writes are routine (no Approve card) unless
they would take a todo out of someone's view."""

from backend.apps.todos import service
from backend.apps.todos.models import ItemIn, ItemPatch
from backend.core.agent.spec import ROUTINE, ToolSpec

_LIST_FILTERS = {
    "status": {"type": "string", "enum": ["inbox", "next_action", "waiting_for", "delegated", "someday_maybe", "done", "dropped"]},
    "project_id": {"type": "integer"},
    "area_id": {"type": "integer"},
    "context": {"type": "string"},
    "tag": {"type": "string"},
    "person": {"type": "string"},
    "starred": {"type": "boolean"},
    "due_before": {"type": "string", "description": "YYYY-MM-DD"},
    "due_after": {"type": "string", "description": "YYYY-MM-DD"},
    "search": {"type": "string"},
    "mine": {"type": "boolean", "description": "Only the user's work: their private todos, team todos assigned to them, unassigned team todos"},
    "include_deferred": {"type": "boolean", "description": "Keep todos whose revisit date is still ahead"},
    "limit": {"type": "integer", "minimum": 1, "maximum": 500},
}  # fmt: skip
_ID = {"id": {"type": "integer", "description": "The todo's id"}}


def _schema(model, **extra) -> dict:
    schema = model.model_json_schema()
    return {"type": "object", "properties": {**extra, **schema["properties"]}, "required": [*extra, *schema.get("required", [])]}


def _list(user, args: dict) -> list[dict]:
    return service.list_items(user, **{k: v for k, v in args.items() if k in _LIST_FILTERS})


def _create(conn, user, args: dict) -> dict:
    fields = ItemIn(**args).model_dump()
    return service.create_item_in(conn, user, fields.pop("title"), **fields, source="agent")


def _update(conn, user, args: dict) -> dict:
    fields = ItemPatch(**{k: v for k, v in args.items() if k != "id"}).model_dump(exclude_unset=True)
    return service.update_item_in(conn, user, int(args["id"]), fields)


def _the_todo(args: dict) -> list[tuple[str, int]]:
    return [("todos.item", int(args["id"]))]


def get_tools() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="todos_list",
            description=(
                "List the todos the user can see: their private ones and the team's. Statuses: inbox (unprocessed), "
                "next_action, waiting_for, delegated, someday_maybe, done, dropped. Todos deferred to a later "
                "revisit date are left out unless include_deferred or search is given."
            ),
            input_schema={"type": "object", "properties": _LIST_FILTERS},
            writes=False,
            handler=_list,
        ),
        ToolSpec(
            name="todos_today",
            description="The user's Today: their open work that is starred, due today or overdue, or whose revisit date has come.",
            input_schema={"type": "object", "properties": {}},
            writes=False,
            handler=lambda user, args: service.today_view(user),
        ),
        ToolSpec(
            name="todos_review",
            description=(
                "The data for a weekly review of the user's work: inbox, completed last week, dated today or overdue, "
                "projects without a next action, waiting for, routines, upcoming, stale, areas. Walk it step by step."
            ),
            input_schema={"type": "object", "properties": {}},
            writes=False,
            handler=lambda user, args: service.review(user),
        ),
        ToolSpec(
            name="todos_create",
            description=(
                "Create a todo. It is private to the user unless visibility is 'team' (every member sees and can edit "
                "it). Unclear items go to the inbox. Write next actions as physical, visible verbs. Link it to a record "
                "with entity_type and entity_id (e.g. core.person and the person's id)."
            ),
            input_schema=_schema(ItemIn),
            writes=True,
            confirm_tier=ROUTINE,
            handler_in=_create,
            targets=lambda args: [],  # touches no existing record; the link is checked for read access
        ),
        ToolSpec(
            name="todos_update",
            description=(
                "Change a todo the user can see: only the fields given change, and null clears one. Making a team todo "
                "private, or giving it to someone else, takes it out of other people's view."
            ),
            input_schema=_schema(ItemPatch, **_ID),
            writes=True,
            confirm_tier=ROUTINE,
            hides_when=lambda args: args.get("visibility") == "private" or "owner_user_id" in args,
            handler_in=_update,
            targets=_the_todo,
        ),
        ToolSpec(
            name="todos_complete",
            description="Mark a todo done. A repeating todo comes back as its next occurrence.",
            input_schema={"type": "object", "properties": _ID, "required": ["id"]},
            writes=True,
            confirm_tier=ROUTINE,
            handler_in=lambda conn, user, args: service.complete_in(conn, user, int(args["id"])),
            targets=_the_todo,
        ),
    ]
