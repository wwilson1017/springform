"""Files attached to any registered entity (docs/agents/records.md §2).

Content-addressed: the bytes for one sha256 live once on the volume (storage.py) with one
`core_file_blobs` row; each attachment is a `core_files` row pointing at a blob, unique per
(record, sha256). Publication stages the upload to tmp, hashes, fsyncs and thumbnails it outside
the lock, then ONE transaction upserts the blob (clearing `unreferenced_since`), inserts the row
and renames the file into place before COMMIT. The sweep (jobs.py) takes the same lock, so the
two never interleave. A blob whose last row goes gets `unreferenced_since`; the sweep deletes it
a week later unless a retained backup manifest still lists it.

Every function authorizes the parent record first: read to list, download or thumbnail; write to
upload or delete. `mime_type` is stored already allow-listed, and re-checked when served.
"""

from __future__ import annotations

import io
import json
import logging
import mimetypes
import re
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

from backend.core import clock, db, entities, settings
from backend.core.errors import NotFound
from backend.core.files import storage, thumbnails

if TYPE_CHECKING:
    from backend.core.auth.deps import User

logger = logging.getLogger(__name__)

DEFAULT_MAX_BYTES = 25 * 1024 * 1024  # setting files.max_bytes
OCTET = "application/octet-stream"
# Types served as themselves. Everything else, HTML, SVG and XML above all, is served as
# octet-stream: these bytes come back from the app's own origin.
ALLOWED_MIME = frozenset({
    "image/jpeg", "image/png", "image/gif", "image/webp", "image/heic",
    "application/pdf", "text/plain", "text/csv", "application/zip",
    "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint", "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "audio/mpeg", "audio/mp4", "video/mp4", "video/quicktime",
})  # fmt: skip

MAX_FILENAME_BYTES = 255
_UNSAFE_FILENAME_CHARS = re.compile(r'[\x00-\x1f\x7f-\x9f"\\]')
_SELECT = """SELECT f.id, f.filename, f.mime_type, f.byte_size, f.sha256, f.created_at, f.uploaded_by,
                    u.name AS uploader_name, f.thumb IS NOT NULL AS has_thumb
               FROM core_files f LEFT JOIN core_users u ON u.id = f.uploaded_by"""


def max_bytes() -> int:
    return int(settings.get_setting("files.max_bytes", DEFAULT_MAX_BYTES))


def served_mime(declared: str | None, filename: str = "") -> str:
    """The type a file is stored and served as: the declared type (or, failing that, one guessed
    from the name) when allow-listed, else octet-stream."""
    mime = (declared or "").split(";")[0].strip().lower()
    if not mime or mime == OCTET:
        mime = mimetypes.guess_type(filename)[0] or OCTET
    return mime if mime in ALLOWED_MIME else OCTET


