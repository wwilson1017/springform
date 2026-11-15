#!/usr/bin/env bash
# Check the real scaffold, then restore the worktree even if a check fails.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"

backend="$root/backend/apps/scaffoldcheck"
frontend="$root/frontend/src/apps/scaffoldcheck"
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

scripts/new-app.sh scaffoldcheck "Scaffold Check"
for f in api.py settings.py; do
  [ ! -e "$backend/$f" ] || { echo "new-app.sh wrote $f, which a new app does not need" >&2; exit 1; }
done
uv run python - <<'PY'
import json
from pathlib import Path

manifest = json.loads(Path("backend/apps/scaffoldcheck/app.json").read_text())
assert manifest["icon"] == "grid", manifest["icon"]  # in APP_ICONS (frontend/src/shared/icons.tsx)
assert manifest["publishes"] == [], manifest["publishes"]
PY

uv run ruff check backend/apps/scaffoldcheck
uv run pytest -q backend/tests/test_app_contract.py backend/apps/scaffoldcheck
DATA_DIR="$tmp/data" uv run python - <<'PY'
from backend.main import create_app

paths = create_app().openapi()["paths"]
base = "/api/scaffoldcheck/items"
for path, method in ((base, "get"), (base, "post"), (base + "/{item_id}", "get")):
    schema = paths[path][method]["responses"]["200"]["content"]["application/json"]["schema"]
    if path == base and method == "get":
        assert schema["type"] == "array", schema
        schema = schema["items"]
    assert schema["$ref"].endswith("/ScaffoldcheckItem"), schema
PY

scripts/gen-types.sh
cd frontend
npm run typecheck
npx vitest run src/core/apps/contract.test.ts src/bootSplit.test.ts
echo "new-app.sh scaffold self-test passed"
