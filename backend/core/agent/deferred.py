"""Deferred tool loading (trimmed from Chatty `core/agents/deferred_tools.py`).

Past THRESHOLD tools, or when the static prompt plus every tool definition would exceed
BUDGET_TOKENS, only core tools go to the provider with full schemas; app tools appear as a compact
catalog grouped by app slug, and the model loads them with `core_find_tools`. Loaded tools stay
callable for the rest of the turn. Under both limits nothing changes.
"""

from __future__ import annotations

import json
from collections import defaultdict

from backend.core.agent.assembly import CHARS_PER_TOKEN
from backend.core.agent.spec import ToolSpec

THRESHOLD = 100
# What every turn sends before the conversation: the static system prompt plus the eager tool
# definitions, estimated as characters / 4. `test_prompt_budget.py` holds a stock install under it.
BUDGET_TOKENS = 14_000
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
        "properties": {
            "query": {
                "type": "string",
                "description": "A keyword (e.g. 'invoice'), an app slug, or an exact tool name.",
            }
        },
        "required": ["query"],
    },
}


def split(
    specs: list[ToolSpec], app_names: dict[str, str] | None = None, prompt_chars: int = 0
) -> tuple[list[ToolSpec], list[ToolSpec], str]:
    """(active, deferred, catalog text). Everything is active at or under the threshold, while
    `prompt_chars` (the static prompt) plus every definition also fits the budget, or deferring
    would not make the request smaller."""
    size = prompt_chars + len(json.dumps([s.provider_def() for s in specs]))
    deferred = [s for s in specs if s.app != "core"]
    if not deferred or (len(specs) <= THRESHOLD and size // CHARS_PER_TOKEN <= BUDGET_TOKENS):
        return specs, [], ""
    active = [s for s in specs if s.app == "core"]
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
    catalog = "\n".join(lines)
    if (
        len(specs) <= THRESHOLD
    ):  # deferring for size: only when it sends less (a few tiny tools can cost more as a catalog)
        after = prompt_chars + len(catalog) + len(json.dumps([*(s.provider_def() for s in active), FIND_TOOLS_DEF]))
        if after >= size:
            return specs, [], ""
    return active, deferred, catalog


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