def normalize_filename(raw: str | None) -> str:
    """Never empty, never a path, no control or quoting characters, at most 255 UTF-8 bytes. It
    is echoed into a Content-Disposition header."""
    name = unicodedata.normalize("NFC", raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = _UNSAFE_FILENAME_CHARS.sub("", name).strip()
    name = name.encode("utf-8")[:MAX_FILENAME_BYTES].decode("utf-8", errors="ignore").strip()
    return name if name not in ("", ".", "..") else "attachment"


def _file(row) -> dict:
    uploader = row["uploaded_by"]
    return {
        "id": row["id"],
        "filename": row["filename"],
        "mime_type": row["mime_type"],
        "byte_size": row["byte_size"],
        "sha256": row["sha256"],
        "created_at": row["created_at"],
        "uploaded_by": {"id": uploader, "name": row["uploader_name"]} if uploader is not None else None,
        "has_thumb": bool(row["has_thumb"]),
    }


def _authorized_row_in(conn: db.Conn, user: User, file_id: int, action: entities.Action) -> dict:
    row = conn.execute("SELECT * FROM core_files WHERE id = ?", (file_id,)).fetchone()
    if row is None:
        raise NotFound()
    entities.authorize(user, conn, row["entity_type"], row["entity_id"], action)
    return dict(row)


def _release_in(conn: db.Conn, shas: list[str]) -> None:
    """Start the clock on blobs that just lost their last row."""
    conn.execute(
        """UPDATE core_file_blobs SET unreferenced_since = ?
            WHERE sha256 IN (SELECT value FROM json_each(?)) AND unreferenced_since IS NULL
              AND NOT EXISTS (SELECT 1 FROM core_files f WHERE f.sha256 = core_file_blobs.sha256)""",
        (clock.now_iso(), json.dumps(shas)),
    )


# ── List ──────────────────────────────────────────────────────────────────────


def list_for_in(conn: db.Conn, user: User, entity_type: str, entity_id: int) -> list[dict]:
    """Newest first."""
    entities.authorize(user, conn, entity_type, entity_id, "read")
    rows = conn.execute(
        f"{_SELECT} WHERE f.entity_type = ? AND f.entity_id = ? ORDER BY f.created_at DESC, f.id DESC",
        (entity_type, entity_id),
    )
    return [_file(r) for r in rows]


def list_for(user: User, entity_type: str, entity_id: int) -> list[dict]:
    return list_for_in(db.get_conn(), user, entity_type, entity_id)


# ── Upload ────────────────────────────────────────────────────────────────────


@contextmanager
def _staged(src: BinaryIO) -> Iterator[tuple[storage.Staged, bytes | None]]:
    staged = storage.stage(src, max_bytes())
    try:
        yield staged, thumbnails.make(staged.path)
    finally:
        staged.path.unlink(missing_ok=True)  # already gone once published


def _publish_in(
    conn: db.Conn, user: User, entity_type: str, entity_id: int, filename: str | None, mime_type: str | None,
    staged: storage.Staged, thumb: bytes | None,
) -> tuple[dict, bool]:
    entities.authorize(user, conn, entity_type, entity_id, "write")
    now, name = clock.now_iso(), normalize_filename(filename)
    conn.execute(
        """INSERT INTO core_file_blobs (sha256, byte_size, created_at) VALUES (?, ?, ?)
           ON CONFLICT (sha256) DO UPDATE SET unreferenced_since = NULL, missing_at = NULL""",
        (staged.sha256, staged.byte_size, now),
    )
    cur = conn.execute(
        """INSERT INTO core_files (entity_type, entity_id, filename, mime_type, byte_size, sha256, thumb, uploaded_by, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (entity_type, entity_id, sha256) DO NOTHING""",
        (entity_type, entity_id, name, served_mime(mime_type, name), staged.byte_size, staged.sha256, thumb, user.id, now),
    )
    storage.publish(staged)  # the rename, under the lock and before COMMIT
    row = conn.execute(
        f"{_SELECT} WHERE f.entity_type = ? AND f.entity_id = ? AND f.sha256 = ?", (entity_type, entity_id, staged.sha256)
    ).fetchone()
    return _file(row), cur.rowcount == 1


def upload(
    user: User, entity_type: str, entity_id: int, filename: str | None, mime_type: str | None, src: BinaryIO
) -> tuple[dict, bool]:
    """Attach the bytes read from `src`. Returns (file, created); created is False when the record
    already had these bytes, and that existing row is returned."""
    entities.authorize(user, db.get_conn(), entity_type, entity_id, "write")  # refuse before touching the disk
    with _staged(src) as (staged, thumb), db.transaction() as conn:
        return _publish_in(conn, user, entity_type, entity_id, filename, mime_type, staged, thumb)


def upload_in(
    conn: db.Conn, user: User, entity_type: str, entity_id: int, filename: str | None, mime_type: str | None, src: BinaryIO
) -> tuple[dict, bool]:
    """upload() in the caller's transaction. Staging and the thumbnail then run under the write
    lock, so prefer upload() when not already in one."""
    entities.authorize(user, conn, entity_type, entity_id, "write")
    with _staged(src) as (staged, thumb):
        return _publish_in(conn, user, entity_type, entity_id, filename, mime_type, staged, thumb)


def attach(user: User, entity_type: str, entity_id: int, filename: str, data: bytes, mime_type: str | None = None) -> dict:
    return upload(user, entity_type, entity_id, filename, mime_type, io.BytesIO(data))[0]


def attach_in(
    conn: db.Conn, user: User, entity_type: str, entity_id: int, filename: str, data: bytes, mime_type: str | None = None
) -> dict:
    return upload_in(conn, user, entity_type, entity_id, filename, mime_type, io.BytesIO(data))[0]


# ── Read ──────────────────────────────────────────────────────────────────────


def download_in(conn: db.Conn, user: User, file_id: int) -> tuple[dict, Path]:
    """({filename, mime_type}, path) for serving. Gone (410) when the bytes are not on disk."""
    row = _authorized_row_in(conn, user, file_id, "read")
    path = storage.blob_path(row["sha256"])
    if not path.is_file():
        logger.error("file %s: blob %s is missing from disk", file_id, row["sha256"])
        raise storage.Gone()
    return {"filename": row["filename"], "mime_type": served_mime(row["mime_type"])}, path


def download(user: User, file_id: int) -> tuple[dict, Path]:
    return download_in(db.get_conn(), user, file_id)


def read_bytes_in(conn: db.Conn, user: User, file_id: int) -> bytes:
    return download_in(conn, user, file_id)[1].read_bytes()


def read_bytes(user: User, file_id: int) -> bytes:
    return read_bytes_in(db.get_conn(), user, file_id)


def thumb_in(conn: db.Conn, user: User, file_id: int) -> bytes:
    """The JPEG thumbnail; NotFound when the file has none."""
    row = _authorized_row_in(conn, user, file_id, "read")
    if row["thumb"] is None:
        raise NotFound()
    return row["thumb"]


def thumb(user: User, file_id: int) -> bytes:
    return thumb_in(db.get_conn(), user, file_id)


# ── Delete, entity hooks ──────────────────────────────────────────────────────


def delete_in(conn: db.Conn, user: User, file_id: int) -> None:
    row = _authorized_row_in(conn, user, file_id, "write")
    conn.execute("DELETE FROM core_files WHERE id = ?", (file_id,))
    _release_in(conn, [row["sha256"]])


def delete(user: User, file_id: int) -> None:
    with db.transaction() as conn:
        delete_in(conn, user, file_id)


def on_entity_deleted_in(conn: db.Conn, entity_type: str, entity_id: int) -> None:
    shas = conn.execute(
        "DELETE FROM core_files WHERE entity_type = ? AND entity_id = ? RETURNING sha256", (entity_type, entity_id)
    ).fetchall()
    _release_in(conn, [r[0] for r in shas])


def move_to_in(conn: db.Conn, entity_type: str, source_id: int, target_id: int) -> None:
    """Move the source record's files to the target. A source row whose bytes the target already
    has is dropped (the target's row wins); its blob stays referenced by the target's."""
    conn.execute(
        """DELETE FROM core_files WHERE entity_type = ? AND entity_id = ?
              AND sha256 IN (SELECT sha256 FROM core_files WHERE entity_type = ? AND entity_id = ?)""",
        (entity_type, source_id, entity_type, target_id),
    )
    conn.execute("UPDATE core_files SET entity_id = ? WHERE entity_type = ? AND entity_id = ?", (target_id, entity_type, source_id))


def move_to(entity_type: str, source_id: int, target_id: int) -> None:
    with db.transaction() as conn:
        move_to_in(conn, entity_type, source_id, target_id)


def on_entity_merged_in(conn: db.Conn, entity_type: str, target_id: int, source_id: int) -> None:
    move_to_in(conn, entity_type, source_id, target_id)
