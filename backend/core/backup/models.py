"""Response models for the Backups page."""

from typing import Literal

from pydantic import BaseModel, Field

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


class Offsite(Out):
    """The off-site copy: the destination minus its secret, and how the last upload went.
    `unreadable`: the stored settings cannot be decrypted (the encryption key changed).
    `stale`: configured, and no good upload in more than 48 hours."""

    configured: bool
    unreadable: bool
    endpoint: str | None
    bucket: str | None
    region: str | None
    prefix: str | None
    access_key_id: str | None
    retention: int | None
    encrypted: bool
    last_success_at: str | None
    last_success_bytes: int | None
    last_error: str | None
    stale: bool


class DestinationIn(BaseModel):
    """`secret_key` is write-only; leave it out to keep the stored one."""

    endpoint: str = Field(min_length=1, max_length=2048)
    bucket: str = Field(min_length=1, max_length=255)
    region: str = Field(default="us-east-1", min_length=1, max_length=128)
    prefix: str = Field(default="", max_length=512)
    access_key_id: str = Field(min_length=1, max_length=512)
    secret_key: str | None = Field(default=None, max_length=4096)
    retention: int = Field(default=30, ge=1, le=365)


class PassphraseIn(BaseModel):
    passphrase: str = Field(min_length=8, max_length=1024)


class BackupsOverview(Out):
    sets: list[BackupSet]
    last_backup_at: str | None
    last_run: BackupRun | None
    key_source: KeySource
    key_shown: bool
    key_mismatch: str | None  # the newest manifest taken under another encryption key, as the last boot found it
    offsite: Offsite


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
