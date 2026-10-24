"""Deferred tool loading (trimmed from Chatty `core/agents/deferred_tools.py`).

Past THRESHOLD tools, only core tools go to the provider with full schemas; app tools appear as
a compact catalog grouped by app slug, and the model loads them with `core_find_tools`. Loaded
tools stay callable for the rest of the turn. Under the threshold nothing changes.
"""

from __future__ import annotations

from collections import defaultdict

from backend.core.agent.spec import ToolSpec

THRESHOLD = 100
MAX_CATALOG_CHARS = 3000
MAX_RESULTS = 20
FIND_TOOLS = "core_find_tools"
FIND_TOOLS_DEF = {
    "name": FIND_TOOLS,
    "description": (
        "Load more tools by keyword, app name or exact tool name. Call this when you need a tool "
        "listed in the 'More tools' catalog; loaded tools become callable for the rest of this turn."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "A keyword (e.g. 'invoice'), an app slug, or an exact tool name."}},
        "required": ["query"],
    },
}


def split(specs: list[ToolSpec], app_names: dict[str, str] | None = None) -> tuple[list[ToolSpec], list[ToolSpec], str]:
    """(active, deferred, catalog text). Everything is active at or under the threshold."""
    if len(specs) <= THRESHOLD:
        return specs, [], ""
    active = [s for s in specs if s.app == "core"]
    deferred = [s for s in specs if s.app != "core"]
    groups: dict[str, list[str]] = defaultdict(list)
    for s in deferred:
        groups[s.app].append(s.name)
    lines = ["## More tools (load with core_find_tools)"]
    for app in sorted(groups):
        line = f"**{(app_names or {}).get(app, app)}** ({app}): {', '.join(groups[app])}"
        if sum(len(x) + 1 for x in lines) + len(line) > MAX_CATALOG_CHARS - 80:
            lines.append(f"... and more ({len(deferred)} tools in all). Search with core_find_tools.")
            break
        lines.append(line)
    return active, deferred, "\n".join(lines)


def find(query: str, deferred: list[ToolSpec]) -> list[ToolSpec]:
    """Exact name, then app slug, then substring of name or description; at most MAX_RESULTS."""
    q = (query or "").strip().lower()
    if not q:
        return []
    for match in (
        lambda s: s.name.lower() == q,
        lambda s: s.app == q,
        lambda s: q in s.name.lower() or q in s.description.lower(),
    ):
        found = [s for s in deferred if match(s)]
        if found:
            return found[:MAX_RESULTS]
    return []
