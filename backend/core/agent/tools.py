"""Whisk's own read tools (agent.md §4, "Core tools"). Chat only: never offered over MCP."""

from backend.core.agent import result_cap
from backend.core.agent.spec import ToolSpec


def get_tools() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="core_read_result",
            description=(
                "Read more of a tool result that was capped. Pass the handle from the cap notice with `offset` "
                f"(characters from the start; up to {result_cap.READ_CHARS:,} come back) or `grep` (text to find; "
                "each match comes back with its offset and the text around it). Works in the conversation the "
                f"result belongs to, for {result_cap.READABLE_HOURS} hours."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "handle": {"type": "string", "description": 'The handle from the cap notice, like "r412".'},
                    "offset": {"type": "integer", "minimum": 0},
                    "grep": {"type": "string"},
                },
                "required": ["handle"],
            },
            writes=False,
            mcp_exposed=False,
            handler=lambda user, args: result_cap.read(
                user, str(args.get("handle") or ""), offset=args.get("offset"), grep=args.get("grep")
            ),
        ),
    ]
