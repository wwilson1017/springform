"""Reports apps contribute through `reports.py` (`REPORTS = [Report(...)]`).

`run(params, user) -> (columns, rows)` receives the user and must apply the entity's
`can_read` to every row. The registry adds the app's manifest roles; `service.py` lists and
runs reports for a user and `router.py` serves them at `/api/core/reports`.

`params` is a JSON schema of the accepted params, limited to what a query string can carry:

    {"type": "object",
     "properties": {"<name>": {"type": "string" | "integer" | "number" | "boolean",
                               "format": "date",      # strings only: YYYY-MM-DD
                               "enum": [...], "default": ..., "title": "...", "description": "..."}},
     "required": ["<name>", ...]}

`register` refuses anything else, so a typo fails at startup instead of at run time.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from backend.core.auth.deps import has_role

if TYPE_CHECKING:
    from backend.core.auth.deps import User


@dataclass(frozen=True)
class Report:
    key: str  # '<app>.<name>'
    label: str
    app: str
    run: Callable[[dict, User], tuple[list[str], list[list[Any]]]]
    params: dict | None = None  # JSON schema of the accepted params (module docstring)
    admin_only: bool = False
    roles: tuple[str, ...] = ("admin", "member")  # set from the app manifest at mount


_REPORTS: dict[str, Report] = {}


PARAM_TYPES = ("string", "integer", "number", "boolean")
_PARAM_KEYS = {"type", "format", "enum", "default", "title", "description"}


def check_params(key: str, spec: dict | None) -> None:
    """Raise ValueError unless `spec` is None or the params shape in the module docstring."""

    def fail(problem: str):
        raise ValueError(f"Report {key!r}: params {problem}")

    if spec is None:
        return
    if not isinstance(spec, dict) or spec.get("type") != "object" or not set(spec) <= {"type", "properties", "required"}:
        fail('must be {"type": "object", "properties": {...}, "required": [...]}')
    props = spec.get("properties", {})
    if not isinstance(props, dict) or not set(spec.get("required", [])) <= set(props):
        fail("properties must be an object naming every required param")
    for name, prop in props.items():
        if not isinstance(prop, dict) or prop.get("type") not in PARAM_TYPES or not set(prop) <= _PARAM_KEYS:
            fail(f"{name!r} needs a type of {', '.join(PARAM_TYPES)} and only {', '.join(sorted(_PARAM_KEYS))}")
        if "format" in prop and (prop["format"] != "date" or prop["type"] != "string"):
            fail(f"{name!r}: the only format is 'date', on a string")


def register(report: Report) -> None:
    if not report.key.startswith(f"{report.app}."):
        raise ValueError(f"Report key {report.key!r} must start with '{report.app}.'")
    check_params(report.key, report.params)
    if report.key in _REPORTS:
        raise ValueError(f"Report {report.key!r} is registered twice")
    _REPORTS[report.key] = report


def clear() -> None:
    _REPORTS.clear()


def get(key: str) -> Report | None:
    return _REPORTS.get(key)


def allowed(report: Report, user: User) -> bool:
    """One of the app's roles (the system principal reads member reports), and admin for admin_only."""
    return has_role(user, report.roles) and (user.role == "admin" or not report.admin_only)


def for_user(user: User) -> list[Report]:
    return [r for r in _REPORTS.values() if allowed(r, user)]
