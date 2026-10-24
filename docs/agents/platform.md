# Platform overview

**What this covers:** what Springform is, the repo tree, the one-container / one-file / one-process shape, the hosting contract, roles, the built-in apps, the build order, the hard lines and the versioning policy.
**Who reads it:** every implementer, first. The other files in `docs/agents/` hold the detailed contracts this one points at.

## What Springform is

Springform is an MIT-licensed foundation for small-business software. The plumbing every such install needs (login, users and roles, a contacts directory, files, notes on records, to-dos, a scheduler, backups, an AI helper, a way to file the next change) lives in `backend/core/` and `frontend/src/core/`. Business apps live in their own folders. A client gets a private repo that pulls platform updates with `git merge upstream` and never edits core.

The motivating failure: a previous fork of CakeCRM had to edit 25 CakeCRM files in three months just to add its own screens, because the extension points did not exist. Springform's app contract (`apps-and-contracts.md`) is the full list of extension points from day one.

## Shape

| Piece | Contract |
|---|---|
| Container | One Docker image, one container. |
| Database | One SQLite file on one volume (`/data`). `db.log_db()` is a seam that returns the main connection in v0.1. |
| Process | One process (`uvicorn --workers 1`), guarded by `fcntl.flock` on `/data/.springform.lock`. A second process refuses to start. |
| Backend | FastAPI + Pydantic. |
| Frontend | React + Vite + Tailwind + TypeScript (the CakeCRM stack, so its code can be lifted). |
| Apps | Folders with an `app.json`. The platform discovers them, mounts their API at `/api/<slug>`, loads their screens lazily, runs their migrations, jobs and seed data, puts a tile on the launcher, and gives every record they own a timeline, attachments, custom fields, saved views, reminders and notifications. |
| Contacts | Core owns the directory: people and organizations, many-to-many with a role. Every app points at the same people. |
| Agent | One default agent, **Whisk**, roster-capable. Every app registers tools with Whisk through one hook (`tools.py`). |
| MCP | Each user can mint an MCP link that is an API key for that user. Admins can connect Whisk outward to other MCP servers. |
| AI keys | The whole install works with zero AI keys. Only Whisk waits for one. |

`backend/main.py` `create_app()` discovers apps and mounts their routers **at import**. The lifespan runs, in order: **checks → migrate → seed → scheduler**. Seed runs every app's idempotent `seed(conn)` at every startup; in `PREVIEW_MODE` it also seeds the preview users and runs every app's `sample(conn)`. The checks include the `flock`, the SQLite version and FTS5 assertion (`database-and-transactions.md`), the `requires_core` check (run by the migration runner before any migration) and the `PREVIEW_MODE` real-secrets refusal (`auth.md`).

## Repo tree

