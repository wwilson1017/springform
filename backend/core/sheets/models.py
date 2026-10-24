"""Response models for connected Google Sheets."""

from typing import Literal

from backend.core.platform.models import Out


class SheetCredentials(Out):
    """Whether a service-account key is stored; the key itself never comes back."""

    configured: bool
    service_account_email: str | None


class ConnectedSheet(Out):
    """A sheet an app declares in its manifest; an admin sets spreadsheet_id and range (`configured`)."""

    id: int
    app: str
    name: str
    description: str
    spreadsheet_id: str
    range: str
    mode: Literal["read", "write"]
    schedule: Literal["hourly", "daily", "manual"]
    enabled: bool
    last_synced_at: str | None
    last_error: str | None
    row_count: int | None
    created_at: str
    updated_at: str
    fetched_at: str | None
    configured: bool


class SheetPreview(Out):
    """The cached header and first rows; every cell is a string."""

    header: list[str]
    rows: list[list[str]]
    fetched_at: str | None
    row_count: int | None
    stale: bool
