# Forks, CI and releases

**What this covers:** the fork model, brand colours and logo (`frontend/public/branding/`) (a private repo with a fetch-only `upstream`), `scripts/new-fork.sh`, `scripts/update-from-upstream.sh`, the `scripts/check-fork-scope.sh` rule and its exemptions, `fork-allow.txt`, `FORK.md`, the single `ci.yml` with the conditional Fork scope job, fork images, release tagging, and the changelog "Schema" convention.
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
6. `scripts/seed-labels.sh --repo …` (including one `app:<slug>` label per manifest), then `gh repo set-default` to the fork in the clone, because `gh` would otherwise resolve to the public upstream (the `upstream` remote) for `gh pr create` and the no-argument `seed-labels.sh`.
7. Branch protection on `master` requiring **Backend**, **Frontend**, **Secret scan**, **Fork scope**. A private repo needs a paid GitHub plan for it; the script says so and carries on.
8. Wait for the first CI run on `master` to go **green**: a fresh fork must pass its own checks before it is handed over. (The workflow registers a few seconds after the push, so the lookup retries for up to 150 s.)

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
6. Open a PR labelled `no-auto-merge`, whose body asks for a merge commit.

An upstream-update PR passes the scope check because it moves the tag in the same PR.

**Merge an update PR with a merge commit, never a squash.** A squash drops upstream's commits from the fork's history, so the next `git merge <tag>` starts from the old merge base and conflicts on every line upstream changed twice, `springform-version` first (a squashed fork reproduced this on the next release; a merge-commit fork merged cleanly). The label keeps an automatic ship lane, which squashes, off the PR; a person merges it with "Create a merge commit".

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
3. Other jobs: SHA-pinned actions, ruff check and ruff format, pyright, an import check, pytest, frontend build / lint / Prettier / test + types diff, gitleaks (Secret scan), the image test (`testing.md` §6).
4. pyright relaxes the Optional-access rules only for the test folders listed in `executionEnvironments` in `pyproject.toml` (fork-editable). When a fork's app tests fail pyright on those rules, add a `backend/apps/<slug>/tests` entry copied from the `example` one.
5. `.github/dependabot.yml` is core too, so a fork carries it unchanged and Dependabot opens dependency PRs in the fork. Close them: upstream's dependency bumps arrive with each release. `.github/CODEOWNERS` is carried the same way; it names the upstream owner, and `new-fork.sh` requires no reviews, so it has no effect in a fork.

## 6. Releases and fork images

1. Any `v*` tag triggers `release.yml`, a fork's tags included. After CI passes on the tag and the tag matches `springform-version`, it builds the amd64 image and pushes `ghcr.io/<repository, lowercased>:<tag>`. Upstream tags are `v<springform-version>` and move `:latest` unless they carry a hyphen (a pre-release). **Fork tags are `v<springform-version>-<fork>.N`** (`v0.1.1-acme.3`: core is pinned, so the fork cannot bump the version file) and every fork tag moves the fork image's `:latest` (`deploy.md` §9).
2. Upstream therefore publishes `ghcr.io/wwilson1017/springform`.
3. **A fork publishes its own (private) image containing its apps**, under its own org, with no workflow change.
4. `deploy/compose.yml` takes the image from `IMAGE=` in `.env`, default the upstream image, so a fork's install sets `IMAGE` (`setup.sh` accepts `IMAGE=`). `.railway/railway.ts` builds the repo's own `Dockerfile` and never reads `IMAGE`. It is core and carried unchanged; `SPRINGFORM_SERVICE` selects the fork's own service when applying `.railway/railway.ts` (`deploy.md`).
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

## 10. Brand colours and logo

A fork brands its install from `frontend/public/branding/` alone (allowed by `fork-allow.txt`); `src/index.css` stays core.

| File | Shown | Upstream ships |
|---|---|---|
| `theme.css` | colour overrides, linked at the top of `<body>` so it always loads after the app's CSS | comments only (no rules) |
| `mark-light.svg`, `mark-dark.svg` | the sign-in pages, light and dark theme | the Springform mark |
| `header-light.svg`, `header-dark.svg` | the header bar, light and dark theme | copies of the marks |
| `favicon.svg` | the browser tab | the Springform tab icon |

