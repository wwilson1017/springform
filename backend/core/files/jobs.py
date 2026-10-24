"""The files sweep, `core.files_sweep` at 03:30 install-local (docs/agents/records.md §2).

Inside ONE transaction, so no upload can publish in between:
1. blobs unreferenced for over 7 days that no retained backup manifest lists lose their row and
   their file (the NOT EXISTS re-checks "still unreferenced" under the lock);
2. every blob row whose file is missing gets `missing_at` (and is logged); one whose file came
   back is cleared;
3. a file under files/<xx>/ with no blob row and mtime over 24 h old is an orphan (a publication
   rolled back after its rename) and is removed.
Then, outside the lock, tmp uploads older than 24 h are removed. File ages compare mtimes with
the real clock; blob ages use core.clock like every stored timestamp.
"""

from __future__ import annotations

import json
import logging
import threading
import time

from backend.core import clock, db, scheduler
from backend.core.files import storage

logger = logging.getLogger(__name__)

KEEP_UNREFERENCED = 7 * 86400
STALE_FILE = 86400


def pinned_blobs() -> set[str]:
    """Every sha256 a retained backup set lists (`<data>/backups/*.manifest.json`, top-level
    "blobs"). A manifest without a "blobs" list fails the sweep rather than unpinning its set."""
    pinned: set[str] = set()
    for path in sorted((db.data_dir() / "backups").glob("*.manifest.json")):
        pinned.update(json.loads(path.read_text(encoding="utf-8"))["blobs"])
    return pinned


def sweep(cancel: threading.Event | None = None) -> dict:
    stale = time.time() - STALE_FILE
    # simplification: the orphan and missing-file checks walk every blob under the write lock
    # (milliseconds for thousands of files); upgrade path: walk outside, re-check candidates inside.
    with db.transaction() as conn:
        pinned = pinned_blobs()
        expired = [
            sha for (sha,) in conn.execute(
                """SELECT sha256 FROM core_file_blobs b WHERE unreferenced_since < ?
                      AND NOT EXISTS (SELECT 1 FROM core_files f WHERE f.sha256 = b.sha256)""",
                (clock.ago(KEEP_UNREFERENCED),),
            ).fetchall()
            if sha not in pinned
        ]
        for sha in expired:
            conn.execute("DELETE FROM core_file_blobs WHERE sha256 = ?", (sha,))
            storage.blob_path(sha).unlink(missing_ok=True)

        known = {sha for (sha,) in conn.execute("SELECT sha256 FROM core_file_blobs")}
        missing = sorted(sha for sha in known if not storage.blob_path(sha).is_file())
        conn.execute(
            "UPDATE core_file_blobs SET missing_at = NULL WHERE missing_at IS NOT NULL AND sha256 NOT IN (SELECT value FROM json_each(?))",
            (json.dumps(missing),),
        )
        conn.execute(
            "UPDATE core_file_blobs SET missing_at = ? WHERE missing_at IS NULL AND sha256 IN (SELECT value FROM json_each(?))",
            (clock.now_iso(), json.dumps(missing)),
        )
        if missing:
            logger.error("files sweep: %d blob(s) missing from disk: %s", len(missing), ", ".join(missing))

        orphans = [
            p for p in storage.root().glob("??/*") if p.is_file() and p.name not in known and p.stat().st_mtime < stale
        ]
        for p in orphans:
            p.unlink(missing_ok=True)

    tmp = [p for p in storage.tmp_dir().glob("*") if p.is_file() and p.stat().st_mtime < stale]
    for p in tmp:
        p.unlink(missing_ok=True)
    result = {"expired": len(expired), "missing": len(missing), "orphans": len(orphans), "tmp": len(tmp)}
    logger.info("files sweep: %s", result)
    return result


JOBS = [scheduler.Job("core.files_sweep", sweep, at="03:30")]
