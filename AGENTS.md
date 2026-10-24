# Springform

An open-source (MIT) foundation for small-business software: one SQLite file, one FastAPI
process, one Docker container. Platform plumbing lives in `backend/core/` and `frontend/src/core/`;
business features are apps in `backend/apps/<slug>/` and `frontend/src/apps/<slug>/`. A client
gets a private fork that pulls platform updates with `git merge` and never edits core.
Default branch `master`.

## Commands

Python 3.12 managed by `uv` from the root `pyproject.toml`; the frontend is npm in `frontend/`.

```bash
uv sync                                        # backend deps
uv run uvicorn backend.main:app --reload       # http://localhost:8000, data in ./data
cd frontend && npm ci && npm run dev           # hot-reload frontend
```

Before pushing, run what CI runs:

```bash
uv run ruff check . && uv run pytest -q
cd frontend && npm run lint && npm run typecheck && npm test && npm run build && cd ..
scripts/gen-types.sh && git diff --exit-code frontend/src/core/api/types.gen.ts
docker build -t springform .                   # the Image test boots this and reads /api/health
```

Scaffold an app with `scripts/new-app.sh <slug> "<Name>"`. Fork tooling: `scripts/new-fork.sh`,
`scripts/update-from-upstream.sh`, `scripts/check-fork-scope.sh` (see `docs/agents/forks.md`).

## Topic docs

Before changing code in an area, read its doc in `docs/agents/`. Keep these as plain paths,
not `@` imports (imports load eagerly).

| Doc | Covers |
|---|---|
| `platform.md` | The shape: core vs apps, process model, settings, where things live |
| `database-and-transactions.md` | `transaction()`, `_in` forms, outbox, migrations, schema compatibility, timestamps, money |
| `apps-and-contracts.md` | `app.json`, every app module and seam, table ownership, the contract test |
| `authorization.md` | Roles, `can_read`/`can_write`, `entities.authorize`, role guards on app routers |
| `auth.md` | Setup token, password + TOTP, Google sign-in, invites, sessions, CSRF |
| `contacts.md` | People, organizations, roles between them, merges |
| `records.md` | Timeline, files, custom fields, saved views, reports, notifications, reminders |
| `agent.md` | Whisk: providers, tool registry, confirm tiers, memory, context files |
| `mcp.md` | Inbound MCP links and the outbound MCP client |
| `scheduler.md` | Jobs, the loop, timeouts, catch-up, core jobs |
| `sheets-and-export.md` | Connected Google Sheets, CSV export, export policy |
| `frontend-shell.md` | Launcher, layout, app registry, contributions, settings cards, lazy loading |
| `testing.md` | pytest and vitest conventions, guard tests, CI jobs |
| `deploy.md` | Image, `/data`, single process, stop-before-start, VPS and Railway, backups off-site |
| `forks.md` | Fork model, `FORK.md`, the scope check, updates from upstream, releases |
| `source-map.md` | Where lifted code came from (with `docs/PROVENANCE.md`) |

New implementation notes and design reasoning go in the matching topic doc. Change this file
only when a core rule changes.

## Hard lines

- **Apps never edit core.** An app's changes live in its own folders. Core gains an extension
  point upstream; a fork never patches core (`scripts/check-fork-scope.sh` fails CI).
- **Core never references app tables** or imports app code. Core migrations name only `core_*`
  tables; apps reference only their own `<slug>_*` tables and `core_*`.
- **No nested transactions.** `transaction()` raises `NestedTransaction`; code that runs inside a
  caller's transaction takes `conn` and is named `fn_in(conn, …)`.
- **Timestamps come only from `core.clock.now_iso()`** (or `clock.normalize` for user input).
  Never `datetime('now')`, `CURRENT_TIMESTAMP` or `datetime.now()` in SQL or services.
- **No network or LLM call inside `transaction()`.** Work after commit goes through the outbox.
- **No member data in the repo**: no real people, client names, phone numbers, emails, customer
  records or secrets, in code, fixtures, docs or filenames. History is public and permanent.

## Backend rules

- SQLite is the only datastore: one file under `DATA_DIR`, WAL, `foreign_keys=ON`, one writer
  lock. SQLite ≥ 3.51.3 is required and asserted from the live connection at startup.
