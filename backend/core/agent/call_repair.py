"""Call repair (agent.md §5, "Call repair"): before a call is settled, an unknown tool name is
answered with the closest real one, and the arguments are coerced to the tool's schema where the
model sent the right value in the wrong type ("42" for 42, a JSON string for a list)."""

from __future__ import annotations

import difflib
import json
import math
import re

from backend.core.agent import deferred, loop_guard, turn_hooks
from backend.core.agent.turn_hooks import TurnState

SUGGEST_CUTOFF = 0.7
_INT_RE = re.compile(r"-?\d+")
_TYPES = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}

# simplification: top-level properties only; nested objects, anyOf and oneOf are left to the handler;
# upgrade: recurse through items and properties.


def _matches(value, kind: str) -> bool:
    if kind in ("integer", "number") and isinstance(value, bool):
        return False
    return kind == "null" and value is None or isinstance(value, _TYPES.get(kind, ()))


def _convert(value, kind: str):
    """`value` as `kind`, or the original object when it does not convert cleanly."""
    if kind == "integer" and isinstance(value, str) and _INT_RE.fullmatch(value.strip()):
        return int(value.strip())
    if kind == "number" and isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return value
        return value if not math.isfinite(number) else int(number) if number.is_integer() else number
    if kind == "boolean" and isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    if kind in ("array", "object") and isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            parsed = None
        if _matches(parsed, kind):
            return parsed
    if kind == "array" and not isinstance(value, list):
        return [value]
    return value


def coerce(args: dict, schema: dict) -> dict:
    """A copy of `args` with each schema property that matches none of its allowed types converted
    to the first type it converts to cleanly; a value that already fits is left alone."""
    out = dict(args)
    for key, prop in (schema.get("properties") or {}).items():
        value = out.get(key)
        kinds = prop.get("type") if isinstance(prop, dict) else None
        kinds = [kinds] if isinstance(kinds, str) else kinds if isinstance(kinds, list) else []
        if value is None or not kinds or any(_matches(value, k) for k in kinds):
            continue
        for kind in kinds:
            if (new := _convert(value, kind)) is not value:
                out[key] = new
                break
    return out


def before_tool(state: TurnState, call: dict) -> str | None:
    name = call["name"]
    spec = state.by_name.get(name)
    if spec is not None:
        call["args"] = coerce(call.get("args") or {}, spec.input_schema)
        return None
    if name == deferred.FIND_TOOLS and state.deferred_specs:
        return None  # dispatch loads deferred tools
    names = [*state.by_name, *([deferred.FIND_TOOLS] if state.deferred_specs else [])]
    match = difflib.get_close_matches(name.lower().replace("-", "_"), names, n=1, cutoff=SUGGEST_CUTOFF)
    text = f"Unknown tool {name!r}. " + (
        f"Did you mean {match[0]!r}?" if match else "Use only the tools you were given."
    )
    return text + loop_guard.observe(state, name, call.get("args") or {}, "unknown tool")


turn_hooks.register("before_tool", before_tool)