```
springform/
  AGENTS.md  CLAUDE.md(@AGENTS.md)  LICENSE  CHANGELOG.md  springform-version  fork-allow.txt
  pyproject.toml  uv.lock  Dockerfile  entrypoint.sh  railway.json  run.py
  backend/
    main.py                 create_app(): discover + mount at import; lifespan = checks → migrate → seed → scheduler
    core/
      db.py settings.py secrets.py kv.py registry.py entities.py scheduler.py backup.py changelog.py
      clock.py localtime.py errors.py pagination.py ratelimit.py logscrub.py csv_export.py sheets.py github.py docs.py preview.py
      auth/        service.py jwt.py deps.py router.py totp.py google.py invites.py mail.py bootstrap.py users_router.py csrf.py
      contacts/    service.py api.py router.py
      timeline/ files/ fields/ views/ reports/ notifications/ reminders/     (each: service.py api.py router.py)
      agent/       providers/ spec.py registry.py confirm_tier.py engine.py history.py assembly.py compaction.py
                   deferred.py agents.py memory/ context_files/ observer.py dreaming.py router.py mcp_server.py mcp_client.py jobs.py
      migrations/  20261020HHMMSS_core_<name>.sql
      docs/        core Guide topics
    apps/<slug>/
      app.json  router.py  api.py  service.py  models.py  entities.py  hooks.py  reports.py  tools.py  jobs.py  seed.py  settings.py
      migrations/YYYYMMDDHHMMSS_<slug>_<name>.sql   docs/index.md
    apps/crm/   apps/todos/   apps/example/   (example is the integration fixture: it contributes every seam)
    tests/      conftest.py  test_app_contract.py  fixtures/bad_app/  test_core_*.py
  frontend/
    vite.config.ts  vitest.config.ts  vite-plugin-apps.ts (virtual:springform-apps from backend/apps/*/app.json)
    src/core/   api/{client.ts,types.gen.ts}  apps/registry.ts  shell/  auth/  contacts/  records/  agent/  pages/  settings/  theme/
    src/shared/ (lifted CakeCRM: toast, confirm, icons, styles, MobileMenuDrawer, …)
    src/apps/<slug>/contributions.ts (light: lazy loaders)  index.tsx (heavy: the app)  api.ts  pages/  components/
  docs/agents/*.md   docs/AUTO_ISSUES.md   docs/PROVENANCE.md   docs/apps/ (fork-owned)
  deploy/   setup.sh  deploy.sh  compose.yml  Caddyfile  .env.example
  scripts/  new-fork.sh  check-fork-scope.sh  seed-labels.sh  gen-types.sh  new-app.sh  update-from-upstream.sh
  .github/workflows/  ci.yml  release.yml
```

`scripts/restore.sh` (§1) is not drawn in the plan's tree but is named in §1 and Step 1; it lives in `scripts/`.

There is no fork workflow template: one `ci.yml` serves upstream and forks, with the conditional Fork scope job (`forks.md` §5).

## Hosting contract

The image follows ONCE's contract: **one port, `/up`, data in `/data`, configuration from the environment.** Details are in `deploy.md`.

| Item | Contract |
|---|---|
| Port | One HTTP port: `PORT` from the environment, default 8000. Railway sets `PORT`; Caddy proxies to `app:8000`. |
| `/up` | `SELECT 1`, then `200 "ok"`. No auth. Docker `HEALTHCHECK` and Railway's healthcheck use it. |
| `/api/health` | `{version, sqlite_version, fts5, preview, apps:[slug], last_backup_at}`. No auth. `version` is read from `springform-version`. |
| `/data` | The only state. Everything a restore needs is in it (see below). |
| Env config | No configuration is baked into the image. |

### `/data` layout (every path the plan names)

| Path | What |
|---|---|
| `/data/springform.sqlite` | The SQLite database. |
| `/data/.springform.lock` | The single-process `flock`. |
| `/data/.encryption-key` | Fernet key, generated on first boot when `ENCRYPTION_KEY` is not set. |
| `/data/setup-token` | One-time first-admin token, mode 0600 (`auth.md`). |
| `/data/files/<sha[:2]>/<sha>` | Attachment blobs. |
| `/data/files/tmp/<uuid>` | Upload staging. |
| `/data/backups/<stamp>.sqlite`, `/data/backups/<stamp>.manifest.json` | Backup recovery sets (`deploy.md`). |

