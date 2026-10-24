"""Reports apps contribute through `reports.py` (`REPORTS = [Report(...)]`).

`run(params, user) -> (columns, rows)` receives the user and must apply the entity's
`can_read` to every row. The registry adds the app's manifest roles; `GET
/api/core/reports/{key}` (a later workstream) serves `for_user`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.core.auth.deps import User


@dataclass(frozen=True)
class Report:
    key: str  # '<app>.<name>'
    label: str
    app: str
    run: Callable[[dict, User], tuple[list[str], list[list[Any]]]]
    params: dict | None = None  # JSON schema of the accepted params
    admin_only: bool = False
    roles: tuple[str, ...] = ("admin", "member")  # set from the app manifest at mount


_REPORTS: dict[str, Report] = {}


def register(report: Report) -> None:
    if not report.key.startswith(f"{report.app}."):
        raise ValueError(f"Report key {report.key!r} must start with '{report.app}.'")
    if report.key in _REPORTS:
        raise ValueError(f"Report {report.key!r} is registered twice")
    _REPORTS[report.key] = report


def clear() -> None:
    _REPORTS.clear()


def get(key: str) -> Report | None:
    return _REPORTS.get(key)


def for_user(user: User) -> list[Report]:
    return [
        r for r in _REPORTS.values()
        if user.role in r.roles and (user.role == "admin" or not r.admin_only)
    ]
