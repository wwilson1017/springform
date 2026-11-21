"""The tool contract every tool source (core, apps, remote MCP servers) speaks.

Two handler forms:
- `handler_in(conn, user, args)` for local writes: runs inside the approval transaction, after
  the engine has called `entities.authorize(user, conn, type, id, "write")` on every
  `targets(args)` record. It uses `_in` service functions and never opens `transaction()`.
- `handler(user, args)` for reads and external-effect tools: runs outside any transaction.

`confirm_tier="routine"` (writes only) lets a write skip the Approve card; `hides_when(args)`
puts the card back for a call that would take a record out of view; `always_confirm` forces a
card even for reads (every remote tool, except a trusted server's read). `tool_def_sha256` binds a pending approval to exactly
what was shown, where it runs, and the implementation revision.
`summary` is the optional user-facing line on the Approve card.
`reads(args, result)` names the records a result carries, as (entity_type, id) pairs; they are
stored on the run and rechecked for read access whenever the result is shown again
(authorization.md §5). `records_in` and `linked` build one from a per-dict matcher.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.core.auth.deps import User
    from backend.core.db import Conn

ROUTINE = "routine"

# The AI tool on the other end of an inbound MCP call (docs/agents/mcp.md §1), self-reported and so
# untrusted; None in chat and jobs. Core sets it around the call; a `handler_in` may read it.
calling_client: contextvars.ContextVar[str | None] = contextvars.ContextVar("tool_calling_client", default=None)
# Whether the chat conversation was tainted when this model call started; `turns` sets it per call,
# so a provider-side tool that no Approve card can gate (Anthropic's web search) stays out.
calling_tainted: contextvars.ContextVar[bool] = contextvars.ContextVar("calling_tainted", default=False)
# The chat conversation a tool runs for; None over MCP and in jobs. `execute.run_tool` sets it.
calling_conversation: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "tool_calling_conversation", default=None
)


def _always(user: User) -> bool:
    return True


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict
    writes: bool
    handler: Callable[[User, dict], Any] | None = None
    handler_in: Callable[[Conn, User, dict], Any] | None = None
    targets: Callable[[dict], list[tuple[str, int]]] | None = None
    confirm_tier: str | None = None
    always_confirm: bool = False
    hides_when: Callable[[dict], bool] | None = None
    enabled: Callable[[User], bool] = _always
    untrusted_source: bool = False
    external_effect: bool = False  # a write whose effect leaves the install (handler, not handler_in)
    mcp_exposed: bool = True  # False for protected tools (e.g. soul/MEMORY context-file writes)
    app: str = "core"
    revision: str = ""  # the app's (or core's) version; set by the registry
    server_id: str | None = None  # remote (outbound MCP) tools only
    server_url: str | None = None
    summary: str = ""  # user-facing line on the Approve card; empty shows only name and args
    title: str = ""  # MCP display title; empty derives one from the name. Not hashed (last: positional order)
    destructive: bool = False  # MCP destructiveHint: the write discards data for good. Not hashed
    # The records a result carries, for the replay recheck (history.recheck). Not hashed
    reads: Callable[[dict, Any], Iterable[tuple[str, int]]] | None = None
    # A bulk edit: its card lists old -> new as the server reads them, and the user can undo it
    # (agent.md §6, "Change lists and Undo"). Needs handler_in. Not hashed
    change_list: bool = False
    trusted: bool = False  # a tool of a trusted outbound MCP server (mcp.md §2). Not hashed

    @property
    def remote(self) -> bool:
        return self.server_url is not None

    def provider_def(self) -> dict:
        """What a model provider sees."""
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}


Record = tuple[str, int]


def records_in(value, match: Callable[[dict], list[Record]]) -> list[Record]:
    """Every record `match` names in any dict inside `value` (lists and dicts, walked whole)."""
    if isinstance(value, list):
        return [r for v in value for r in records_in(v, match)]
    if isinstance(value, dict):
        return [*match(value), *(r for v in value.values() for r in records_in(v, match))]
    return []


def linked(d: dict) -> list[Record]:
    """A dict about another record (a note, a reminder): its entity_type/entity_id pair when set."""
    return [(d["entity_type"], int(d["entity_id"]))] if d.get("entity_type") and d.get("entity_id") else []


def tool_def_sha256(spec: ToolSpec) -> str:
    material = {
        "name": spec.name,
        "description": spec.description,
        "input_schema": spec.input_schema,
        "writes": spec.writes,
        "confirm_tier": spec.confirm_tier,
        "always_confirm": spec.always_confirm,
        "revision": spec.revision,
        "server_id": spec.server_id,
        "server_url": spec.server_url,
    }
    if spec.summary:
        material["summary"] = spec.summary
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()