The data directory is `DATA_DIR` (the donor's env var, kept; default `./data` for development). In the container it is `/data`, so the database is `/data/springform.sqlite`.

### Environment variables

| Variable | Effect | Doc |
|---|---|---|
| `PORT` | The HTTP port, default `8000`. Railway sets it. | `deploy.md` |
| `DATA_DIR` | The data directory, default `./data`; `/data` in the container. | `database-and-transactions.md` |
| `PUBLIC_URL` | The install's public URL: Google redirect URI, CSRF origin, scheme warning. Shown read-only in Settings; not a `core_settings` key. | `auth.md` |
| `ENCRYPTION_KEY` | Fernet key; when set, no key file is written. | `deploy.md` |
| `TRUST_PROXY` | `1` → uvicorn `--proxy-headers --forwarded-allow-ips='*'`. | `auth.md`, `deploy.md` |
| `PREVIEW_MODE` | `1` → seeded preview users, role picker, Google stub. | `auth.md` |
| `RESEND_API_KEY`, `MAIL_FROM` | Invite and reset mail via Resend. | `auth.md` |
| `MCP_ALLOW_PRIVATE` | `1` → outbound MCP may reach private addresses and `http://`. | `mcp.md` |
| `AGENT_VECTOR` | `1` → optional `core_agent_vectors`. | `agent.md` |
| `DOMAIN` | Caddy site address in `deploy/`. | `deploy.md` |
| `IMAGE` | Image `compose.yml` and `railway.json` run. | `deploy.md`, `forks.md` |
| `RAILWAY_DEPLOYMENT_DRAINING_SECONDS` | `15`, documented for Railway. | `deploy.md` |

## Roles

| Role | Who | Notes |
|---|---|---|
| `admin` | Invited humans. | Settings, users, backups, export, jobs, hidden apps. |
| `member` | Invited humans. | Default role for business users. |
| `system` | One seeded row, `core_users.id = 0`. | Not a login role. Records unattended actions. Reads as a member through `can_read`; `authorize` always refuses it a write. See `authorization.md` §7. |

Login is invite-only. The first admin is created with a one-time setup token, never by "first visitor" (`auth.md`). There is no Cloudflare Access in front of the app.

## Built-in apps

Springform ships two business apps plus the Example fixture. Example is hidden from clients by default.

| App | Folder | What |
|---|---|---|
| CRM | `backend/apps/crm`, `frontend/src/apps/crm` | CakeCRM ported to SQLite onto the core directory, minus its GTD, Gmail, Telegram and built-in assistant (Baker) code. Path `/crm`, API `/api/crm`. |
| Todos | `backend/apps/todos`, `frontend/src/apps/todos` | todo-gtd ported from "one list is the account" to per-user todos with team todos. Private by default; team todos editable by any member; admins see team todos and their own only. API `/api/todos`. |
| Example | `backend/apps/example`, `frontend/src/apps/example` | The integration fixture: contributes every seam from its own folder (`apps-and-contracts.md`). |

Core screens (not apps): launcher, settings, people and organizations, Guide, Requests board, ChangeLog, Backups, Jobs, connected Google Sheets, the Whisk page (`frontend-shell.md`).

## Build order

| Step | What | Who |
|---|---|---|
| 0 | Repo created (public, MIT, README-only `master`); branch protection with the required checks once CI exists. Google OAuth client, Resend key and GitHub token are registered later in Settings, not in the repo. | Author |
| 1 | **Foundation** on branch `foundation`: every shared contract with behaviour, plus a minimal real implementation of every piece the vertical slice needs (list in "Step 1 scope" below). Later workstreams extend these; they do not replace them. | Author + one agent |
| 1b | **Vertical slice** through `apps/example` against the real Step 1 code: setup token → admin → invite a member (copy link) → create an example record → note + attachment → the other member is refused on every surface → a FakeProvider tool call confirms and runs via `handler_in` → back up, restore the set into an empty volume, open the attachment → `new-fork.sh` into a throwaway repo, CI green → the scope check fails on a core edit and passes on an app edit. Contract breakage found here is fixed here. | One agent |
| 2 | Core workstreams in parallel, disjoint folders: W1 Login (§2); W2 contacts + record-service backends (§3–4, up to three agents: contacts+timeline+files / fields+views+reports / notifications+reminders); W3 scheduler, backup + restore test, changelog, Jobs/ChangeLog/Backups pages (§11, §1); W4 Sheets + CSV + export policy + Sheets page (§9); W5 Guide + Requests; W6 Shell: Launcher, Layout, Settings registry, shared lift, theme (§10); W7 Todos (§8); W8 Dockerfile, `deploy/`, `scripts/`, `release.yml`, gen-types, image test (§12–13); W9 providers + keys UI, `ToolSpec`/registry/confirm tiers, core tool sources (§5). W1 and W9 contribute settings cards through W6's registry and do not touch `settings/`. | Parallel agents |
| 3 | W10 CRM backend (§7); W11 contacts frontend + record-services frontend (§3–4); W12 Whisk engine/history/compaction/confirm/router + chat UI (§5); W13 CRM frontend (§7), starting against a stub once W10's route shapes exist and W11 lands. | Parallel agents |
| 4 | W14 MCP server and W15 MCP client (after W12); W16 nightly observer/dreaming; W17 Guide content + `docs/agents` refresh. | Agents |
| 5 | Integrate and release: full suite + Playwright smoke on a seeded `PREVIEW_MODE` build; fresh-VPS dry run; restore drill; tag `v0.1.0`; fork round-trip with the two-PR scope test (`forks.md`); review on each PR and `ready-to-ship` labels throughout, never merged by hand. | Agents |
| 6 | The first client fork is created with `new-fork.sh` against `v0.1.0`; its apps are built there, not here. | Client fork |

Landing priority: core and the pieces the first client fork needs, then the CRM port, then Whisk, then MCP. Each workstream merges to `master` when green.

### Step 1 scope

`pyproject`/uv, `package.json`/vite/vitest + `vite-plugin-apps.ts`; `core/db.py` (transaction composition, outbox, migration runner with checksums), `settings.py`, `secrets.py`, `kv.py`, `clock.py` (+ `normalize`), `localtime.py`, `errors.py`, `pagination.py`, `registry.py` (all modules in the contract, role guard at mount), `entities.py` (`authorize`, hooks), `main.py`; the core init migration `20261020000100_core_init.sql` (settings, change_log, job_runs, apps_state, requests, backups, outbox, file blobs, users incl. the system user, totp, trusted_devices, login_tokens, login_attempts, contacts tables, timeline, files); `auth/` minimal but real (setup token, password login, cookie session, `current_user`/`require_admin`, invite with a copyable link, no mail yet); `timeline/` notes + `record_changes_in`; `files/` upload/download with the publication protocol; `scheduler.py` minimal (`Job`, loop, `run_now`); `backup.py` with manifests + `scripts/restore.sh`; `agent/spec.py` + `registry.py` + a FakeProvider engine stub that can run one confirmed `handler_in` tool; `tests/conftest.py` (temp DB, `freeze`, `login_as`), `test_app_contract.py` + `fixtures/bad_app`; `apps/example` (every seam); `scripts/new-app.sh`, `new-fork.sh`, `check-fork-scope.sh`; frontend `core/api/client.ts`, `apps/registry.ts` (contributions + lazy), `Root.tsx`, Layout/Launcher, a minimal record page for `example` with Timeline + Attachments; `docs/agents/`; `AGENTS.md`; `ci.yml` (incl. the conditional Fork scope job).

**Frozen stub signatures** Step 1 ships for later workstreams to fill: `core.changelog.record_in`, `core.sheets.client`, `core.csv_export.stream_csv`, `core.notifications.deliver_in`, `core.reminders`.

## Hard lines

1. **Apps never edit core.** An app's code, migrations, settings cards, record panels, tools, jobs and docs live in its own folders. A fork's CI fails any core path that differs from the pinned upstream tag (`forks.md`).
2. **Core never references app tables.** Core migrations and core code name only `core_*` tables. Apps reference `core_*` and their own `<slug>_*` tables, never another app's. Apps import another app only through `apps.<x>.api`.
3. **No nested transactions.** `transaction()` raises `NestedTransaction` when the thread's connection is already in one. Code that runs inside a caller's transaction takes `conn` (`fn_in(conn, …)`).
4. **`now_iso()` only.** `core.clock.now_iso()` is the only timestamp writer; SQL never calls `datetime('now')` or `CURRENT_TIMESTAMP`.
5. **No network or LLM call inside `transaction()`.** External effects run outside the write lock (outbox consumers, external-effect tools, sheet refresh, notification flush).
6. **No member data in the repo.** Credentials (Google OAuth client, Resend key, GitHub token, AI keys) are entered in Settings after deploy and stored encrypted in `core_settings`. A client's own apps and data live in the client's private fork.
7. **Every core service and router authorizes.** One `entities.authorize` call before touching a record (`authorization.md`).
8. **Core schema is additive within a major** (below).

## Versioning policy

| Item | Rule |
|---|---|
| `springform-version` | One line at the repo root (`0.1.0` today). Read by `/api/health` and by the migration runner's `requires_core` check. |
| Tags and releases | `vX.Y.Z` tags; `release.yml` builds and pushes `ghcr.io/${{ github.repository }}:<tag>,latest` (`forks.md`). |
| `CHANGELOG.md` | keep-a-changelog. Schema changes and deprecations are recorded under a "Schema" heading. |
| `requires_core` | Every app manifest declares a PEP 440 specifier set (parsed with `packaging`), e.g. `>=0.1,<1`. **The runner checks every installed app's `requires_core` against `springform-version` before applying any migration** and refuses to start on a mismatch, naming the app. |
| Core schema compatibility | **Within a major version, core never drops or renames a table or column.** Changes are additive: new tables, new nullable columns, new indexes. A column core stops using is marked deprecated in `CHANGELOG.md` "Schema" and stays in place, nullable and unused, until the next major. |
| Major release | May drop deprecated columns and ships a **baseline** migration. Apps crossing a major re-baseline (squash their migrations) and raise `requires_core`. |
| Lint | Every core migration except files named `*_baseline.sql` fails CI if it contains `DROP COLUMN`, `DROP TABLE` or `RENAME`. |
| App manifest `version` | The app's own version. It feeds `tool_def_sha256` for the app's tools (`agent.md`). |

Because nothing an app may reference disappears inside a major, a fresh install (all current core migrations, then historical app migrations) and an upgraded install reach the same schema.

## Doc index

| Doc | Covers |
|---|---|
| `database-and-transactions.md` | Connection, `transaction()`, `_in` forms, hooks vs outbox, migrations, identifiers, timestamps, money, search, single process, SQLite version. |
| `apps-and-contracts.md` | `app.json`, discovered modules, frontend contributions, the contract test, `apps/example`, `new-app.sh`, hiding apps. |
| `authorization.md` | `Entity`, `authorize`, hooks, roles, stored copies, the system principal, the two-member test. |
| `auth.md` | Sessions, CSRF, users, setup token, Google, TOTP, invites, deactivation, preview mode. |
| `contacts.md` | People, organizations, links, channels, merge, `contacts.api`. |
| `records.md` | Timeline, files, fields, views, reports, notifications, reminders, change log, record components. |
| `agent.md` | Whisk: tables, memory privacy, `ToolSpec`, registry, turn loop, confirmation, SSE. |
| `mcp.md` | Inbound links and outbound servers. |
| `scheduler.md` | Jobs, status enum, timeouts, catch-up, core job list. |
| `sheets-and-export.md` | Connected Google Sheets, CSV, the export policy. |
| `frontend-shell.md` | Shell, launcher, settings registry, core pages, type generation, tokens, the API block. |
| `testing.md` | Every verification item by suite, conftest conventions. |
| `deploy.md` | Image, entrypoint, `deploy/`, Railway, backups and restore. |
| `forks.md` | Fork model, scripts, scope check, CI, images, releases. |
| `source-map.md` | Springform path → donor path, and the provenance rule. |

## Tests that pin this

- Contract guard passes for `example`/`crm`/`todos` and fails `bad_app`.
- Migrations apply in order (core before apps); upgrade from the previous tag + a private fixture app.
- `now_iso` is the only timestamp writer (grep test); no `httpx` inside `transaction()`; nested `transaction()` raises.
- Live: CI image test (sqlite version, fts5); `new-fork.sh` + `update-from-upstream.sh` on a throwaway repo with the two-PR scope test.
- Playwright smoke on a seeded `PREVIEW_MODE=1` build (`testing.md`).

## Source

Build plan: Overview, Decisions, Architecture (tree, SQLite rules), §1, §13, §14, Build steps 0–6, Verification.
