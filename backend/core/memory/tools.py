"""Whisk's memory tools. Writes run through `handler_in` inside the approval transaction and
touch no entity records (`targets` is empty). The context-file write always confirms, is
admin-only, and is never exposed over MCP; `for_source("job")` drops both writes."""

from backend.core import db, memory
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
    f = context_files.write_in(
        conn,
        _AGENT,
        args["filename"],
        args["content"],
        user,
        allow_protected=True,
        keep_entries=not args.get("drop_entries"),
    )
    return {k: f[k] for k in ("filename", "is_protected", "updated_at", "size_chars", "removed")} | {
        "memory_size": memory.context_size(conn, _AGENT)
    }


def _no_targets(args: dict) -> list[tuple[str, int]]:
    return []


def get_tools() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="core_memory_search",
            description="Search the business memory: recorded facts and the assistant's context files.",
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
                "as a plain sentence. Never personal details about a person. A fact already held is not saved "
                "again (duplicate), and passwords, keys and card numbers are removed (removed): tell the person."
            ),
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}}},
                "required": ["text"],
            },
            writes=True,
            handler_in=_remember,
            targets=_no_targets,
            summary="Save this fact to the business memory.",
        ),
        ToolSpec(
            name="core_context_file_read",
            description="Read one of the assistant's context files (for example business.md).",
            input_schema={"type": "object", "properties": {"filename": {"type": "string"}}, "required": ["filename"]},
            writes=False,
            handler=_read_file,
        ),
        ToolSpec(
            name="core_context_file_write",
            description=(
                "Replace the whole content of one of the assistant's context files, including soul.md and MEMORY.md. "
                "A rewrite that drops over a quarter of the file's lines is refused unless drop_entries is true. "
                "Passwords, keys and card numbers are removed. The result's memory_size is how much of the "
                "per-turn memory budget the context files use."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "filename": {"type": "string"},
                    "content": {"type": "string"},
                    "drop_entries": {
                        "type": "boolean",
                        "description": "True only to remove entries on purpose.",
                    },
                },
                "required": ["filename", "content"],
            },
            writes=True,
            handler_in=_write_file,
            targets=_no_targets,
            always_confirm=True,
            mcp_exposed=False,
            enabled=lambda user: user.is_admin,
            summary="Replace this context file with the content below.",
        ),
    ]
