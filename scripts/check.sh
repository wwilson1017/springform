#!/usr/bin/env bash
# Run the CI checks locally (the Backend and Frontend jobs in .github/workflows/ci.yml).
# Agents run this before opening a PR. Needs Node 22, as CI uses (test-railway-config.sh strips TS types).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

uv run --locked ruff check .
uv run --locked ruff format --check backend scripts run.py conftest.py
uv run --locked pyright
DATA_DIR="$(mktemp -d)" uv run --locked python -c "from backend.main import create_app; create_app()"
uv run --locked pytest -q
scripts/gen-types.sh
git diff --exit-code -- frontend/src/core/api/types.gen.ts
scripts/test-railway-config.sh
scripts/test-new-app.sh
cd frontend
npm run lint
npm run format:check
npm run typecheck
npm test
npm run build -- --outDir "$(mktemp -d)"
