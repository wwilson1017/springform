#!/usr/bin/env bash
# Make a private client fork of Springform, ready to hand over.
#
#   scripts/new-fork.sh <name> --org <org> [--dry-run]
#
# Clones upstream into ./<name> with a fetch-only `upstream` remote, starts master at the newest
# upstream release tag (upstream master's commit if there is none yet), seeds FORK.md, creates
# <org>/<name> as a private GitHub repo and pushes, seeds the labels, protects master with the
# required checks, then waits for the first CI run to go green. --dry-run prints each command
# instead of running it. Needs git and gh (logged in, admin on the org).
# SPRINGFORM_UPSTREAM overrides where to fork from.
set -euo pipefail

upstream=${SPRINGFORM_UPSTREAM:-https://github.com/wwilson1017/springform.git}
name=
org=
dry=
while [ $# -gt 0 ]; do
  case $1 in
    --org) org=${2:?--org needs a value}; shift 2 ;;
    --dry-run) dry=1; shift ;;
    -*) echo "unknown flag: $1" >&2; exit 2 ;;
    *) name=$1; shift ;;
  esac
done
if [ -z "$name" ] || [ -z "$org" ]; then
  echo "usage: scripts/new-fork.sh <name> --org <org> [--dry-run]" >&2
  exit 2
fi
repo=$org/$name
dir=$PWD/$name
if [ -z "$dry" ] && [ -e "$dir" ]; then
  echo "$dir already exists" >&2
  exit 1
fi

run() {
  if [ -n "$dry" ]; then
    printf '+'; printf ' %q' "$@"; printf '\n'
  else
    "$@"
  fi
}

# Read-only, so these run in a dry run too.
pin=$(git ls-remote --tags --refs --sort=-v:refname "$upstream" 'v*' | sed -n '1s#.*refs/tags/##p')
note="Pinned to the newest upstream release tag."
if [ -z "$pin" ]; then
  pin=$(git ls-remote "$upstream" refs/heads/master | cut -f1)
  note="No upstream release tag existed yet, so this pins upstream master's commit."
fi
[ -n "$pin" ] || { echo "Can't read $upstream" >&2; exit 1; }
echo "Forking $upstream at $pin into $repo"

fork_md="# $name

A private fork of Springform. Core equals the upstream release pinned below; this fork's own
work lives in backend/apps/, frontend/src/apps/ and docs/apps/ (plus the globs in
fork-allow.txt). CI's Fork scope job, scripts/check-fork-scope.sh, enforces it.

- Take a new upstream release with \`scripts/update-from-upstream.sh vX.Y.Z\`.
- Tag this fork's own releases \`vX.Y.Z-$name.N\` so they never collide with upstream tags.

<!-- $note -->
upstream: $pin
upstream-repo: ${upstream%.git}
"

run git clone --quiet --origin upstream "$upstream" "$dir"
run git -C "$dir" remote set-url --push upstream no_push
run git -C "$dir" checkout --quiet -B master "$pin"
if [ -n "$dry" ]; then
  echo "+ write $dir/FORK.md:"
  printf '%s' "$fork_md" | sed 's/^/    /'
else
  printf '%s' "$fork_md" >"$dir/FORK.md"
fi
run git -C "$dir" add FORK.md
run git -C "$dir" commit --quiet -m "Fork of Springform at $pin"
run gh repo create "$repo" --private --source "$dir" --remote origin --push
run "$dir/scripts/seed-labels.sh" --repo "$repo"

protect=(api --silent -X PUT "repos/$repo/branches/master/protection"
  -F 'required_status_checks[strict]=false')
for check in Backend Frontend "Secret scan" "Fork scope"; do
  protect+=(-f "required_status_checks[contexts][]=$check")
done
protect+=(-F enforce_admins=false -F required_pull_request_reviews=null -F restrictions=null
  -F required_conversation_resolution=true)
# Private repos need a paid GitHub plan for branch protection; say so rather than stop here.
run gh "${protect[@]}" || echo "WARNING: could not protect master on $repo; set it by hand" >&2

# The push above started CI; a fresh fork must pass its own checks before it is handed over.
if [ -n "$dry" ]; then
  echo "+ wait for the CI run on master's head commit, then: gh run watch <run-id> --repo $repo --exit-status"
else
  sha=$(git -C "$dir" rev-parse HEAD)
  run_id=
  for _ in $(seq 30); do
    run_id=$(gh run list --repo "$repo" --workflow ci.yml --commit "$sha" --json databaseId \
      --jq '.[0].databaseId // empty')
    [ -n "$run_id" ] && break
    sleep 5
  done
  [ -n "$run_id" ] || { echo "No CI run started on $repo for $sha" >&2; exit 1; }
  gh run watch "$run_id" --repo "$repo" --exit-status
fi
echo "Fork ready: https://github.com/$repo (local clone: $dir)"
