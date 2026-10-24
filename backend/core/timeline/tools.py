"""Whisk's note tool: a note on any registered record's timeline, written as the acting user (the
chat's or the MCP link's), who needs write access to the record. The write confirms (an Approve
card) and runs through `handler_in` in the approval transaction. `human`, `url` and `record` are
shared with the contacts and reminders tools."""

from backend.core import entities, settings
from backend.core.agent.spec import ToolSpec
from backend.core.errors import Invalid
from backend.core.timeline import api as timeline

RECORD = {
    "entity_type": {
        "type": "string",
        "description": "The record's type, '<app>.<name>': core.person, core.organization, or an app's record type",
    },
    "entity_id": {"type": "integer", "description": "The record's id"},
}


def human(user) -> bool:
    """Any active admin or member: these tools are never the system principal's."""
    return user.is_active and user.role in ("admin", "member")


def url(entity_type: str, entity_id: int) -> str:
    return settings.public_url() + entities.url_for(entity_type, entity_id)


def record(args: dict) -> list[tuple[str, int]]:
    """[(entity_type, entity_id)]; an unknown type is refused with the registered ones listed."""
    entity_type, known = args.get("entity_type"), sorted(e.type for e in entities.all_entities())
    if entity_type not in known:
        raise Invalid(f"entity_type must be one of: {', '.join(known)}")
    return [(entity_type, int(args["entity_id"]))]


def _add_note(conn, user, args: dict) -> dict:
    [(entity_type, entity_id)] = record(args)
    entry = timeline.add_note_in(conn, user, entity_type, entity_id, args.get("body") or "")
    return {**entry, "entity_type": entity_type, "entity_id": entity_id, "url": url(entity_type, entity_id)}


def get_tools() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="core_add_note",
            description=(
                "Add a note to a record's timeline (a person, an organization, a deal, a todo…), written as the user. "
                "The result carries the record's `url`."
            ),
            input_schema={
                "type": "object",
                "properties": {**RECORD, "body": {"type": "string", "description": "The note, plain text or Markdown"}},
                "required": ["entity_type", "entity_id", "body"],
            },
            writes=True,
            handler_in=_add_note,
            targets=record,
            enabled=human,
        ),
    ]
