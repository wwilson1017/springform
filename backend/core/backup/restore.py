"""Restore a recovery set into an empty data directory.

    python -m backend.core.backup.restore <manifest> <target_data_dir>
        [--files-from <source_data_dir>] [--key-file <path>] [--allow-missing-blobs]

Everything is checked before anything is written: the manifest, the snapshot's sha256, every
listed blob (present, with the right sha256), that the target is empty, and that the key the
restored install will use has the manifest's fingerprint. That key is ENCRYPTION_KEY when it is
set (it wins at boot), and --key-file too when given. A wrong key fails loudly instead of
booting an install that cannot read its stored credentials.

Blobs are read from `<files-from>/files/`; without --files-from, from the data directory that
holds the manifest's `backups/` folder. Exit codes: 0 restored, 1 refused or failed, 2 usage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

from packaging.version import InvalidVersion, Version

from backend.core import VERSION
from backend.core.backup.service import MANIFEST_VERSION, sha256_file
from backend.core.db import DB_FILENAME


class RestoreError(Exception):
    """The set cannot be restored as asked; the message says why, for a human."""


def fingerprint(key: str) -> str:
    """The formula of secrets.key_fingerprint(), for a key that is not this process's."""
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def restore(
    manifest_path: str | Path,
    target_dir: str | Path,
    *,
    files_from: str | Path | None = None,
    key_file: str | Path | None = None,
    allow_missing_blobs: bool = False,
) -> dict:
    """Verify the set, then copy it into `target_dir`. Raises RestoreError before writing
    anything when a check fails. Returns {target, snapshot, blobs, missing_blobs, key_file, warnings}."""
    manifest_path, target = Path(manifest_path), Path(target_dir)
    try:
        m = json.loads(manifest_path.read_text(encoding="utf-8"))
        filename, digest = m["snapshot"]["filename"], m["snapshot"]["sha256"]
        blobs, expected = list(m["blobs"]), m["key_fingerprint"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise RestoreError(f"cannot read the manifest {manifest_path}: {e!r}") from None
    if m.get("version") != MANIFEST_VERSION:
        raise RestoreError(f"manifest version {m.get('version')!r} is not supported (this release reads {MANIFEST_VERSION})")
    warnings = []
    try:
        if Version(m.get("springform_version", "0")) > Version(VERSION):
            warnings.append(f"the backup was taken by Springform {m['springform_version']}, newer than this {VERSION}")
    except InvalidVersion:
        warnings.append(f"the manifest's springform_version {m.get('springform_version')!r} is not a version")

    snapshot = manifest_path.parent / filename
    if Path(filename).name != filename or not snapshot.is_file():
        raise RestoreError(f"the snapshot {snapshot} is missing")
    if sha256_file(snapshot) != digest:
        raise RestoreError(f"the snapshot {snapshot} is damaged: its sha256 does not match the manifest")

    keys = [("ENCRYPTION_KEY", os.environ["ENCRYPTION_KEY"])] if os.environ.get("ENCRYPTION_KEY") else []
    if key_file:
        try:
            keys.append((str(key_file), Path(key_file).read_text(encoding="utf-8").strip()))
        except OSError as e:
            raise RestoreError(f"cannot read the key file: {e}") from None
    if not keys:
        raise RestoreError(
            "no key: pass --key-file <path> (the key the Backups page showed once, or the old data "
            "directory's .encryption-key) or set ENCRYPTION_KEY"
        )
    for source, key in keys:
        if fingerprint(key) != expected:
            raise RestoreError(
                f"wrong key: {source} has fingerprint {fingerprint(key)}, but this backup was taken with "
                f"key {expected}. Use the key that was in use when the backup was taken."
            )

    files = (Path(files_from) if files_from else manifest_path.resolve().parent.parent) / "files"
    missing = [sha for sha in blobs if not ((p := files / sha[:2] / sha).is_file() and sha256_file(p) == sha)]
    if missing and not allow_missing_blobs:
        raise RestoreError(
            f"{len(missing)} of {len(blobs)} files are missing or damaged under {files} (first: {missing[0]}). "
            "Point --files-from at the data directory holding files/, or pass --allow-missing-blobs."
        )
    if missing:
        warnings.append(f"{len(missing)} files were missing or damaged and were not restored")

    if target.exists() and any(p.name != "lost+found" for p in target.iterdir()):
        raise RestoreError(f"the target {target} is not empty; restore only into an empty data directory")

    target.mkdir(parents=True, exist_ok=True)
    for sha in blobs:
        if sha not in missing:
            dest = target / "files" / sha[:2] / sha
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(files / sha[:2] / sha, dest)
    if key_file:
        dest = target / ".encryption-key"
        shutil.copyfile(key_file, dest)
        dest.chmod(0o600)
    tmp = target / f"{DB_FILENAME}.tmp"
    shutil.copyfile(snapshot, tmp)
    os.replace(tmp, target / DB_FILENAME)  # last, so a half-copied database never has the real name
    return {
        "target": str(target), "snapshot": filename, "blobs": len(blobs) - len(missing),
        "missing_blobs": missing, "key_file": bool(key_file), "warnings": warnings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="restore", description="Restore a Springform backup set into an empty data directory."
    )
    parser.add_argument("manifest", help="<data>/backups/<stamp>.manifest.json")
    parser.add_argument("target", help="the empty data directory to restore into")
    parser.add_argument("--files-from", help="the data directory holding files/ (default: the manifest's)")
    parser.add_argument("--key-file", help="the encryption key the backup was taken with")
    parser.add_argument("--allow-missing-blobs", action="store_true", help="restore even if some files are missing")
    args = parser.parse_args(argv)
    try:
        result = restore(
            args.manifest, args.target, files_from=args.files_from, key_file=args.key_file,
            allow_missing_blobs=args.allow_missing_blobs,
        )
    except (RestoreError, OSError) as e:
        print(f"restore failed: {e}", file=sys.stderr)
        return 1
    for w in result["warnings"]:
        print(f"warning: {w}", file=sys.stderr)
    key = ", and the encryption key" if result["key_file"] else ""
    print(f"Restored {result['snapshot']}, {result['blobs']} files{key} into {result['target']}.")
    print(f"Start Springform with DATA_DIR={result['target']}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
