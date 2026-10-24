#!/usr/bin/env bash
# In a fork: take upstream release vX.Y.Z on a branch and open a PR for it.
#
#   scripts/update-from-upstream.sh v0.2.0
#
# Fetches the tag, merges it on branch upstream-vX.Y.Z (from origin/master), moves the pin in
# FORK.md, regenerates the API types, runs the backend and frontend suites and the fork scope
# check, pushes, and opens the PR. A merge conflict stops it: resolve and commit, then finish the
# remaining steps by hand.
set -euo pipefail
tag=${1:?usage: scripts/update-from-upstream.sh vX.Y.Z}
cd "$(git rev-parse --show-toplevel)"
if [ ! -f FORK.md ]; then
  echo "No FORK.md: run this in a fork, not in upstream." >&2
  exit 2
fi
if [ -n "$(git status --porcelain)" ]; then
  echo "Commit or stash your changes first." >&2
  exit 2
fi

git fetch --quiet origin
git fetch --quiet --no-tags upstream tag "$tag"
branch=upstream-$tag
git switch --quiet -c "$branch" origin/master
if ! git merge --quiet --no-edit -m "Merge upstream $tag" "$tag"; then
  echo "Merge conflicts. Resolve and commit them, then: bump 'upstream:' in FORK.md," \
    "run scripts/gen-types.sh and the suites, push, and open the PR." >&2
  exit 1
fi
sed -i.bak "s/^upstream:.*/upstream: $tag/" FORK.md && rm FORK.md.bak

uv sync --frozen
scripts/gen-types.sh
uv run ruff check .
uv run pytest -q
(cd frontend && npm ci && npm run lint && npm run typecheck && npm test && npm run build)
git add FORK.md frontend/src/core/api/types.gen.ts
git commit --quiet -m "Update to upstream $tag"
scripts/check-fork-scope.sh

upstream_url=$(sed -n 's/^upstream-repo:[[:space:]]*//p' FORK.md)
git push --quiet -u origin "$branch"
gh pr create --base master --head "$branch" --title "Update to upstream Springform $tag" --body \
"**In plain English:** this brings the fork up to Springform $tag. Core files now match that
release exactly; this fork's own apps are untouched.

- Merges upstream tag \`$tag\` and moves the pin in \`FORK.md\`
- Regenerates \`frontend/src/core/api/types.gen.ts\`
- What changed upstream: $upstream_url/blob/$tag/CHANGELOG.md

Test plan: backend and frontend suites and the fork scope check passed locally; CI reruns them."
