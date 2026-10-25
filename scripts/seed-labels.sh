#!/usr/bin/env bash
# Create or normalize the GitHub labels the auto-issues loop uses (docs/AUTO_ISSUES.md), plus
# one `app:<slug>` label per backend/apps/*/app.json. Idempotent: an existing label gets the
# canonical colour and description. Re-run after adding an app.
#
#   scripts/seed-labels.sh                  # the current repo (gh infers it)
#   scripts/seed-labels.sh --repo owner/n   # an explicit repo
#
# Needs gh, logged in with repo scope.
set -euo pipefail
cd "$(dirname "$0")/.."

repo=
while [ $# -gt 0 ]; do
  case $1 in
    --repo) repo=${2:?--repo needs owner/name}; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
# From origin, not gh's default: in a fork clone gh may resolve to the public upstream.
[ -n "$repo" ] || repo=$(git remote get-url origin | sed -E 's#^(https://github\.com/|git@github\.com:)##; s#\.git$##')

# name|colour|description (green = go, yellow = in flight, orange = parked, red = stop)
labels=(
  "ready-to-ship|0e8a16|Green, mergeable, threads resolved: the ship lane merges it"
  "needs-settle|fbca04|Red or unresolved threads: the settle lane picks it up"
  "no-auto-merge|b60205|Merge needs a production write or a missing secret (see the PR body)"
  "stale|cfd3d7|Red or conflicting with no push for 14 days; closed at 21"
  "awaiting-answer|d93f0b|Parked: waiting on a human answer"
  "bug|d73a4a|Something is broken"
  "enhancement|a2eeef|A new capability or improvement"
)
for manifest in backend/apps/*/app.json; do
  [ -e "$manifest" ] || continue
  slug=$(basename "$(dirname "$manifest")")
  labels+=("app:$slug|1d76db|Concerns the $slug app")
done

echo "Seeding labels on $repo"
for entry in "${labels[@]}"; do
  IFS='|' read -r name colour description <<<"$entry"
  gh label create "$name" --force --repo "$repo" --color "$colour" --description "$description" >/dev/null
  echo "  $name"
done
echo "Done: ${#labels[@]} labels."