**Logos** are sized by height with automatic width: 28 px tall in the header (at most `min(40vw, 10rem)` wide, so a wide wordmark fits a 390 px phone) and 36 px on the sign-in pages (at most `min(60vw, 14rem)`). A square mark looks as before; a wide wordmark keeps its ratio. The header has its own pair so a dark header bar can carry an on-dark (light) logo while the sign-in pages keep the normal one. The files must be SVG; a raster logo goes inside one: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 W H" width="W" height="H"><image width="W" height="H" href="data:image/png;base64,…"/></svg>` with the PNG's pixel size as W and H (an `<img>` loads no external files from an SVG, so the data URI is required).

**The install name beside the logo.** The header shows the install name next to the logo. When the logo already spells it (a wordmark), an admin turns off **Show the name next to the logo** in Settings > Workspace (setting `workspace.show_name`, default on, sent to the shell as `show_name` in `GET /api/core/workspace`). The header then shows only the logo; the home link keeps the install name as its `aria-label`, and the tab title is the install name either way (except while a page sets its own, as Todos does). The sign-in pages do not follow the setting: they show the mark, not the header logo, and run before sign-in, when the workspace route answers 401.

**`theme.css`** holds only token blocks; the contrast guards refuse any other selector, because app markup is not a stable interface.

```css
:root      { /* both themes: light values and anything shared */ }
:root.dark { /* dark theme only */ }
```

A token set in `:root` applies in dark mode too (it beats `index.css`'s `.dark` block), so every value that differs in dark (surfaces, ink, `accent-text`, the header) needs a `:root.dark` line. `--color-sf-accent-soft` is a mix of the accent and follows it.

| Token | Paints | Default |
|---|---|---|
| `--color-sf-bg`, `-card`, `-raised` | page, card and raised surfaces | cream / warm greys |
| `--color-sf-line`, `-line-strong` | borders | greys |
| `--color-sf-ink`, `-ink-mute`, `-ink-soft`, `-ink-dim` | text, darkest to lightest | ink ramp |
| `--color-sf-hover` | hover tint; keep it an rgba of `ink` | ink at 5% |
| `--color-sf-accent`, `-accent-dark` | accent FILL: buttons, focus, active states | copper |
| `--color-sf-accent-ink` | text on an accent fill | white |
| `--color-sf-accent-text` | accent as TEXT or an icon | dark copper / light copper |
| `--color-sf-header` | header bar background | the page `bg` |
| `--color-sf-header-ink` | header text and icons; muted items, outlines and hover become tints of it | the page ink ramp |
| `--color-sf-highlight` | the rule under the header and the active-nav underline | `line` and `accent` |
| `--sf-header-rule` | that rule's width (a length, e.g. `3px`) | `1px` |

The three header tokens are not declared upstream; the header reads them with a fallback to the page tokens, so leaving them out keeps the plain header. The mobile browser's `theme-color` follows `--color-sf-header`.

**The AA rule.** Every pairing painted as text must clear WCAG AA 4.5:1, in both themes. Accent is two tokens because a fill colour usually fails as text on a light page: `accent` is for fills (with `accent-ink` on top), `accent-text` for glyphs on `bg` and `card`. The ink ramp must clear 4.5:1 on every surface, `header-ink` (and its 80% tint) on `header`. The contrast guards in `frontend/src/core/theme/*.test.ts` read `index.css` with `theme.css` over it, so a fork's own palette is checked in its CI (Frontend job). `--color-sf-highlight` is a line, not text.

## Tests that pin this

- Live: `new-fork.sh` + `update-from-upstream.sh` on a throwaway repo with the two-PR scope test.
- Step 1b: scope check fails on a core edit and passes on an app edit.
- `gen-types` diff clean (types regenerate in the update PR).
- Brand: `frontend/src/core/theme/themeOverride.test.ts` (an override changes the accent; the header's contrast) and `frontend/e2e/branding.spec.ts` (the cascade in a real browser, a missing `theme.css`, a wide logo at 390 px).

## Source

Build plan: §13 (forks, scope check, releases, one `ci.yml`), §12 (generated types exempt), §14 (`seed-labels.sh`, `AUTO_ISSUES.md`, `ci.yml` structure), Decisions (Forks), SQLite rules (schema compatibility, "Schema" changelog), Steps 1b, 5, 6.
