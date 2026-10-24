"""Bytes on the volume: `<data>/files/<sha[:2]>/<sha>`, uploads staged in `<data>/files/tmp/<uuid>`."""

from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from backend.core import db
from backend.core.errors import AppError

CHUNK = 1024 * 1024


class TooLarge(AppError):
    status, default = 413, "file_too_large"


class Gone(AppError):
    """The row exists but its bytes are not on disk; never served as if they were."""

    status, default = 410, "file_missing"


@dataclass(frozen=True)
class Staged:
    path: Path
    sha256: str
    byte_size: int


def root() -> Path:
    return db.data_dir() / "files"


def tmp_dir() -> Path:
    return root() / "tmp"


def blob_path(sha256: str) -> Path:
    return root() / sha256[:2] / sha256


def stage(src: BinaryIO, max_bytes: int) -> Staged:
    """Copy an upload into tmp, hashing as it goes, then fsync. Past `max_bytes` it raises
    TooLarge and leaves nothing behind."""
    tmp_dir().mkdir(parents=True, exist_ok=True)
    path = tmp_dir() / uuid.uuid4().hex
    digest, size = hashlib.sha256(), 0
    try:
        with open(path, "wb") as out:
            while chunk := src.read(CHUNK):
                size += len(chunk)
                if size > max_bytes:
                    raise TooLarge()
                digest.update(chunk)
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return Staged(path, digest.hexdigest(), size)


def publish(staged: Staged) -> None:
    """Rename a staged upload into place. Called inside the transaction that records its blob,
    before COMMIT; replacing an existing copy of the same bytes is harmless and heals a lost one."""
    dest = blob_path(staged.sha256)
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.rename(staged.path, dest)
