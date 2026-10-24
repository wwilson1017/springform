"""The tool contract every tool source (core, apps, remote MCP servers) speaks.

Two handler forms:
- `handler_in(conn, user, args)` for local writes: runs inside the approval transaction, after
  the engine has called `entities.authorize(user, conn, type, id, "write")` on every
  `targets(args)` record. It uses `_in` service functions and never opens `transaction()`.
- `handler(user, args)` for reads and external-effect tools: runs outside any transaction.

`confirm_tier="routine"` (writes only) lets a write skip the Approve card; `hides_when(args)`
puts the card back for a call that would take a record out of view; `always_confirm` forces a
card even for reads (every remote tool). `tool_def_sha256` binds a pending approval to exactly
what was shown, where it runs, and the implementation revision.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.core.auth.deps import User
    from backend.core.db import Conn

ROUTINE = "routine"


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

    @property
    def remote(self) -> bool:
        return self.server_url is not None

    def provider_def(self) -> dict:
        """What a model provider sees."""
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}


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
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()