- One process: `--workers 1`, a file lock on `/data/.springform.lock`, deploys are
  stop-before-start. In-process caches and the scheduler rely on this.
- Every service and published API function comes as `fn(...)` (opens its own transaction) and
  `fn_in(conn, ...)` (runs inside the caller's). Sync hooks receive `conn` and do cheap
  bookkeeping only; anything slow or external is an outbox consumer.
- Migrations are new files, never edits: `backend/core/migrations/YYYYMMDDHHMMSS_core_<name>.sql`
  and `backend/apps/<slug>/migrations/YYYYMMDDHHMMSS_<slug>_<name>.sql` (app stamps
  `>= 20261101000000`). Checksums are recorded; changing an applied file fails startup.
- Within a major version core never drops or renames a table or column. A column core stops using
  is listed under "Schema" in `CHANGELOG.md` and stays, nullable, until the next major.
- Every object an app creates (table, index, trigger, view, virtual table) is named `<slug>_*`.
  Entity tables use `INTEGER PRIMARY KEY AUTOINCREMENT`; nothing resets `sqlite_sequence`.
- Authorization: every core service checks the entity's `can_read`/`can_write` through
  `entities.authorize`; app routers carry the manifest's role guard. Roles are `admin`, `member`.
- Another app's code is reachable only through `apps.<slug>.api`. Jobs are named `<slug>.<job>`,
  tools `<slug>_<tool>`.
- Money is integer cents, never REAL. Search uses FTS5; `LIKE … COLLATE NOCASE` is ASCII-only.
  Local-day bucketing happens in Python with `zoneinfo` and the install timezone.
- The whole install works with zero AI keys; only Whisk waits for one.

## Frontend rules

- An app's screens live in `frontend/src/apps/<slug>/`: `contributions.ts` is light (lazy loaders
  only), `index.tsx` is the app and loads only when its route is visited. Never import another
  app's folder.
- API types come from `frontend/src/core/api/types.gen.ts`, generated by `scripts/gen-types.sh`.
  Never edit it by hand; regenerate and commit it with the backend change.
- Pages and heavy panels load lazily; the bootSplit tests enforce it.
- Vitest runs with a pinned non-UTC `TZ`; keep it.

## Tests and CI

- No `skip`, `xfail`, `# noqa` or `eslint-disable`: fix the cause.
- A new repo-wide guard test needs a self-test on synthetic input (one case it must flag, one it
  must not) and an assertion that it reached the real code.
- CI (`.github/workflows/ci.yml`, one file for upstream and forks) runs **Backend**, **Frontend**
  (incl. the `types.gen.ts` diff), **Browser smoke** (`scripts/e2e.sh`), **Secret scan**, **Image
  test** and **Fork scope** (a no-op without `FORK.md`). Required checks are Backend, Frontend, Secret scan and Fork scope.
- Gitleaks scans full history. For a verified false positive add its exact fingerprint to
  `.gitleaksignore` with a reason; never a path-keyed allowlist.
- Workflows trigger on `pull_request`, never `pull_request_target`; third-party actions are
  pinned to a commit SHA with the version in a trailing comment.

## Scope

- Core is thin: plumbing every business needs. A feature one business needs is an app.
- Built-in apps: CRM and Todos, plus `example`, the integration fixture that uses every seam.
- One default agent, Whisk. Login is invite-only with two roles.
- A fork changes only `backend/apps/`, `frontend/src/apps/`, `docs/apps/`, lockfiles, generated
  types and the globs in `fork-allow.txt`. Anything else is sent upstream. The app folders are
  fork-editable in full, built-in apps (CRM, Todos, example) included, by design.

## Commits and PRs

- Branch from `master`, PR to `master`; never push to `master` directly. Don't merge your own PR:
  label it `ready-to-ship` when it is green (see `docs/AUTO_ISSUES.md`).
- Plain commit messages. No AI attribution, `Co-Authored-By` trailers or tool-generated footers.
- A user-visible change adds a line under "Unreleased" in `CHANGELOG.md`.
- Code lifted from another repo gets a row in `docs/PROVENANCE.md` in the same PR.
