"""Reports for a user: which they may run, and running one with its params checked.

Who may run a report: one of its app's roles, and admin when it is `admin_only` (unknown key
404, not allowed 403). The report's own `run(params, user)` then applies `can_read` per row.

Params arrive as strings from a query string or typed from Python; both are coerced to the
spec's types (`registry.py` docstring). Unknown params are refused, empty ones count as absent,
an absent one takes its `default` or is left out, and a missing `required` one is refused.

`run` opens no transaction and a report reads through this thread's connection, so it is safe
inside a caller's transaction; that is why there is no separate `run_in`. The CSV route
(core/export) calls `run` and streams `{columns, rows}`.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from datetime import date
from typing import TYPE_CHECKING, Any

from backend.core.errors import Forbidden, Invalid, NotFound
from backend.core.reports import registry

if TYPE_CHECKING:
    from backend.core.auth.deps import User

_BOOLS = {"true": True, "1": True, "false": False, "0": False}
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_EXPECTED = {"string": "text", "integer": "an integer", "number": "a number", "boolean": "true or false"}


def list_for(user: User) -> list[dict]:
    return [
        {"key": r.key, "label": r.label, "app": r.app, "params": r.params, "admin_only": r.admin_only}
        for r in registry.for_user(user)
    ]


def _coerce(name: str, prop: dict, value: Any) -> Any:
    t, is_date = prop["type"], prop.get("format") == "date"
    try:
        if t == "integer":
            value = value if type(value) is int else int(str(value))
        elif t == "number":
            value = value if type(value) in (int, float) else float(str(value))
            if not math.isfinite(value):
                raise ValueError
        elif t == "boolean":
            value = value if isinstance(value, bool) else _BOOLS[str(value).lower()]
        else:
            value = str(value)
            if is_date and not (_DATE.fullmatch(value) and date.fromisoformat(value)):
                raise ValueError
    except (ValueError, KeyError, OverflowError):
        raise Invalid(f"{name}: expected {'a date (YYYY-MM-DD)' if is_date else _EXPECTED[t]}") from None
    if "enum" in prop and value not in prop["enum"]:
        raise Invalid(f"{name}: one of {', '.join(map(str, prop['enum']))}")
    return value


def params_for(report: registry.Report, raw: Mapping[str, Any]) -> dict:
    spec = report.params or {}
    props = spec.get("properties", {})
    if unknown := sorted(set(raw) - set(props)):
        raise Invalid(f"unknown param: {', '.join(unknown)}")
    out = {}
    for name, prop in props.items():
        if raw.get(name) not in (None, ""):
            out[name] = _coerce(name, prop, raw[name])
        elif "default" in prop:
            out[name] = prop["default"]
        elif name in spec.get("required", ()):
            raise Invalid(f"{name}: required")
    return out


def run(user: User, key: str, params: Mapping[str, Any]) -> dict:
    """{columns, rows} of report `key` for `user`."""
    report = registry.get(key)
    if report is None:
        raise NotFound()
    if not registry.allowed(report, user):
        raise Forbidden("admin_only" if report.admin_only else "forbidden")
    columns, rows = report.run(params_for(report, params), user)
    return {"columns": list(columns), "rows": [list(r) for r in rows]}
