"""Whisk's memory tools. Writes run through `handler_in` inside the approval transaction and
touch no entity records (`targets` is empty). The context-file write always confirms, is
admin-only, and is never exposed over MCP; `for_source("job")` drops both writes."""

from backend.core import db
from backend.core.agent.spec import ToolSpec
from backend.core.memory import context_files, facts

_AGENT = context_files.DEFAULT_AGENT  # simplification: handlers get no agent context, so tools act on Whisk's files


def _search(user, args: dict) -> dict:
    conn = db.get_conn()
    query = str(args.get("query", ""))
    return {
        "facts": [facts.public(f) for f in facts.search_in(conn, query, int(args.get("limit", 10)))],
        "context_files": context_files.search_in(conn, _AGENT, query, user),
    }


def _remember(conn, user, args: dict) -> dict:
    return facts.public(facts.remember_in(conn, args["text"], author_user_id=user.id, tags=args.get("tags", ())))


def _read_file(user, args: dict) -> dict:
    return context_files.read(_AGENT, args["filename"], user)


def _write_file(conn, user, args: dict) -> dict:
    f = context_files.write_in(conn, _AGENT, args["filename"], args["content"], user, allow_protected=True)
    return {k: f[k] for k in ("filename", "is_protected", "updated_at", "size_chars")}


def _no_targets(args: dict) -> list[tuple[str, int]]:
    return []


def get_tools() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="core_memory_search",
            description="Search the business memory: recorded facts and Whisk's context files.",
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 50}},
                "required": ["query"],
            },
            writes=False,
            handler=_search,
        ),
        ToolSpec(
            name="core_memory_remember",
            description=(
                "Record one durable fact about the business (a product, price, supplier, policy, decision) "
                "as a plain sentence. Never personal details about a person."
            ),
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}}},
                "required": ["text"],
            },
            writes=True,
            handler_in=_remember,
            targets=_no_targets,
        ),
        ToolSpec(
            name="core_context_file_read",
            description="Read one of Whisk's context files (for example business.md).",
            input_schema={"type": "object", "properties": {"filename": {"type": "string"}}, "required": ["filename"]},
            writes=False,
            handler=_read_file,
        ),
        ToolSpec(
            name="core_context_file_write",
            description="Replace the whole content of one of Whisk's context files, including soul.md and MEMORY.md.",
            input_schema={
                "type": "object",
                "properties": {"filename": {"type": "string"}, "content": {"type": "string"}},
                "required": ["filename", "content"],
            },
            writes=True,
            handler_in=_write_file,
            targets=_no_targets,
            always_confirm=True,
            mcp_exposed=False,
            enabled=lambda user: user.is_admin,
        ),
    ]
