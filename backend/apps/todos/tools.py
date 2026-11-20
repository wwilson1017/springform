"""Whisk tools. The acting user is the chat's or the MCP link's user, so every tool sees and
changes exactly what that person could in the app. Writes are routine (no Approve card) unless
they would take a todo out of someone's view."""

from pydantic import ValidationError

from backend.apps.todos import service
from backend.apps.todos.common import MAX_BULK
from backend.apps.todos.models import AreaIn, AreaPatch, ItemIn, ItemPatch, ProjectIn, ProjectPatch
from backend.core.agent.spec import ROUTINE, ToolSpec, calling_client
from backend.core.errors import AppError, Invalid

MAX_BULK_CREATE = 100

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
}  # fmt: skip
_PAGING = {
    # 80 compact rows is about 12 KB: under what some clients cut a reply at.
    "limit": {"type": "integer", "minimum": 1, "maximum": 500, "description": "Rows per call (default 80)"},
    "offset": {"type": "integer", "minimum": 0, "description": "How many to skip: send next_offset from the last call"},
    "full": {"type": "boolean", "description": "Every field of each todo; the default compact rows are several times smaller"},
}  # fmt: skip
_ID = {"id": {"type": "integer", "description": "The todo's id"}}
# What a compact row keeps when set (the donor's, plus the team fields): what an AI sorts and reviews by.
_COMPACT = ("context", "project_id", "project_name", "area_name", "due_date", "revisit_on", "star", "people", "tags",
            "repeat", "assignee_name")  # fmt: skip


def _schema(model, **extra) -> dict:
    schema = model.model_json_schema()
    return {
        "type": "object",
        "properties": {**extra, **schema["properties"]},
        "required": [*extra, *schema.get("required", [])],
    }


def _compact(todo: dict) -> dict:
    row = {k: todo[k] for k in ("id", "title", "status", "visibility")}
    for key in _COMPACT:
        if todo.get(key):
            row[key.removesuffix("_name")] = todo[key]
    if todo.get("notes"):
        row["has_notes"] = True
    return row


def _list(user, args: dict) -> dict:
    """A page of todos with `total` and `next_offset` (null on the last page)."""
    filters = {k: v for k, v in args.items() if k in _LIST_FILTERS}
    limit, offset = service.page_size(args.get("limit", 80)), max(0, int(args.get("offset") or 0))
    rows = service.list_items(user, limit=limit, offset=offset, **filters)
    total = service.count_items(user, **filters)
    return {
        "todos": rows if args.get("full") else [_compact(t) for t in rows],
        "count": len(rows),
        "total": total,
        "next_offset": offset + len(rows) if offset + len(rows) < total else None,
    }


def _create(conn, user, args: dict) -> dict:
    fields = ItemIn(**args).model_dump()
    title = fields.pop("title")
    return service.create_item_in(conn, user, title, **fields, source="agent", source_client=calling_client.get())


def _why(e: Exception) -> str:
    if isinstance(e, ValidationError):
        first = e.errors()[0]
        return f"{'.'.join(str(p) for p in first['loc']) or 'item'}: {first['msg']}"
    return e.detail if isinstance(e, AppError) else str(e)


def _bulk_create(conn, user, args: dict) -> dict:
    """All or nothing: the first bad item raises, and the run's transaction rolls every one back."""
    todos = args.get("todos")
    if not isinstance(todos, list) or not 1 <= len(todos) <= MAX_BULK_CREATE:
        raise Invalid(f"todos must be a list of 1 to {MAX_BULK_CREATE} todos")
    ids = []
    for i, item in enumerate(todos):
        try:
            if not isinstance(item, dict):
                raise Invalid("each todo is an object")
            ids.append(_create(conn, user, item)["id"])
        except (AppError, ValidationError, TypeError) as e:
            raise Invalid(f"todos[{i}]: {_why(e)[:300]} (nothing in this batch was created)") from None
    return {"created": len(ids), "ids": ids}


def _bulk_ids(args: dict) -> list[int]:
    ids = args.get("ids")
    if not isinstance(ids, list) or not 1 <= len(ids) <= MAX_BULK:
        raise Invalid(f"ids must be a list of 1 to {MAX_BULK} todo ids")
    return [int(i) for i in ids]


