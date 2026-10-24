"""The tool registry: one validated, immutable set of ToolSpecs, swapped in whole.

`build_registry(specs)` validates everything at boot (a malformed tool fails startup, so a new
source can never silently clobber or weaken another). The live registry is replaced atomically
(`set_current`), so an in-flight turn keeps the set it started with. Outbound MCP servers are the
one source that changes after boot: `swap_server` replaces a server's tools the same way.

Exposure: `for_user(user)` filters by `enabled(user)` (which the app registry wraps with the
app's roles); `for_source(source)` applies what a source may ever see. A caller wants the
intersection, e.g. MCP exposes `for_user(link_user)` ∩ `for_source("mcp")`.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterable
from typing import TYPE_CHECKING, Literal

from backend.core.agent.spec import ROUTINE, ToolSpec

if TYPE_CHECKING:
    from backend.core.auth.deps import User

Source = Literal["chat", "mcp", "job"]
_NAME = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")  # what provider APIs accept


class ToolSpecError(ValueError):
    pass


class ToolRegistry:
    def __init__(self, specs: Iterable[ToolSpec] = ()):
        self._specs: dict[str, ToolSpec] = {s.name: s for s in specs}

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def all(self) -> list[ToolSpec]:
        return list(self._specs.values())

    def for_user(self, user: User) -> list[ToolSpec]:
        return [s for s in self._specs.values() if s.enabled(user)]

    def for_source(self, source: Source) -> list[ToolSpec]:
        if source == "chat":
            return self.all()
        if source == "mcp":
            return [s for s in self._specs.values() if s.mcp_exposed and not s.remote]
        if source == "job":  # unattended: runs as the system principal with nobody to confirm
            return [
                s for s in self._specs.values()
                if not s.writes and not s.always_confirm and not s.remote and not s.untrusted_source
            ]
        raise ValueError(f"Unknown tool source {source!r}")


def _problems(spec: ToolSpec) -> list[str]:
    p = []
    if not _NAME.match(spec.name):
        p.append("name must be 1-64 of [a-zA-Z0-9_-]")
    if not spec.name.startswith(f"{spec.app}_"):
        p.append(f"name must start with '{spec.app}_'")
    if not isinstance(spec.writes, bool):
        p.append("writes must be a bool")
    if spec.confirm_tier is not None:
        if spec.confirm_tier != ROUTINE:
            p.append(f"confirm_tier must be {ROUTINE!r} or None")
        if spec.writes is not True:
            p.append("confirm_tier is only valid on a write")
    if not isinstance(spec.input_schema, dict) or spec.input_schema.get("type") != "object":
        p.append("input_schema must be a JSON schema of type 'object'")
    if (spec.handler is None) == (spec.handler_in is None):
        p.append("give exactly one of handler and handler_in")
    if spec.writes is True and not spec.external_effect and (spec.handler_in is None or spec.targets is None):
        p.append("a local write needs handler_in and targets (or external_effect=True with handler)")
    if spec.external_effect and spec.handler is None:
        p.append("an external_effect tool runs through handler, outside any transaction")
    if spec.writes is False and spec.handler_in is not None:
        p.append("a read runs through handler, not handler_in")
    if spec.remote and not (spec.always_confirm and spec.untrusted_source and spec.external_effect):
        p.append("a remote tool is always_confirm, untrusted_source and external_effect")
    return [f"tool {spec.name!r}: {x}" for x in p]


def build_registry(specs: Iterable[ToolSpec]) -> ToolRegistry:
    specs = list(specs)
    problems, seen = [], set()
    for spec in specs:
        if spec.name in seen:
            problems.append(f"tool {spec.name!r}: duplicate name")
        seen.add(spec.name)
        problems += _problems(spec)
    if problems:
        raise ToolSpecError("Invalid tool registry:\n  " + "\n  ".join(problems))
    return ToolRegistry(specs)


_current = ToolRegistry()
_swap_lock = threading.Lock()


def set_current(registry: ToolRegistry) -> None:
    global _current
    _current = registry


def swap_server(server_id: str, specs: Iterable[ToolSpec]) -> None:
    """Replace one outbound MCP server's tools in the live registry (no specs drops them). The
    whole set is rebuilt and validated, then swapped in at once; on ToolSpecError nothing changes.
    A pending approval of a replaced spec fails its tool_def_sha256 check at confirm time."""
    with _swap_lock:
        keep = [s for s in _current.all() if s.server_id != server_id]
        set_current(build_registry([*keep, *specs]))


def current() -> ToolRegistry:
    return _current


def get(name: str) -> ToolSpec | None:
    return _current.get(name)


def for_user(user: User) -> list[ToolSpec]:
    return _current.for_user(user)


def for_source(source: Source) -> list[ToolSpec]:
    return _current.for_source(source)
