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

1. `gh repo create O/<name> --private`.
2. Clone with `--origin upstream`.
3. `git remote set-url --push upstream no_push` (fetch-only).
4. Add `origin` (the new private repo).
5. Seed `fork-allow.txt` and `FORK.md` (with the pinned upstream tag).
6. Push.
7. `scripts/seed-labels.sh --repo …` (including one `app:<slug>` label per manifest).
8. Branch protection requiring **Backend**, **Frontend**, **Secret scan**, **Fork scope**.
9. Trigger CI once and **wait for green**: a fresh fork must pass its own checks before it is handed over.

Open: what `--dry-run` prints or skips is not stated.

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
| `pyproject.toml`, `uv.lock`, `package.json`, `package-lock.json` | Dependency manifests and lockfiles. |
| Globs listed in `fork-allow.txt` | Branding, README, and other allow-listed paths, each with a reason. |

`backend/apps/**` and `frontend/src/apps/**` are fork-editable in full, built-in apps included. That is intended: a fork may customise CRM or Todos, and upstream updates to them then merge like any other change.

Open: `FORK.md`'s format (how the script reads the tag) and `fork-allow.txt`'s format (one glob per line, reason syntax) are not stated.

## 5. One `ci.yml` for upstream and forks

1. `.github/workflows/ci.yml` runs the **Fork scope** job **only when `FORK.md` exists**.
2. So a fork's `.github/` stays byte-identical to upstream, and there is no fork-specific workflow file.
3. Other jobs: SHA-pinned actions, ruff, an import check, pytest, frontend build / lint / test + types diff, gitleaks (Secret scan), the image test (`testing.md` §6).

## 6. Releases and fork images

1. `vX.Y.Z` tags trigger `release.yml`, which builds and pushes `ghcr.io/${{ github.repository }}:<tag>,latest`.
2. Upstream therefore publishes `ghcr.io/wwilson1017/springform`.
3. **A fork publishes its own (private) image containing its apps**, under its own org, with no workflow change.
4. `deploy/compose.yml` and `railway.json` take the image from `IMAGE=` in `.env` (default: the fork's own).
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