def _bulk_update(conn, user, args: dict) -> dict:
    fields = ItemPatch(**(args.get("fields") or {})).model_dump(exclude_unset=True)
    return service.bulk_update_in(conn, user, _bulk_ids(args), fields)


def _hides(fields: dict) -> bool:
    """Making a row private, or giving it to someone else, takes it out of other people's view."""
    return fields.get("visibility") == "private" or "owner_user_id" in fields


def _container_tools(kind: str, noun: str, plural: str, model_in, model_patch, filters: dict, describe: str):
    """List, create and update for projects or areas. Neither is a registered entity, so the writes
    have no `targets`: the service's `_container_in` refuses a row the user cannot read, as the REST
    routes rely on. A create is always the caller's own row."""
    create_in = service.create_project_in if kind == "project" else service.create_area_in
    listing = service.list_projects if kind == "project" else service.list_areas

    def create(conn, user, args):
        fields = model_in(**args).model_dump()
        return create_in(conn, user, fields.pop("name"), **fields)

    def update(conn, user, args):
        fields = model_patch(**{k: v for k, v in args.items() if k != "id"}).model_dump(exclude_unset=True)
        return service.update_container_in(conn, user, kind, int(args["id"]), fields)

    the_id = {"id": {"type": "integer", "description": f"The {noun}'s id"}}
    return [
        ToolSpec(
            name=f"todos_list_{plural}",
            title=f"List {plural if kind == 'project' else 'areas of focus'}",
            description=f"List the {plural} the user can see: their private ones and the team's. {describe}",
            input_schema={"type": "object", "properties": filters},
            writes=False,
            handler=lambda user, args: listing(user, **{k: v for k, v in args.items() if k in filters}),
        ),
        ToolSpec(
            name=f"todos_create_{kind}",
            title=f"Add {'a project' if kind == 'project' else 'an area of focus'}",
            description=f"Create a {noun}, private to the user unless visibility is 'team'. Names are unique. {describe}",
            input_schema=_schema(model_in),
            writes=True,
            confirm_tier=ROUTINE,
            handler_in=create,
            targets=lambda args: [],
            summary=f"Create this {noun}.",
        ),
        ToolSpec(
            name=f"todos_update_{kind}",
            title=f"Update {'a project' if kind == 'project' else 'an area of focus'}",
            description=(
                f"Change a {noun} the user can see: only the fields given change. Status 'dropped' archives it; what "
                "sits in it stays. Making a team one private, or giving it to someone else, takes it out of other "
                "people's view."
            ),
            input_schema=_schema(model_patch, **the_id),
            writes=True,
            confirm_tier=ROUTINE,
            hides_when=_hides,
            handler_in=update,
            targets=lambda args: [],
            summary=f"Update this {noun} with the changes below.",
        ),
    ]


def _update(conn, user, args: dict) -> dict:
    fields = ItemPatch(**{k: v for k, v in args.items() if k != "id"}).model_dump(exclude_unset=True)
    return service.update_item_in(conn, user, int(args["id"]), fields)


def _the_todo(args: dict) -> list[tuple[str, int]]:
    return [("todos.item", int(args["id"]))]


