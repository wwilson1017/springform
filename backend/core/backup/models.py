"""Response models for the Backups page."""

from typing import Literal

from backend.core.platform.models import Out

KeySource = Literal["env", "file"]


class BackupSet(Out):
    """One recovery set on disk. `manifest_ok`: the manifest parses and its snapshot is present at the
    recorded size. `status` comes from the run log (None when no run on this install recorded it)."""

    stamp: str
    created_at: str | None
    snapshot_bytes: int | None
    blob_count: int | None
    status: str | None
    manifest_ok: bool


class BackupRun(Out):
    """A `core_backups` row: one run of the nightly job or of "Back up now"."""

    id: int
    started_at: str
    finished_at: str
    status: Literal["ok", "error", "skipped"]
    snapshot: str | None
    manifest: str | None
    byte_size: int | None
    sha256: str | None
    error: str | None


class BackupRunUnrecorded(Out):
    """What POST /run answers when the run could not be written to the log: its outcome only."""

    status: Literal["ok", "error", "skipped"]
    snapshot: str | None = None
    manifest: str | None = None
    byte_size: int | None = None
    sha256: str | None = None
    error: str | None = None


class BackupsOverview(Out):
    sets: list[BackupSet]
    last_backup_at: str | None
    last_run: BackupRun | None
    key_source: KeySource
    key_shown: bool
    key_mismatch: str | None  # the newest manifest taken under another encryption key, as the last boot found it


class KeyReveal(Out):
    """The key once (`key_source` "file"); an environment key is never returned, only its fingerprint."""

    key_source: KeySource
    key: str | None = None
    fingerprint: str


class ManifestSnapshot(Out):
    filename: str
    sha256: str
    byte_size: int


class BackupManifest(Out):
    version: int
    springform_version: str
    created_at: str
    snapshot: ManifestSnapshot
    blobs: list[str]
    key_fingerprint: str
    key_source: KeySource
