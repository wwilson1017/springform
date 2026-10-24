#!/usr/bin/env bash
# Self-test for scripts/check-fork-scope.sh: builds a throwaway upstream and fork in a temp dir
# and runs the check on every case it must pass and every case it must fail. CI runs it in the
# Fork scope job.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
check=$here/check-fork-scope.sh
root=$(mktemp -d)
trap 'rm -rf "$root"' EXIT
export GIT_AUTHOR_NAME=test GIT_AUTHOR_EMAIL=test@example.invalid
export GIT_COMMITTER_NAME=test GIT_COMMITTER_EMAIL=test@example.invalid GIT_CONFIG_GLOBAL=/dev/null
failures=0

# expect <dir> <want exit> <description> [path the output must name]
expect() {
  local dir=$1 want=$2 what=$3 named=${4:-} got=0 out
  out=$(cd "$dir" && "$check" 2>&1) || got=$?
  if [ "$got" != "$want" ] || { [ -n "$named" ] && ! grep -qxF "  $named" <<<"$out"; }; then
    echo "FAIL  $what (exit $got, want $want${named:+, naming $named})"
    printf '      %s\n' "${out//$'\n'/$'\n'      }"
    failures=$((failures + 1))
  else
    echo "ok    $what"
  fi
}
put() { mkdir -p "$(dirname "$1")" && echo "${2:-changed}" >"$1"; }
# start a case: the fork's master as it was right after forking
fresh() { git -C "$root/fork" checkout -q -B case base; }
commit() { git -C "$root/fork" add -A && git -C "$root/fork" commit -qm case; }

cd "$root" && git init -q -b master up && cd up
for f in backend/core/db.py backend/apps/example/router.py frontend/src/core/api/types.gen.ts \
  frontend/src/apps/example/index.tsx frontend/package.json frontend/package-lock.json \
  frontend/public/branding/logo.svg docs/agents/platform.md pyproject.toml uv.lock README.md \
  .github/workflows/ci.yml; do
  put "$f" original
done
cp "$here/../fork-allow.txt" .
git add -A && git commit -qm upstream && git tag v0.0.1

expect "$root/up" 0 "upstream (no FORK.md) passes"

git clone -q --origin upstream "$root/up" "$root/fork"
cd "$root/fork"
printf 'upstream: v0.0.1\nupstream-repo: %s\n' "$root/up" >FORK.md
git add FORK.md && git commit -qm fork && git branch base
expect "$root/fork" 0 "fresh fork passes"

fresh; put backend/core/db.py; commit
expect "$root/fork" 1 "core edit fails" backend/core/db.py
fresh; put backend/core/new.py; commit
expect "$root/fork" 1 "new core file fails" backend/core/new.py
fresh; git rm -q backend/core/db.py; commit
expect "$root/fork" 1 "deleted core file fails" backend/core/db.py
fresh; git mv backend/core/db.py backend/apps/example/db.py; commit
expect "$root/fork" 1 "core file moved into an app fails" backend/core/db.py
fresh; put .github/workflows/ci.yml; commit
expect "$root/fork" 1 "workflow edit fails" .github/workflows/ci.yml

fresh; put backend/apps/example/router.py; put backend/apps/crm2/app.json
put frontend/src/apps/example/index.tsx; put docs/apps/guide.md; commit
expect "$root/fork" 0 "app edits pass"
fresh; put README.md; put frontend/public/branding/dark/logo.svg; commit
expect "$root/fork" 0 "allow-listed paths pass"
fresh; put uv.lock; put pyproject.toml; put frontend/package.json; put frontend/package-lock.json
commit
expect "$root/fork" 0 "manifests and lockfiles pass"
fresh; put frontend/src/core/api/types.gen.ts; commit
expect "$root/fork" 0 "generated types pass"
fresh; put docs/README.md; commit
expect "$root/fork" 1 "README.md glob does not match nested READMEs" docs/README.md
fresh; put frontend/public/branding-old/logo.svg; commit
expect "$root/fork" 1 "branding glob does not match a sibling folder" frontend/public/branding-old/logo.svg
fresh; put backend/appsx/router.py; commit
expect "$root/fork" 1 "app folder prefix does not match backend/appsx" backend/appsx/router.py
fresh; printf '# why: fork docs\ndocs/agents/**\n' >>fork-allow.txt; put docs/agents/platform.md; commit
expect "$root/fork" 0 "a glob the fork adds to fork-allow.txt passes"
fresh; printf 'frontend/public/*.ico\n' >>fork-allow.txt; put frontend/public/favicon.ico; commit
expect "$root/fork" 0 "a single * matches within its folder"
fresh; printf 'frontend/public/*.ico\n' >>fork-allow.txt; put frontend/public/icons/app.ico; commit
expect "$root/fork" 1 "a single * does not cross folders" frontend/public/icons/app.ico

# An upstream release that changes core: merging it without moving the pin fails; merging it and
# moving the pin in the same commit passes.
put "$root/up/backend/core/db.py" "release 2"
git -C "$root/up" commit -qam "release 2" && git -C "$root/up" tag v0.0.2
git fetch -q upstream --tags
fresh; git merge -q --no-edit v0.0.2
expect "$root/fork" 1 "upstream merge without moving the pin fails" backend/core/db.py
fresh; git merge -q --no-commit v0.0.2 >/dev/null 2>&1; sed -i.bak 's/^upstream:.*/upstream: v0.0.2/' FORK.md
rm FORK.md.bak; git add FORK.md; git commit -qm "Update to upstream v0.0.2"
expect "$root/fork" 0 "upstream merge that moves the pin in the same commit passes"
fresh; put backend/core/db.py "release 2"; sed -i.bak 's/^upstream:.*/upstream: v0.0.2/' FORK.md
rm FORK.md.bak; put backend/core/db.py "release 2 plus a fork patch"; commit
expect "$root/fork" 1 "moving the pin does not excuse a core edit beyond the release" backend/core/db.py

# CI clones only the fork: the pinned tag is fetched from upstream-repo.
fresh; git checkout -q master
git clone -q --no-tags "$root/fork" "$root/ci"
expect "$root/ci" 0 "missing tag is fetched from upstream-repo"
fresh; printf 'no pin here\n' >FORK.md; commit
expect "$root/fork" 2 "FORK.md without an upstream line is an error"
fresh; sed -i.bak 's/^upstream:.*/upstream: v9.9.9/' FORK.md; rm FORK.md.bak; commit
expect "$root/fork" 2 "a pin that exists nowhere is an error"

if [ "$failures" -gt 0 ]; then
  echo "$failures case(s) failed"
  exit 1
fi
echo "All fork scope cases behave."