def get_tools() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="todos_list",
            title="List todos",
            description=(
                "List the todos the user can see: their private ones and the team's. Statuses: inbox (unprocessed), "
                "next_action, waiting_for, delegated, someday_maybe, done, dropped. Todos deferred to a later "
                "revisit date are left out unless include_deferred or search is given. Rows are compact (id, title, "
                "status, visibility and only the fields that are set; has_notes when there are notes): todos_get "
                "returns one in full. `total` is how many match; while `next_offset` is not null, call again with it."
            ),
            input_schema={"type": "object", "properties": {**_LIST_FILTERS, **_PAGING}},
            writes=False,
            handler=_list,
        ),
        ToolSpec(
            name="todos_get",
            title="Get one todo",
            description="One todo the user can see, with every field.",
            input_schema={"type": "object", "properties": _ID, "required": ["id"]},
            writes=False,
            handler=lambda user, args: service.get_item(user, int(args["id"])),
        ),
        ToolSpec(
            name="todos_today",
            title="Today's todos",
            description="The user's Today: their open work that is starred, due today or overdue, or whose revisit date has come.",
            input_schema={"type": "object", "properties": {}},
            writes=False,
            handler=lambda user, args: service.today_view(user),
        ),
        ToolSpec(
            name="todos_review",
            title="Weekly review",
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
            title="Add a todo",
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
            summary="Create this todo.",
        ),
        ToolSpec(
            name="todos_update",
            title="Update a todo",
            description=(
                "Change a todo the user can see: only the fields given change, and null clears one. Making a team todo "
                "private, or giving it to someone else, takes it out of other people's view."
            ),
            input_schema=_schema(ItemPatch, **_ID),
            writes=True,
            confirm_tier=ROUTINE,
            hides_when=_hides,
            handler_in=_update,
            targets=_the_todo,
            summary="Update this todo with the changes below.",
        ),
        ToolSpec(
            name="todos_complete",
            title="Complete a todo",
            description="Mark a todo done. A repeating todo comes back as its next occurrence.",
            input_schema={"type": "object", "properties": _ID, "required": ["id"]},
            writes=True,
            confirm_tier=ROUTINE,
            handler_in=lambda conn, user, args: service.complete_in(conn, user, int(args["id"])),
            targets=_the_todo,
            summary="Complete this todo and schedule its next occurrence if repeating.",
        ),
        ToolSpec(
            name="todos_bulk_create",
            title="Add several todos",
            description=(
                f"Create up to {MAX_BULK_CREATE} todos at once, for a long mind dump or an import. Each item has "
                "todos_create's fields. All or nothing: a bad item creates none, and the error names it (todos[3]). "
                "Returns the count and the new ids in the order sent."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "todos": {"type": "array", "items": _schema(ItemIn), "minItems": 1, "maxItems": MAX_BULK_CREATE}
                },
                "required": ["todos"],
            },  # fmt: skip
            writes=True,
            confirm_tier=ROUTINE,
            handler_in=_bulk_create,
            targets=lambda args: [],
            summary="Create these todos.",
        ),
        ToolSpec(
            name="todos_bulk_update",
            title="Update several todos",
            description=(
                "Apply the same changes to many todos at once: move inbox items to next_action, put a batch in a "
                "project, complete a list. `fields` takes todos_update's fields. Every id must be a todo the user can "
                "see, or nothing changes."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "ids": {"type": "array", "items": {"type": "integer"}, "minItems": 1, "maxItems": MAX_BULK},
                    "fields": _schema(ItemPatch),
                },
                "required": ["ids", "fields"],
            },
            writes=True,
            confirm_tier=ROUTINE,
            hides_when=lambda args: _hides(args.get("fields") or {}),
            handler_in=_bulk_update,
            targets=lambda args: [("todos.item", i) for i in _bulk_ids(args)],
            summary="Apply the changes below to every listed todo.",
        ),
        *_container_tools(
            "project",
            "project",
            "projects",
            ProjectIn,
            ProjectPatch,
            {
                "status": {"type": "string", "enum": ["active", "someday", "completed", "dropped"]},
                "area_id": {"type": "integer"},
            },
            "A project is an outcome that needs more than one action; give it a purpose and an outcome. Each comes "
            "with open_count, the open todos in it the user can see.",
        ),  # fmt: skip
        *_container_tools(
            "area",
            "area of focus",
            "areas",
            AreaIn,
            AreaPatch,
            {"status": {"type": "string", "enum": ["active", "dropped"]}},
            "An area of focus is a standing part of a job or a life that projects and todos hang off; it is never "
            "finished.",
        ),  # fmt: skip
        ToolSpec(
            name="todos_changes",
            title="Changes since the last sync",
            description=(
                "What changed for the user after `since_rev`, oldest first, to keep another list in step: the todos, "
                "projects and areas added or edited, whole, and in `removed` the ids of rows that left their view. "
                "Store `next_since_rev` and send it next time; while `more` is true, call again at once. `reset` true "
                "means replace your copy with what this returns. 0 returns everything."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "since_rev": {"type": "integer", "minimum": 0},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 500},
                },
            },
            writes=False,
            handler=lambda user, args: service.changes(
                user, int(args.get("since_rev") or 0), int(args.get("limit") or 500)
            ),
        ),
    ]
