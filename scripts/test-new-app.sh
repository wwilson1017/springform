#!/usr/bin/env bash
# Check the real scaffold, then restore the worktree even if a check fails.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"

# A random suffix with no underscore, so a fork's own apps cannot collide with the throwaway one.
export SLUG="scaffoldcheck$RANDOM"
backend="$root/backend/apps/$SLUG"
frontend="$root/frontend/src/apps/$SLUG"
for app in "$backend" "$frontend"; do
  if [ -e "$app" ] || [ -L "$app" ]; then
    echo "Refusing to overwrite existing app: $app" >&2
    exit 1
  fi
done

tmp=$(mktemp -d)
types="$root/frontend/src/core/api/types.gen.ts"
cleanup() {
  local status=$?
  if [ -f "$tmp/types.gen.ts" ]; then
    cp -p "$tmp/types.gen.ts" "$types" || status=1
  fi
  rm -rf "$backend" "$frontend" "$tmp" || status=1
  exit "$status"
}
trap cleanup EXIT
cp -p "$types" "$tmp/types.gen.ts"

scripts/new-app.sh "$SLUG" "Scaffold Check"
for f in api.py settings.py; do
  [ ! -e "$backend/$f" ] || { echo "new-app.sh wrote $f, which a new app does not need" >&2; exit 1; }
done
uv run python - <<'PY'
import json
import os
from pathlib import Path

manifest = json.loads(Path(f"backend/apps/{os.environ['SLUG']}/app.json").read_text())
assert manifest["icon"] == "grid", manifest["icon"]  # in APP_ICONS (frontend/src/shared/icons.tsx)
assert manifest["publishes"] == [], manifest["publishes"]
PY

uv run ruff check "$backend"
uv run pytest -q backend/tests/test_app_contract.py "$backend"
DATA_DIR="$tmp/data" uv run python - <<'PY'
import os

from backend.main import create_app

paths = create_app().openapi()["paths"]
slug = os.environ["SLUG"]
base = f"/api/{slug}/items"
for path, method in ((base, "get"), (base, "post"), (base + "/{item_id}", "get")):
    schema = paths[path][method]["responses"]["200"]["content"]["application/json"]["schema"]
    if path == base and method == "get":
        assert schema["type"] == "array", schema
        schema = schema["items"]
    assert schema["$ref"].endswith(f"/{slug.capitalize()}Item"), schema
PY

scripts/gen-types.sh
cd frontend
npm run typecheck
npx vitest run src/core/apps/contract.test.ts src/bootSplit.test.ts
echo "new-app.sh scaffold self-test passed"
