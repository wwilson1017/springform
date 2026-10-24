from backend.core.agent.spec import ToolSpec


def get_tools() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="make_thing", description="Unprefixed.", input_schema={"type": "object", "properties": {}},
            writes=False, handler=lambda user, args: None,
        )
    ]
