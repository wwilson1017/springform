"""Response models for reports. `params` is the report's JSON schema of accepted query params."""

from typing import Any

from backend.core.platform.models import Out


class ReportInfo(Out):
    key: str
    label: str
    app: str
    params: dict[str, Any] | None
    admin_only: bool


class ReportResult(Out):
    columns: list[str]
    rows: list[list[Any]]
