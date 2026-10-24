# Apps and the app contract

**What this covers:** `app.json` and the `AppManifest` model, every auto-discovered backend module and what it exports, the frontend contract (`contributions.ts`, `index.tsx`), the contract test and its Vitest twin, `apps/example` as the integration fixture, `scripts/new-app.sh`, hiding apps, and core packages, which contribute the way apps do.
**Who reads it:** anyone writing or porting an app (CRM, Todos, a client's app), and anyone working on `core/registry.py`, `frontend/src/core/apps/registry.ts` or the contract tests.

The app contract replaces the 25 core edits a previous CakeCRM fork needed. An app touches nothing outside `backend/apps/<slug>/`, `frontend/src/apps/<slug>/` and (in a fork) `docs/apps/`.

## 1. `app.json` → `AppManifest`

`backend/apps/<slug>/app.json` is parsed into the Pydantic model `AppManifest`.

| Field | Type | Rule |
|---|---|---|
| `slug` | string | `^[a-z][a-z0-9_]{1,29}$`. Equals the folder name. **Permanent**: it is baked into table names. Reserved: `core`, `api`, `auth`, `mcp`, `up`, `assets`, `agent`, `me`, `health`, `settings`, `people`, `organizations`, `guide`, `requests`, `login`, `setup`, `invite`, `changelog`, `backups`, `jobs`, `sheets`, `notifications`, `reminders`, `whisk`, `files`, `timeline`, `export`, `reports`, `reset-password`. A slug may not start with `core_`, and may not equal another installed slug + `_` + anything (prefix collision: `crm` and `crm_x` cannot both be installed). |
| `name` | string | Display name (launcher tile, settings section). |
| `description` | string | Launcher/tile description. |
| `path` | string | Must equal `/<slug>`. |
| `icon` | string | Icon name for the tile. |
| `roles` | list | Subset of `admin`, `member`. Enforced on the router at mount and inherited by the app's entities, reports and tools (`authorization.md`). |
| `order` | int | Default launcher order; `core_apps_state.position` overrides it when set. |
| `badge` | string, optional | A route returning `{count, label?}` (the example uses `"/api/example/badge"`). |
| `docs` | string | The app's Guide docs (the example uses `"docs/index.md"`). |
| `version` | string | The app's version; part of `tool_def_sha256` for the app's tools. |
| `requires_core` | string | PEP 440 specifier set over `springform-version` (parsed with `packaging`), e.g. `>=0.1,<1`. Checked before any migration runs. |
| `settings_cards` | list | `[{id, title, admin_only}]`. Each `id` must have a loader in `contributions.ts`. |
| `sheets` | list | `[{name, mode, description}]`, `mode` is `read` or `write`. Seeds `core_connected_sheets` (`sheets-and-export.md`). |
| `publishes` | list | Names of the app's published functions (the example lists `["get_widget", "widgets_for_person"]`). Validated against the names `api.py` exports. |

The current fixture manifest (`backend/apps/example/app.json`):

```json
{
  "slug": "example",
  "name": "Example",
  "description": "The integration fixture: a small app that uses every extension point. Hidden from clients by default.",
  "path": "/example",
  "icon": "flask",
  "roles": ["admin", "member"],
  "order": 900,
  "badge": "/api/example/badge",
  "docs": "docs/index.md",
  "version": "0.1.0",
  "requires_core": ">=0.1,<1",
  "settings_cards": [{ "id": "example", "title": "Example", "admin_only": true }],
  "sheets": [{ "name": "widgets", "mode": "read", "description": "A sample sheet of widgets" }],
  "publishes": ["get_widget", "widgets_for_person"]
}
```

Open (pinned by the implementing workstream, which updates this doc): the `icon` vocabulary is not stated.

## 2. Backend modules

`core/registry.py` discovers `backend/apps/*/`. All modules are optional **except** `router.py`, `migrations/`, `seed.py` and the docs file named by the manifest's `docs` field (default `docs/index.md`). Unknown manifest keys are refused.

| Module | Exports | Contract |
|---|---|---|
| `app.json` | manifest | §1 above. |
| `router.py` | `router` | Mounted at `/api/<slug>`, tagged `<slug>` (stable `operationId`s for type generation). `registry.mount_app()`, run by `registry.install()`, adds `Depends(require_roles(manifest.roles))`. Every `/api` route, core or app, answers 401 without a session unless it is listed in `ALLOW_UNAUTHENTICATED` in the contract test (the sign-in routes and `/api/health`). |
| `api.py` | published functions | **The only module another app may import** (`from backend.apps.<x>.api import …`). Every published function has an `_in(conn, …)` form. |
| `entities.py` | `ENTITIES = [Entity(...)]` | Table, labels, URL and title builders, `can_read(user, conn, id)` / `can_write(user, conn, id)` (`authorization.md`). |
| `hooks.py` | `HOOKS = {"on_entity_deleted": [...], "on_entity_merged": [...], "on_record_changed": [...], "after_record_changed": [...]}` | The registry subscribes them. The three sync keys run in the caller's transaction; `after_record_changed` takes `fn(conn, payload)` after commit, via the outbox. Signatures are in `authorization.md` §3. |
| `reports.py` | `REPORTS = [Report(...)]` | `records.md`. |
| `tools.py` | `get_tools() -> list[ToolSpec]` | Names prefixed `<slug>_`; per-spec `enabled(user)` (`agent.md`). |
| `jobs.py` | `JOBS = [Job(name="<slug>.<job>", fn, every=…\|at="HH:MM")]` | `scheduler.md`. |
| `seed.py` | `seed(conn)`, `sample(conn)`, `RESET_TABLES`, `EXPORT` | Below. |
| `settings.py` | `DEFAULTS = {"<slug>.<key>": value}` | Defaults for `core_settings`. |
| `migrations/` | `YYYYMMDDHHMMSS_<slug>_<name>.sql` | Below. |
| `docs/index.md` | Guide topic(s) | Front matter + Markdown, loaded by `backend/core/guide/library.py`. `docs/index.md` is the topic `<slug>`; any other `docs/<name>.md` is `<slug>.<name>` (`frontend-shell.md` §3). |
| `service.py`, `models.py` | — | App-internal; not discovered. |

### `api.py` and the import rule

1. Another app (or core) may import an app only through `backend.apps.<x>.api`. The contract test parses each app's Python with `ast` and flags any other `backend.apps.<other>` import, and any relative import that leaves the app package.
2. Every published function has `fn(...)` and `fn_in(conn, ...)` forms (`database-and-transactions.md` §3).

Published APIs the plan fixes so far:

| App | Functions |
|---|---|
| `crm` | `get_deal(user, deal_id)`, `deals_for_person(user, person_id, include_archived=False)`, `deals_for_organization(user, organization_id, include_archived=False)`, `create_deal(user, title, **fields)` (fields as `POST /api/crm/deals`); `_in(conn, …)` forms of each; results are `Deal` dicts |
| `todos` | `create(acting_user_id, title, *, owner_user_id=None, visibility="private", entity_type=None, entity_id=None, due_date=None, notes="", source="app")` (creating for another owner requires `visibility="team"` or an admin; the system principal may create team todos only, owned by user 0 when no owner is given), `list_for_record(user, entity_type, entity_id, include_done=False)`, `complete(acting_user_id, todo_id)`; `_in` forms of each |
| `example` | `get_widget(user, widget_id)`, `widgets_for_person(user, person_id)`, and `get_widget_in(conn, user, widget_id)`, `widgets_for_person_in(conn, user, person_id)` (from `publishes`) |
| core `contacts.api` | `contacts.md` |

### `seed.py`

| Export | Contract |
|---|---|
| `seed(conn)` | The app's reference data. Runs at **every startup** and must be idempotent. Writes through published APIs (the CRM seed writes through `contacts.api`). |
| `sample(conn)` | Sample data. Runs at startup only in `PREVIEW_MODE`, after the preview users and core's sample directory (so it may link to sample people and organizations), and must be idempotent. |
| `RESET_TABLES` | The app's owned **real tables** (no indexes, views or FTS shadow tables). Must **equal** that set (contract test). Used by `registry.reset_app_in`. |
| `EXPORT` | `{"<table>": {"entity": "<slug>.<name>", "columns": [...], "id_column"?, "where"?, "owner_column"?}}`: the column allow-list for the admin export, separate from reset ownership. `entity` is required: one of the app's own entity types, or `None` for no row check. `id_column` (default `"id"`) and `owner_column` must name real columns. Same shape as `CORE_EXPORT` (`sheets-and-export.md` §6). |

### `settings.py`

`DEFAULTS = {key: value}` provides defaults for `core_settings(key PK, value, is_secret, updated_at, updated_by)`.

App setting keys are `<slug>.<key>`. An admin sets them through `PUT /api/core/settings`, which accepts any JSON value for an app key; core keys are listed in `platform.md`.

### `migrations/`

1. File name `YYYYMMDDHHMMSS_<slug>_<name>.sql`; contract test regex `\d{14}_<slug>_`. App migrations are stamped `>= 20261101…`.
2. Every `CREATE` / `ALTER` target starts with `<slug>_`.
3. `REFERENCES` may name `<slug>_*` or `core_*` tables, never another app's.
4. An app migration may reference only core tables that exist at its `requires_core` version.
5. Never edit a migration that has landed.
6. Tables that other rows point at polymorphically use `INTEGER PRIMARY KEY AUTOINCREMENT`.

## 3. Mounting and the API surface

1. `create_app()` discovers apps and mounts routers when it builds the app, before the lifespan runs, so `app.openapi()` works without a database (`frontend-shell.md`, type generation).
2. Each router mounts at `/api/<slug>` with `Depends(require_roles(manifest.roles))`. A member calling an admin-only app's API directly gets **403**.
3. Badge routes return `{count, label?}`. The launcher polls them every 60 s while visible.
4. Errors are `{detail}`: 401 not signed in; 404 missing or not readable, for reads and writes alike, so existence never leaks; 403 when the record is readable but not writable, or a role-guarded route refuses the caller; 422 invalid (`authorization.md` §2).

```
GET  /api/core/apps    -> [{slug, name, description, path, icon, roles, order, badge, hidden, settings_cards, version}] for the caller's role; admins also receive hidden apps with hidden:true
GET  /api/example/widgets[?person_id=]   -> [Widget]  Widget = {id, name, color, owner_user_id, person_id, is_private, created_at, updated_at}
POST /api/example/widgets {name, color?, is_private?, person_id?} -> Widget
GET  /api/example/widgets/{id}           -> Widget; 404 when missing or not readable
PATCH /api/example/widgets/{id} {name?, color?, is_private?, person_id?} -> Widget
GET  /api/example/badge                  -> {count, label?}
Badge routes return {count, label?}. Errors: `{detail}`; 401 not signed in, 403 denied, 404 missing or not readable, 422 invalid.
```

## 4. Hiding apps (hide, never disable)

`core_apps_state(slug PK, hidden, position)` holds the admin's per-install choices from Settings → Apps (order/hide).

1. An installed app is **hidden, not disabled**. `GET /api/core/apps` omits hidden apps for members; admins receive them with `hidden: true`, and the launcher shows them hidden tiles.
2. Hiding removes the tile and nav for members. The app's routes, jobs, tools and record panels stay active, and admins can still open the app.
3. `order` is the manifest default; `core_apps_state.position` overrides it when an admin has reordered.
4. Order and hide are the only per-install app switches the plan defines.

## 5. Frontend contract

| File | Contract |
|---|---|
| `frontend/src/apps/<slug>/contributions.ts` | A **light** module (no screen code), loaded eagerly. Default-exports `{ slug, settingsCards?: Record<id, () => Promise<Component>>, recordPanels?: Record<entityType, () => Promise<Component>>, nav?: NavItem[] }`. |
| `frontend/src/apps/<slug>/index.tsx` | Default-exports `{ slug, App }`. Loaded **only** when the app's route is visited. |
| `frontend/src/apps/<slug>/api.ts`, `pages/`, `components/` | App-internal. API types from `types.gen.ts` (`paths['/api/<slug>/…']`, `components['schemas'][…]`). |

```ts
// contributions.ts (shape)
export default {
  slug: "example",
  settingsCards: { example: () => import("./SettingsCard") },
  recordPanels: { "core.person": () => import("./PersonPanel") },
  nav: [{ label: "Example", to: "/example" }],
} satisfies AppContributions;

// index.tsx (shape)
export default { slug: "example", App };
```

How it is wired:

1. `vite-plugin-apps.ts` exposes `virtual:springform-apps`, built from `backend/apps/*/app.json`. (The Dockerfile's frontend stage copies `backend/apps` so the plugin sees them.)
2. `frontend/src/core/apps/registry.ts` zips `virtual:springform-apps` with `import.meta.glob('../../apps/*/contributions.ts', { eager: true })` and `import.meta.glob('../../apps/*/index.tsx')` (lazy).
3. `Root.tsx` emits one `<Route path={`${path}/*`}>` per manifest.
4. **`recordPanels`** is how an app adds a panel to a core record page without editing core: core's person and organization detail pages render every app's panel registered for `core.person` / `core.organization` (the CRM's `DealsPanel`, the example's person-detail panel).
5. **Settings cards**: the settings registry renders core cards plus one section per app, built from `contributions.ts` `settingsCards`, keyed by the manifest's `settings_cards[].id`; `admin_only` cards are shown to admins only.
6. bootSplit rule: every app's `index.tsx` is lazy; `contributions.ts` is eager but tiny (`frontend-shell.md`).

Both files use `export default`. `NavItem = {label, to, icon?}`. A record panel receives the props `{entityType, entityId}`.

## 6. The contract test (`backend/tests/test_app_contract.py`)

Falsifiable against `backend/tests/fixtures/bad_app` (the test must fail it). It runs over every app in `backend/apps/` (`example`, `crm`, `todos`, and any fork app).

**Manifest and router**

1. The manifest is valid (`AppManifest` parses).
2. `slug` equals the folder name.
3. `path` equals `/<slug>`.
4. `slug` is not reserved and does not prefix-collide with another installed slug.
5. `router.py` is present, and every route carries the auth dependency unless listed in the test's `ALLOW_UNAUTHENTICATED`.
6. The mounted router carries the manifest's role guard.

**Migrations and ownership** (after migrating a temp DB)

7. Migration files are named `\d{14}_<slug>_`.
8. **Ownership is by name prefix for every object type.** Each row of `sqlite_master` (table, index, trigger, view, virtual table) must be named one of:
   - `core_*`;
   - `_migrations_applied`;
   - a SQLite-generated `sqlite_autoindex_*` (a `UNIQUE` or `PRIMARY KEY` constraint's index, attributed to the table it indexes, so rule 9 applies), `sqlite_sequence` or `sqlite_stat*`;
   - an FTS5 shadow table `<fts>_data`, `<fts>_idx`, `<fts>_content`, `<fts>_docsize`, `<fts>_config`, attributed to its virtual table's owner;
   - `<slug>_*` for **exactly one** installed slug.
9. An index or trigger must target a table its own prefix owns (`tbl_name` check).
10. A view may read only owned or `core_` tables.
11. `REFERENCES` may name only `<slug>_` or `core_` tables.

**Seed and export**

12. `RESET_TABLES` lists the app's owned **real tables** (no indexes, views or shadow tables) and must **equal** that set.
13. `EXPORT` names only owned tables and real columns; every entry has an `entity` that is one of the app's registered entity types or `None`; `id_column` and `owner_column`, when given, are real columns.

**Everything else**

14. `docs/index.md` is present.
15. `JOBS` names are prefixed `<slug>.`.
16. Cross-app imports happen only via `api` (an `ast` walk).
17. Tool names carry the `<slug>_` prefix (`build_registry()` checks it at boot as well).
18. Entity types are `<slug>.<name>` on a table the app owns.
19. Migrations are stamped `20261101000000` or later.
20. `seed.py` exports `seed`, `sample` and `RESET_TABLES`.
21. `HOOKS` names only known hooks.
22. `DEFAULTS` keys are `<slug>.<key>`.
23. Every `publishes` name exists in `api.py` as both `name` and `name_in` (the registry also checks this at boot).

### Vitest twin

1. Every manifest has `contributions.ts` and `index.tsx`, and vice versa.
2. Every settings card id has a loader.
3. No `../<otherapp>/` imports.
4. A grep guard that `apps/crm` contains no `contact_id|company_id`.

## 7. `apps/example`, the integration fixture

`apps/example` contributes, all from its own folder:

| Seam | What |
|---|---|
| Route | `/api/example/widgets…`, `/api/example/badge` (API block above). |
| Entity | `example.widget` on `example_widgets`. Anyone may read a widget unless it is private; a private one only its owner. The owner or an admin may write it. |
| Report | One `Report`. |
| Settings card | `example` (admin only). |
| Person-detail panel | A `recordPanels["core.person"]` loader (widgets for a person, via `person_id`). |
| Tool | Two Whisk tools: a read, `example_list_widgets`, and a write, `example_create_widget`. |
| Job | One job, `example.tidy`, every hour. |
| Sheet | `widgets`, mode `read`. |
| Subscribers | `on_entity_merged`, `on_entity_deleted` and `on_record_changed`. |
| Docs | `docs/index.md`. |
| Table | `example_widgets`. |

The contract test and the Playwright smoke both exercise it (Settings cards by role with the example card present; the example record panel on a person). Step 1b's vertical slice runs through it.

## 8. `scripts/new-app.sh`

```
scripts/new-app.sh <slug> "<Name>"
```

Scaffolds an app that **passes** the contract test and the Vitest twin as generated. It writes `backend/apps/<slug>/` (manifest, router, api, entities, seed, settings, a migration, docs) from its own templates; it does not copy `apps/example`. The scaffold has a `<slug>.item` entity on `<slug>_items` and publishes `get_item`. When `frontend/src` exists it also writes `frontend/src/apps/<slug>/{contributions.ts,index.tsx}`. It refuses a reserved slug and any slug that extends, or is extended by, `core_` or an installed app's prefix.

## 9. Core packages contribute like apps

A core package is a folder `backend/core/<pkg>/` with an `__init__.py`. `registry.install()` discovers these modules in every core package; each is optional.

| Module | Exports | Contract |
|---|---|---|
| `router.py` | `router` | Included as-is. It sets its own `/api/...` prefix, and no manifest role guard is added, so its routes declare their own auth dependencies. |
| `hooks.py` | `HOOKS` | Same keys and signatures as an app's (`authorization.md` §3). |
| `jobs.py` | `JOBS` | Names `core.<job>` (`scheduler.md`). |
| `tools.py` | `get_tools()` | Names prefixed `core_`; the registry sets `app="core"` (`agent.md` §4). |
| `startup.py` | `on_startup()` | Called from the lifespan after migrations and seeds, inside the process lock, before the scheduler starts. |

A workstream adds a package. Nobody edits `main.py` or `registry.py` to add one.

## Tests that pin this

- Contract guard passes for `example`/`crm`/`todos` and fails `bad_app`.
- A member calling an admin-only app's API directly gets 403.
- Vitest: apps contract (contributions + index); bootSplit (every app lazy; contributions eager but tiny); grep guard that `apps/crm` contains no `contact_id|company_id`.
- Playwright: Settings cards by role (example app's card present) → example record panel on a person.

## Source

Build plan: Architecture → "The app contract"; §1 (`core_apps_state`, `core_settings`); §4 (manifest roles); §7 (CRM `api.py`, `recordPanels`); §8 (Todos `api.py`); §10 (launcher, settings registry); API block (orchestrator); Verification.
