"""Recovery sets: `<data>/backups/<stamp>.sqlite` plus `<stamp>.manifest.json`, written last.

A set is complete iff its manifest exists. The manifest lists every blob (`core_files.sha256`)
the snapshot references; the files sweep never deletes a blob a retained manifest lists, so
every retained set restores whole, and pruning a set is what releases its blobs.

`run()` never raises: a failure is logged and recorded in `core_backups` (`ok | error | skipped`).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path

from backend.core import VERSION, clock, db, secrets, settings
from backend.core.errors import AppError, NotFound

logger = logging.getLogger(__name__)

KEEP = 7
MIN_FREE_BYTES = 100 * 1024 * 1024  # free space that must remain after a snapshot the size of the DB
ORPHAN_AGE = 3600  # seconds before a snapshot without a manifest, or a .tmp, counts as abandoned
STAMP = re.compile(r"^\d{8}T\d{6}Z$")
SNAPSHOT, MANIFEST = ".sqlite", ".manifest.json"
KEY_SHOWN = "backups.key_shown_at"
MANIFEST_VERSION = 1

_running = threading.Lock()  # one run at a time, whether the job or "Back up now" started it


class KeyAlreadyShown(AppError):
    status, default = 410, "key_already_shown"


def backups_dir() -> Path:
    return db.data_dir() / "backups"


def key_source() -> str:
    return "env" if os.environ.get("ENCRYPTION_KEY") else "file"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def _write_synced(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def run(trigger: str = "job") -> dict | None:
    """Take a recovery set. Returns the `core_backups` row, or None when a run is already in
    progress (nothing is recorded then). Never raises."""
    if not _running.acquire(blocking=False):
        logger.info("Backup (%s) not started: another backup is running", trigger)
        return None
    try:
        started = clock.now()
        try:
            status, fields = _take(started)
        except Exception as e:
            logger.exception("Backup (%s) failed; the next run tries again", trigger)
            status, fields = "error", {"error": repr(e)[:2000]}
        if status == "skipped":
            logger.warning("Backup (%s) skipped: %s", trigger, fields["error"])
        elif status == "ok":
            logger.info("Backup (%s) written: %s", trigger, fields["snapshot"])
        return _record(started, status, fields)
    finally:
        _running.release()


def _take(started: datetime) -> tuple[str, dict]:
    data, out = db.data_dir(), backups_dir()
    free = shutil.disk_usage(out if out.is_dir() else data).free
    need = (data / db.DB_FILENAME).stat().st_size + MIN_FREE_BYTES
    if free < need:
        return "skipped", {"error": f"low disk space: {free // 2**20} MB free, {need // 2**20} MB needed"}
    out.mkdir(exist_ok=True)
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    final, manifest = out / f"{stamp}{SNAPSHOT}", out / f"{stamp}{MANIFEST}"
    if final.exists() or manifest.exists():
        raise FileExistsError(f"a backup named {stamp} already exists; try again in a second")
    tmp = out / f"{stamp}{SNAPSHOT}.tmp"
    tmp.unlink(missing_ok=True)
    try:
        # VACUUM INTO reads one consistent snapshot without blocking writers; it cannot run inside
        # a transaction, and the job and the route never hold one here.
        db.get_conn().execute("VACUUM INTO ?", (str(tmp),))
        snap = db.sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
        try:  # the blobs this snapshot references, read from the snapshot itself
            blobs = [r[0] for r in snap.execute("SELECT DISTINCT sha256 FROM core_files ORDER BY sha256")]
        finally:
            snap.close()
        with open(tmp, "rb+") as f:
            os.fsync(f.fileno())
        digest, size = sha256_file(tmp), tmp.stat().st_size
        os.replace(tmp, final)
    finally:
        tmp.unlink(missing_ok=True)
    body = {
        "version": MANIFEST_VERSION,
        "springform_version": VERSION,
        "created_at": clock.to_iso(started),
        "snapshot": {"filename": final.name, "sha256": digest, "byte_size": size},
        "blobs": blobs,
        "key_fingerprint": secrets.key_fingerprint(),
        "key_source": key_source(),
    }
    _write_synced(manifest, json.dumps(body, indent=2).encode())  # last: the set is now complete
    try:
        prune()
    except Exception:
        logger.exception("Pruning old backups failed; the new set is complete")
    return "ok", {"snapshot": final.name, "manifest": manifest.name, "byte_size": size, "sha256": digest}


def _record(started: datetime, status: str, fields: dict) -> dict:
    try:
        with db.transaction() as conn:
            row_id = conn.execute(
                """INSERT INTO core_backups (started_at, finished_at, status, snapshot, manifest, byte_size, sha256, error)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (clock.to_iso(started), clock.now_iso(), status, fields.get("snapshot"), fields.get("manifest"),
                 fields.get("byte_size"), fields.get("sha256"), fields.get("error")),
            ).lastrowid
        return db.one("SELECT * FROM core_backups WHERE id = ?", (row_id,))
    except Exception:
        logger.exception("Could not record the backup run")
        return {"status": status, **fields}


