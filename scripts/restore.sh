#!/bin/sh
# Restore a backup set into an empty data directory; every check runs before anything is written.
#   scripts/restore.sh <manifest> <target_data_dir> [--files-from <dir>] [--key-file <path>] [--allow-missing-blobs]
# Details and exit codes: backend/core/backup/restore.py (or pass --help).
set -eu
root=$(cd "$(dirname "$0")/.." && pwd)
PYTHONPATH="$root${PYTHONPATH:+:$PYTHONPATH}" exec uv run --project "$root" python -m backend.core.backup.restore "$@"
