# Forks, CI and releases

**What this covers:** the fork model (a private repo with a fetch-only `upstream`), `scripts/new-fork.sh`, `scripts/update-from-upstream.sh`, the `scripts/check-fork-scope.sh` rule and its exemptions, `fork-allow.txt`, `FORK.md`, the single `ci.yml` with the conditional Fork scope job, fork images, release tagging, and the changelog "Schema" convention.
**Who reads it:** W8 (scripts, release, CI), whoever builds a client fork, and anyone changing core paths (the scope check is why core must not be edited in a fork).

## 1. The fork model

1. A client gets a **private repo** created by `new-fork.sh`, with the public Springform repo as a **fetch-only `upstream`** remote.
2. The client's apps live only in `backend/apps/<slug>/`, `frontend/src/apps/<slug>/` and `docs/apps/` (fork-owned).
3. Platform updates arrive with `git merge` of an upstream tag (`update-from-upstream.sh`). Core is never edited in the fork.
4. CI in the fork fails any change to a core path that does not match the pinned upstream tag.

Why not a GitHub "Fork" button fork: GitHub makes a fork of a public repository public, and a client repo must be private. (GitHub platform behaviour; the plan states the decision, not this reason.)

## 2. `scripts/new-fork.sh`

```
scripts/new-fork.sh <name> --org O [--dry-run]
```

1. Clone upstream with `--origin upstream` (`SPRINGFORM_UPSTREAM` overrides the source).
2. `git remote set-url --push upstream no_push` (fetch-only).
3. Start `master` at the newest upstream `v*` tag, or at upstream master's commit when there is no tag yet.
4. Write `FORK.md` with `upstream: <pin>` and `upstream-repo: <url>` lines. `fork-allow.txt` comes from upstream, where it already exists.
5. `gh repo create O/<name> --private --source … --remote origin --push` creates the repo, adds `origin` and pushes in one step.
6. `scripts/seed-labels.sh --repo …` (including one `app:<slug>` label per manifest).
7. Branch protection on `master` requiring **Backend**, **Frontend**, **Secret scan**, **Fork scope**. A private repo needs a paid GitHub plan for it; the script says so and carries on.
8. Wait for the first CI run on `master` to go **green**: a fresh fork must pass its own checks before it is handed over.

`--dry-run` prints each mutating command prefixed with `+`, including the `FORK.md` text and the CI wait, and runs only the read-only `git ls-remote` that finds the pin.

## 3. `scripts/update-from-upstream.sh`

```
scripts/update-from-upstream.sh vX.Y.Z
```

1. Fetch upstream.
2. Merge the tag on a branch.
3. Bump the tag in `FORK.md`.
4. Regenerate types (`scripts/gen-types.sh`).
5. Run the suite.
6. Open a PR.

An upstream-update PR passes the scope check because it moves the tag in the same PR.

## 4. `scripts/check-fork-scope.sh`

**The rule is "core equals the pinned tag".**

1. Read the tag from `FORK.md`.
2. `git diff --quiet <tag> HEAD -- <core paths>` must be empty.
3. On failure, print the list of paths and: "move into an app, send upstream, or allow-list with a reason".

**Core paths** = everything **except**:

| Exempt | Why |
|---|---|
| `backend/apps/` | Fork-owned apps. |
| `frontend/src/apps/` | Fork-owned app screens. |
| `docs/apps/` | Fork-owned app docs. |
| `FORK.md`, `fork-allow.txt` | Fork metadata. |
| `frontend/src/core/api/types.gen.ts` | Generated (includes the fork's app routes). |
| `pyproject.toml`, `uv.lock`, `frontend/package.json`, `frontend/package-lock.json` | Dependency manifests and lockfiles. |
| Globs listed in `fork-allow.txt` | Branding, README, and other allow-listed paths, each with a reason. |

`backend/apps/**` and `frontend/src/apps/**` are fork-editable in full, built-in apps included. That is intended: a fork may customise CRM or Todos, and upstream updates to them then merge like any other change.

The script reads the first `upstream: <tag-or-sha>` line of `FORK.md`, fetching that tag from `upstream-repo: <url>` when it is not present locally. `fork-allow.txt` holds one git glob per line (`**` crosses directories); `#` starts a comment, and each glob gets a comment line above it saying why. Exit codes: 0 in scope, 1 core changed, 2 `FORK.md` or the pinned tag missing.

## 5. One `ci.yml` for upstream and forks

1. `.github/workflows/ci.yml` runs the **Fork scope** job on every push and PR. It first self-tests the check (`scripts/test-fork-scope.sh`), then runs `scripts/check-fork-scope.sh`, which passes at once when there is no `FORK.md` (upstream).
2. So a fork's `.github/` stays byte-identical to upstream, and there is no fork-specific workflow file.
3. Other jobs: SHA-pinned actions, ruff, an import check, pytest, frontend build / lint / test + types diff, gitleaks (Secret scan), the image test (`testing.md` §6).

## 6. Releases and fork images

1. Any `v*` tag triggers `release.yml`, a fork's tags included. After CI passes on the tag, it builds the amd64 image and pushes `ghcr.io/<repository, lowercased>:<tag>`, plus `:latest` for a tag without a hyphen (`deploy.md` §9).
2. Upstream therefore publishes `ghcr.io/wwilson1017/springform`.
3. **A fork publishes its own (private) image containing its apps**, under its own org, with no workflow change.
4. `deploy/compose.yml` takes the image from `IMAGE=` in `.env`, default the upstream image, so a fork's install sets `IMAGE` (`setup.sh` accepts `IMAGE=`). `railway.json` builds the repo's own `Dockerfile` and never reads `IMAGE`.
5. `springform-version` is read by `/api/health`.

## 7. `CHANGELOG.md`

1. keep-a-changelog format.
2. A **"Schema"** section records schema changes, and marks a column core stops using as **deprecated**. Deprecated columns stay, nullable and unused, until the next major (`database-and-transactions.md` §5).
3. A major release notes its **baseline** migration and the deprecated columns it drops; apps crossing it re-baseline and raise `requires_core`.

## 8. Labels and requests

`scripts/seed-labels.sh` (from CakeCRM) seeds the repo's labels, including `app:<slug>` per manifest. The Requests page files GitHub issues labelled `app:<slug>` (`frontend-shell.md`). `docs/AUTO_ISSUES.md` is copied from CakeCRM minus its cake_os mirror section.

## 9. Proving it

- **Step 1b:** `new-fork.sh` into a throwaway repo, CI green; the scope check fails on a core edit and passes on an app edit.
- **Step 5:** tag `v0.1.0`; `new-fork.sh` into a throwaway org repo; `update-from-upstream.sh v0.1.1` after a trivial core change, with one PR touching core (must fail) and one touching an app (must pass).
- **First client fork:** created with `new-fork.sh` against `v0.1.0`; its first `update-from-upstream.sh` run is the first live test of the fork model.

## Tests that pin this

- Live: `new-fork.sh` + `update-from-upstream.sh` on a throwaway repo with the two-PR scope test.
- Step 1b: scope check fails on a core edit and passes on an app edit.
- `gen-types` diff clean (types regenerate in the update PR).

## Source

Build plan: §13 (forks, scope check, releases, one `ci.yml`), §12 (generated types exempt), §14 (`seed-labels.sh`, `AUTO_ISSUES.md`, `ci.yml` structure), Decisions (Forks), SQLite rules (schema compatibility, "Schema" changelog), Steps 1b, 5, 6.
