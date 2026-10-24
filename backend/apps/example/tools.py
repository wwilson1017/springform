from backend.apps.example import service
from backend.apps.example.models import WidgetIn
from backend.core.agent.spec import ToolSpec


def _create(conn, user, args: dict) -> dict:
    return service.create_widget_in(conn, user, WidgetIn(**args))


def _targets(args: dict) -> list[tuple[str, int]]:
    return [("core.person", int(args["person_id"]))] if args.get("person_id") else []


def get_tools() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="example_list_widgets",
            description="List the widgets the user can see.",
            input_schema={"type": "object", "properties": {}},
            writes=False,
            handler=lambda user, args: service.list_widgets(user),
        ),
        ToolSpec(
            name="example_create_widget",
            description="Create a widget, optionally linked to a person.",
            input_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "color": {"type": "string"},
                    "is_private": {"type": "boolean"},
                    "person_id": {"type": "integer"},
                },
                "required": ["name"],
            },
            writes=True,
            handler_in=_create,
            targets=_targets,
        ),
    ]