def prune() -> None:
    """Keep the newest KEEP complete sets; drop older ones (manifest first, so a set is never
    complete without its snapshot) and abandoned snapshots or temp files."""
    out = backups_dir()
    complete = sorted(p.name[: -len(MANIFEST)] for p in out.glob(f"*{MANIFEST}"))
    for stamp in complete[:-KEEP]:
        (out / f"{stamp}{MANIFEST}").unlink(missing_ok=True)
        (out / f"{stamp}{SNAPSHOT}").unlink(missing_ok=True)
    now = time.time()
    for p in out.iterdir():
        abandoned = p.name.endswith(".tmp") or (
            p.name.endswith(SNAPSHOT) and not (out / f"{p.name[: -len(SNAPSHOT)]}{MANIFEST}").exists()
        )
        if abandoned and p.is_file() and now - p.stat().st_mtime > ORPHAN_AGE:
            p.unlink(missing_ok=True)


def read_manifest(stamp: str) -> dict | None:
    if not STAMP.match(stamp):
        return None
    try:
        return json.loads((backups_dir() / f"{stamp}{MANIFEST}").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def snapshot_path(stamp: str) -> Path:
    path = backups_dir() / f"{stamp}{SNAPSHOT}"
    if not STAMP.match(stamp) or not path.is_file():
        raise NotFound("backup_not_found")
    return path


def list_sets() -> list[dict]:
    """Every set on disk, newest first. `manifest_ok`: the manifest parses and its snapshot is
    present at the recorded size (the sha256 is checked on restore, not on every listing)."""
    out = backups_dir()
    if not out.is_dir():
        return []
    stamps = {
        p.name.split(".", 1)[0] for p in out.iterdir() if p.name.endswith((SNAPSHOT, MANIFEST))
    }
    statuses = {r["snapshot"]: r["status"] for r in db.rows("SELECT snapshot, status FROM core_backups ORDER BY id")}
    sets = []
    for stamp in sorted((s for s in stamps if STAMP.match(s)), reverse=True):
        manifest, snap = read_manifest(stamp), out / f"{stamp}{SNAPSHOT}"
        size = snap.stat().st_size if snap.is_file() else None
        try:
            ok = manifest["version"] == MANIFEST_VERSION and manifest["snapshot"]["byte_size"] == size
            blob_count = len(manifest["blobs"])
        except (TypeError, KeyError):
            ok, blob_count = False, None
        sets.append({
            "stamp": stamp,
            "created_at": manifest.get("created_at") if isinstance(manifest, dict) else None,
            "snapshot_bytes": size,
            "blob_count": blob_count,
            "status": statuses.get(snap.name),
            "manifest_ok": ok,
        })
    return sets


def last_backup_at() -> str | None:
    """When the newest complete set on this volume was taken (None when there is none)."""
    out = backups_dir()
    for p in sorted(out.glob(f"*{MANIFEST}"), reverse=True) if out.is_dir() else []:
        manifest = read_manifest(p.name[: -len(MANIFEST)])
        if isinstance(manifest, dict) and manifest.get("created_at"):
            return manifest["created_at"]
    return None


def overview() -> dict:
    """The Backups page: the sets, the last run (so a failure or skip is visible) and the key state."""
    return {
        "sets": list_sets(),
        "last_backup_at": last_backup_at(),
        "last_run": db.one("SELECT * FROM core_backups ORDER BY id DESC LIMIT 1"),
        "key_source": key_source(),
        "key_shown": settings.get_setting(KEY_SHOWN) is not None,
    }


def reveal_key(user_id: int) -> dict:
    """The encryption key, once. An environment key is never returned: it lives with the `.env`."""
    fingerprint = secrets.key_fingerprint()
    if key_source() == "env":
        return {"key_source": "env", "fingerprint": fingerprint}
    key = secrets.key().decode()
    with db.transaction() as conn:
        if conn.execute("SELECT 1 FROM core_settings WHERE key = ?", (KEY_SHOWN,)).fetchone():
            raise KeyAlreadyShown()
        settings.set_setting_in(conn, KEY_SHOWN, clock.now_iso(), user_id)
    return {"key_source": "file", "key": key, "fingerprint": fingerprint}
