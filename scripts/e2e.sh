#!/usr/bin/env bash
# Browser smoke: build the SPA, boot two PREVIEW_MODE backends that serve it on fresh data dirs
# with a frozen clock (one with the FakeProvider, one with no AI key for the zero-key card), run
# Playwright, stop both by PID and exit with Playwright's status. Arguments go to
# `playwright test` (e.g. `scripts/e2e.sh --project=desktop e2e/todos.spec.ts`).
#
# Env: E2E_PORT (8160; the keyless backend takes the next port), E2E_FREEZE_CLOCK (the server's
# frozen instant), E2E_ARTIFACTS (where the HTML report, traces and server logs go; a temp dir).
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
port=${E2E_PORT:-8160}
zero_port=$((port + 1))
export E2E_FREEZE_CLOCK=${E2E_FREEZE_CLOCK:-2026-11-02T15:00:00Z}
export E2E_ARTIFACTS=${E2E_ARTIFACTS:-$(mktemp -d)}
mkdir -p "$E2E_ARTIFACTS"
data=$(mktemp -d)
pids=()

stop() {
  for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
  rm -rf "$data"
}
trap stop EXIT

cd "$root/frontend"
[ -d node_modules ] || npm ci
npm run build

# boot <port> <name> [VAR=value ...]: one backend on its own data dir, logging to the artifacts.
boot() {
  local p=$1 name=$2
  shift 2
  if curl -sf "http://127.0.0.1:$p/up" >/dev/null; then
    echo "port $p already answers /up; stop that server or set E2E_PORT" >&2
    return 1
  fi
  mkdir -p "$data/$name"
  (cd "$root" && exec env PREVIEW_MODE=1 SPRINGFORM_FREEZE_CLOCK="$E2E_FREEZE_CLOCK" DATA_DIR="$data/$name" "$@" \
    uv run uvicorn backend.main:app --host 127.0.0.1 --port "$p") >"$E2E_ARTIFACTS/$name.log" 2>&1 &
  pids+=($!)
  for _ in $(seq 120); do
    curl -sf "http://127.0.0.1:$p/up" >/dev/null && return 0
    sleep 0.5
  done
  echo "backend $name did not answer /up on port $p; its log:" >&2
  tail -40 "$E2E_ARTIFACTS/$name.log" >&2
  return 1
}
boot "$port" main AGENT_FAKE_PROVIDER=1
boot "$zero_port" zero-key

status=0
E2E_BASE_URL="http://127.0.0.1:$port" E2E_ZERO_KEY_URL="http://127.0.0.1:$zero_port" npx playwright test "$@" || status=$?
echo "Playwright report and traces: $E2E_ARTIFACTS"
exit "$status"
