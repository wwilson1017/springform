"""Response models for the Requests board."""

from typing import Literal

from backend.core.platform.models import Out, UserRef


class RequestRow(Out):
    """A request filed here, mirroring its GitHub issue; `app` is "core" or an app slug."""

    id: int
    issue_number: int | None
    url: str | None
    state: Literal["open", "closed"]  # the GitHub issue's state
    title: str
    app: str
    description: str
    labels: list[str]
    requested_by: UserRef | None
    created_at: str
    updated_at: str


class RequestsConfig(Out):
    configured: bool
    warning_text: str
    repo: str | None
