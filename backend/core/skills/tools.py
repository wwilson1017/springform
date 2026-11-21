"""`core_skill_load`: the full text of one active skill (the index in the prompt lists them)."""

from backend.core import skills
from backend.core.agent.spec import ToolSpec
from backend.core.timeline.tools import human


def _load(user, args: dict) -> dict:
    return skills.load(str(args.get("name") or ""))


def get_tools() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="core_skill_load",
            description=(
                "Load one of the skills listed under Skills in your instructions and get its full steps. "
                "Load a skill before a task it covers."
            ),
            input_schema={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
            writes=False,
            handler=_load,
            enabled=human,
            mcp_exposed=False,  # the index lives only in the chat prompt
            reads=lambda args, result: [],  # a skill is install-shared text, no record
        )
    ]
