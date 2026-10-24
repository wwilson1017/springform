"""Whisk's reminder tools: set a reminder on a record for the acting user (its owner), and list
theirs. A date-time without an offset is read in the install timezone, the one Whisk is told
today's date in. The write is routine (no Approve card) and runs through `handler_in`."""

from backend.core import clock, db, entities, localtime, settings
from backend.core.agent.spec import ROUTINE, ToolSpec
from backend.core.errors import Invalid
from backend.core.reminders import api as reminders
from backend.core.timeline.tools import RECORD, human, record

_WAITING = {"open": ("open", "snoozed"), "done": ("done",)}


def _shape(r: dict) -> dict:
    keep = ("id", "title", "note", "due_at", "status", "entity_type", "entity_id", "entity_title")
    due_local = clock.parse(r["due_at"]).astimezone(localtime.tz()).isoformat()
    return {**{k: r[k] for k in keep}, "due_local": due_local, "url": settings.public_url() + (r["link"] or reminders.LINK)}


def _set(conn, user, args: dict) -> dict:
    [(entity_type, entity_id)] = record(args)
    try:
        due_at = clock.normalize(str(args.get("due_at") or ""), localtime.tz())
    except ValueError:
        raise Invalid("due_at must be an ISO date-time such as 2026-11-02T09:00") from None
    title = entities.titles_for(user, conn, entity_type, [entity_id]).get(entity_id) or f"{entities.get(entity_type).label} #{entity_id}"
    return _shape(reminders.create_in(
        conn, user, title=title[: reminders.TITLE_MAX], due_at=due_at, note=args.get("note") or "", entity_type=entity_type, entity_id=entity_id,
    ))  # fmt: skip


def _list(user, args: dict) -> list[dict]:
    statuses, limit = _WAITING.get(args.get("status") or "open"), int(args.get("limit") or 20)
    if statuses is None:
        raise Invalid("status must be open or done")
    rows = [r for s in statuses for r in reminders.list_mine_in(db.get_conn(), user, status=s, limit=limit)]
    return [_shape(r) for r in sorted(rows, key=lambda r: (r["due_at"], r["id"]))[:limit]]


def get_tools() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="core_set_reminder",
            description=(
                "Remind the user about a record (a person, an organization, a deal, a todo…) at due_at: they get a "
                "notification titled with the record's name, with the note. The result carries `url`."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    **RECORD,
                    "due_at": {"type": "string", "description": "When, ISO 8601 (2026-11-02T09:00); without an offset it is local time"},
                    "note": {"type": "string", "description": "What to do, e.g. 'Call about the spring order'"},
                },
                "required": ["entity_type", "entity_id", "due_at"],
            },
            writes=True,
            confirm_tier=ROUTINE,
            handler_in=_set,
            targets=lambda args: [],  # changes no record; create_in checks the record is readable
            enabled=human,
        ),
        ToolSpec(
            name="core_list_my_reminders",
            description=(
                "The user's reminders, soonest first: open (the default: waiting, snoozed included) or done. "
                "due_local is the due time in local time. Each carries a `url`."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["open", "done"]},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
            },
            writes=False,
            handler=_list,
            enabled=human,
        ),
    ]
