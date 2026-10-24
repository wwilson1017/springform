from backend.core.agent.spec import ToolSpec


def get_tools() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="adminonly_peek", description="Peek.", input_schema={"type": "object", "properties": {}},
            writes=False, handler=lambda user, args: {"ok": True},
        )
    ]
