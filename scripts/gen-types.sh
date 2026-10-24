#!/usr/bin/env bash
# Regenerate frontend/src/core/api/types.gen.ts from the backend's OpenAPI schema. No database
# is needed: building the app registers its routes without running startup. CI regenerates it
# and fails on any diff, so commit the result with the backend change.
#
#   scripts/gen-types.sh                 # from any directory, after `uv sync` and `npm ci`
#
# openapi-typescript comes from the frontend's devDependencies (never fetched ad hoc), so the
# output only changes when the lockfile does.
set -euo pipefail
cd "$(dirname "$0")/.."

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir "$tmp/data"
DATA_DIR="$tmp/data" uv run --frozen python -c '
import json
import backend.main as main
app = main.create_app() if hasattr(main, "create_app") else main.app
print(json.dumps(app.openapi(), indent=2, sort_keys=True))' >"$tmp/openapi.json"

cd frontend
npx --no-install openapi-typescript "$tmp/openapi.json" --output src/core/api/types.gen.ts
