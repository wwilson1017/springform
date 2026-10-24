"""Response models for health, apps, settings, workspace, jobs and the change log, plus the small
shapes other core packages share (`Out`, `UserRef`, `Ok`, `Updated`).

Every model mirrors the dict its route already builds: same keys, same order, same nullability.
`Out` forbids extra keys, so a key a service adds without adding it here fails the response
(500) instead of silently vanishing from it; `test_response_models.py` calls every typed route."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from backend.core.registry import SettingsCard


class Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UserRef(Out):
    id: int
    name: str


class Ok(Out):
    ok: bool


class Updated(Out):
    updated: int


class Health(Out):
    version: str
    sqlite_version: str
    fts5: bool
    preview: bool
    apps: list[str]
    last_backup_at: str | None
    key_mismatch: bool  # the boot found the newest backup taken under another encryption key


class CoreApp(Out):
    """One launcher app; admins also get hidden ones, marked hidden."""

    slug: str
    name: str
    description: str
    path: str
    icon: str
    roles: list[Literal["admin", "member"]]
    order: int
    badge: str | None
    hidden: bool
    settings_cards: list[SettingsCard]
    version: str


class CoreSettings(Out):
    """`values`/`defaults` for plain keys; `secrets` says only whether a secret is set."""

    values: dict[str, Any]
    secrets: dict[str, bool]
    defaults: dict[str, Any]


class Workspace(Out):
    name: str
    timezone: str
    version: str
    preview: bool
    public_url: str


RunStatus = Literal["running", "ok", "error", "timed_out", "interrupted", "skipped"]


class JobLastRun(Out):
    status: RunStatus
    started_at: str
    finished_at: str | None
    error: str | None


class JobInfo(Out):
    name: str
    app: str
    every: int | None  # seconds; None for an `at` job
    at: str | None  # "HH:MM" install-local; None for an `every` job
    timeout: int | float
    last_run: JobLastRun | None
    in_flight: bool


class JobRun(Out):
    id: int
    job: str
    app: str
    trigger: Literal["schedule", "manual", "nudge"]
    status: RunStatus
    scheduled_for: str | None
    started_at: str
    finished_at: str | None
    error: str | None


class DeadOutboxRow(Out):
    id: int
    hook: str
    attempts: int
    last_error: str | None
    created_at: str
    dead_at: str


class JobStarted(Out):
    started: bool


class ChangeRow(Out):
    """`title` and `url` are None when the record is gone (shown only to the user who wrote it)."""

    id: int
    at: str
    user: UserRef | None
    app: str
    entity_type: str
    entity_id: int
    title: str | None
    url: str | None
    field: str
    old: Any
    new: Any
    reason: str | None
    deleted_at: str | None
