#!/usr/bin/env bash
# In a fork, fail when core differs from the upstream release pinned in FORK.md.
#
#   scripts/check-fork-scope.sh          # CI's "Fork scope" job runs exactly this
#
# A fork owns backend/apps/, frontend/src/apps/, docs/apps/, FORK.md, fork-allow.txt, the
# generated API types, the dependency manifests and lockfiles, and the globs in fork-allow.txt.
# Every other path must equal the pinned upstream tag. An upstream update moves the pin in the
# same change, so it passes; a core edit without moving the pin fails. Upstream has no FORK.md.
# Exit codes: 0 in scope, 1 core changed, 2 FORK.md or the pinned tag is missing.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

if [ ! -f FORK.md ]; then
  echo "No FORK.md: this is upstream Springform, nothing to check."
  exit 0
fi
pin=$(sed -n 's/^upstream:[[:space:]]*\([^[:space:]]*\).*/\1/p' FORK.md | sed -n 1p)
repo=$(sed -n 's/^upstream-repo:[[:space:]]*\([^[:space:]]*\).*/\1/p' FORK.md | sed -n 1p)
if [ -z "$pin" ]; then
  echo "FORK.md has no 'upstream: vX.Y.Z' line." >&2
  exit 2
fi
# CI clones only the fork, so fetch the pinned tag from upstream when it isn't here.
if ! git rev-parse -q --verify "$pin^{commit}" >/dev/null && [ -n "$repo" ]; then
  git fetch -q --no-tags "$repo" "refs/tags/$pin:refs/tags/$pin" || true
fi
if ! git rev-parse -q --verify "$pin^{commit}" >/dev/null; then
  echo "Pinned upstream $pin is not in this clone. Try: git fetch upstream --tags" >&2
  exit 2
fi

spec=(.)
for owned in backend/apps frontend/src/apps docs/apps FORK.md fork-allow.txt \
  frontend/src/core/api/types.gen.ts pyproject.toml uv.lock \
  frontend/package.json frontend/package-lock.json; do
  spec+=(":(exclude)$owned")
done
if [ -f fork-allow.txt ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    glob=${line%%#*}
    glob=${glob//[[:space:]]/}
    if [ -n "$glob" ]; then spec+=(":(exclude,glob)$glob"); fi
  done <fork-allow.txt
fi

if git diff --quiet --no-renames "$pin" HEAD -- "${spec[@]}"; then
  echo "Fork scope OK: core equals upstream $pin."
  exit 0
fi
echo "These core paths differ from upstream $pin:"
git diff --name-only --no-renames "$pin" HEAD -- "${spec[@]}" | sed 's/^/  /'
echo "Move the change into an app, send it upstream, or allow-list it in fork-allow.txt with a reason."
exit 1
