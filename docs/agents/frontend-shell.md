# Frontend shell and the API block

**What this covers:** §10 and §12: what is lifted into `frontend/src/core` and `frontend/src/shared`, the app registry and routing, the bootSplit rule, the launcher, the settings registry and its sections, the core discovery seams and page paths, the Guide, Requests, ChangeLog, Backups and Jobs pages, type generation (including request bodies), the `--color-sf-*` tokens, and the full API block the frontend and backend are coded against.
**Who reads it:** W6 (shell), W1/W9 (settings cards), W3/W4/W5 (core pages), W11/W12/W13 (record, agent and CRM frontends), and every backend author whose routes the frontend calls.

## 1. Lifted from CakeCRM

| Piece | CakeCRM source | Notes |
|---|---|---|
| `src/shared/` | `frontend/src/shared/` subset (~900 of 8,307 lines) | Toast, confirm, icons, styles, `MobileMenuDrawer`, … Written here: `UserPicker` (the one user chooser, a type-to-search select over `GET /api/core/timeline/mentionable?q=`) and `users.ts` (its search and the shared name cache, `useUserNames`). |
| `BootFallback` | `frontend/src/core/components/BootFallback.tsx` (36) | |
| `ChunkErrorBoundary` | `frontend/src/core/components/ChunkErrorBoundary.tsx` (298) | |
| `useTheme` + contrast tests | `frontend/src/core/theme/useTheme.ts` (87) | Contrast guards run on shipped CSS. |
| `index.css` tokens | `frontend/src/index.css` (403) | Renamed `--color-sf-*`; ink ramp and status hues kept; stage hues move to the CRM as `--color-crm-stage-*` in `apps/crm/theme.css`. |
| `core/api/client.ts` | `frontend/src/core/api/client.ts` (143) | Cookie auth, `ApiError`, 401 redirect; plus `openapi-fetch` `createClient<paths>()`. |
| `bootSplit.test.ts` | `frontend/src/bootSplit.test.ts` (838) | Every app lazy. |
| `settingsSections.ts` | `frontend/src/crm/settingsSections.ts` (147) | Generalised to core cards + one section per app (from `contributions.ts`). |

## 2. App registry and routing

1. `vite-plugin-apps.ts` provides `virtual:springform-apps` from `backend/apps/*/app.json`.
2. `src/core/apps/registry.ts` zips the manifests with `import.meta.glob('../../apps/*/contributions.ts', { eager: true })` and `import.meta.glob('../../apps/*/index.tsx')` (lazy).
3. `Root.tsx` emits one `<Route path={`${path}/*`}>` per manifest.
4. Record pages render apps' `recordPanels` for their entity type, passing `{entityType, entityId}`.
5. Full contract in `apps-and-contracts.md` §5.

**Links inside an app are absolute.** Root mounts an app at `<path>/*`, and react-router 7 resolves a relative link inside a splat route against the whole URL, so `<Link to="deals">` seen from `/crm/deals` resolves to `/crm/deals/deals`. Write `/crm/deals`, or build the path from the app root the way Todos' `todoPath('/inbox')` does (`src/apps/todos/menu.ts`). The app's own `<Routes>` stay relative (`<Route path="deals">`).

### bootSplit rule

1. Every app's `index.tsx` is **lazy**; nothing in the boot chunk imports an app's screens.
2. `contributions.ts` is **eager but tiny**: lazy loaders only, no screen code.
3. `bootSplit.test.ts` enforces both.

## 3. New core screens (~1,900 lines + tests)

| Screen | Contract |
|---|---|
| Launcher | Tiles by role from `GET /api/core/apps`; hidden tiles shown to admins (`hidden: true`); **badge polling every 60 s while visible**. |
| Layout / Nav | `src/core/shell/Layout.tsx`: the header nav is Home, People, Organizations, then core `primary` items (`nav.tsx` seam below), then apps' `nav` items from `contributions.ts` for the apps the user receives. Core `menu` items and Settings sit in the user menu; the mobile drawer shows both lists plus Settings. |
| Settings | `/settings/<section id>`. Core sections come from each area's `settingsCards.ts` (seam below), plus one section per app from `contributions.ts` `settingsCards`, keyed by the manifest's `settings_cards[].id`; `admin_only` cards for admins only. The sections as built are in the Settings table below. Backups is a page (`/backups`), not a card. |
| Guide | `backend/core/guide/library.py` ports CakeCRM `help/library.py`. Core topics are `backend/core/docs/*.md`, slugged by file name. An app's `docs/index.md` is the topic `<slug>`, and its other `docs/<name>.md` files are `<slug>.<name>`. Each file opens with front matter: `title` (required, at most 80 characters), `summary` (optional, at most 200) and `order` (optional integer, default 1000). The body cap is **8,000 characters**. A bad topic (too long, an unknown key, a bad file name, a duplicate slug) is skipped and logged at runtime; a test loads strictly and fails CI on it. The library loads at startup and searches deterministically: title beats summary beats body, and ties break on slug. Routes: `GET /api/core/guide` (`[{slug, title, summary, app}]`, topics of core and of the apps on the caller's launcher), `GET /api/core/guide/search?q=&limit=` (`[{slug, title, snippet, app}]`; default 10, at most 20), `GET /api/core/guide/{slug}` (`{slug, title, summary, body_markdown, app}`). Pages: `/guide` (the index with search) and `/guide/:slug` (one topic), both from `src/core/pages/Guide.tsx` through `src/core/pages/routes.tsx`, with a Guide item in the user menu. |
| Requests | Form: title, app, description, plus the warning text from the setting `requests.warning_text` → a GitHub issue in `github.repo`, labelled `request` and `app:<slug>` (`app` defaults to `core`), created with the token in the setting `github.token` (`backend/core/requests/github.py`). Routes: `POST /api/core/requests`, `GET /api/core/requests`, `GET /api/core/requests/config`, `POST /api/core/requests/refresh`. Board from `core_requests`, refreshed every 15 min (`core.requests_refresh`). |
| ChangeLog | Filters: app, user, entity. Rows authorized per row (`records.md` §8). |
| Backups | List, back up now, download, show the encryption key once (`deploy.md`). |
| Jobs | Runs, run now; dead outbox rows (`scheduler.md`, `database-and-transactions.md`). |
| Sheets admin | No page: connected sheets, status and refresh are the Google Sheets card in Settings → Integrations (`src/core/integrations/`, `sheets-and-export.md`). |

`src/core/settings/` holds the registry (`settingsSections.ts`) and the shell's own sections (`settingsCards.ts`: Workspace, Apps, Data). Every other area contributes through its own `settingsCards.ts` and does not edit `settings/`.

Core areas contribute to the shell by discovery, like apps; nobody edits `Root.tsx`, `Layout.tsx` or `settings/` to add one. Each module is an eager glob, so it holds only data and `lazy()` loaders:

| File | Default export | Contract |
|---|---|---|
| `src/core/<area>/routes.tsx` | `CoreRoute[]`, `{path, element, public?, admin?}` (`src/core/shell/coreRoutes.ts`) | Shell routes render inside the signed-in Layout, admin ones behind `RequireAdmin` (a member sees a Not allowed page at that URL); `public` ones (an invite or reset link) render beside `/login`. Paths have no leading slash, and the first segment must be a reserved slug. |
| `src/core/<area>/nav.tsx` | `CoreNavItem[]`, `{to, label, icon, placement: "primary" \| "menu", adminOnly?, order?}` (`src/core/shell/coreNav.ts`) | `icon` is an element sized 18, not a name. `primary` items sit in the header nav after Organizations and before the apps (keep it to one per area); `menu` items in the user menu and the mobile drawer. Lower `order` first, default 100. |
| `src/core/<area>/settingsCards.ts` | `SettingsSection[]`, `{id, label, order?, cards: [{id, title, adminOnly, Card}]}` (`src/core/settings/settingsSections.ts`) | The section id is the URL segment `/settings/<id>`. A section shows only when one of its cards does. Core sections sort by `order` (default 0) and member-visible sections take a lower `order` than admin-only ones; app sections follow. |

Core page paths, pinned. Add a new one only through a `routes.tsx` module, with its first segment added to `RESERVED_SLUGS` in `backend/core/registry.py`:

| Path | Declared in | Notes |
|---|---|---|
| `/`, `/settings/*` | `src/core/Root.tsx` | The launcher (index) and Settings, inside the signed-in Layout. |
| `/login`, `/setup` | `src/core/Root.tsx` | Outside the Layout. |
| `/invite/:token`, `/reset-password/:token` | `src/core/auth/routes.tsx` | `public`. The backend mails `PUBLIC_URL/invite/<token>` and `PUBLIC_URL/reset-password/<token>` links. |
| `/people`, `/people/:id`, `/organizations`, `/organizations/:id` | `src/core/contacts/routes.tsx` | Header links come from `Layout.tsx`. |
| `/guide`, `/guide/:slug`, `/requests`, `/changelog`, `/jobs` | `src/core/pages/routes.tsx` | `/jobs` is `admin`. Menu items in `src/core/pages/nav.tsx`. |
| `/backups` | `src/core/backups/routes.tsx` | `admin`; an admin-only menu item. |
| `/whisk/*` | `src/core/agent/routes.tsx` | One splat for `/whisk` and `/whisk/<conversation id>`; the only `primary` nav item. |
| `/reports`, `/reminders`, `/notifications` | `src/core/records/routes.tsx` | Reminders and Reports are menu items; Notifications opens from the header bell. |

Each first segment is a reserved slug (`apps-and-contracts.md` §1).

Settings sections as built, in the order a user sees them (a member sees only the sections with a card for members):

| Order | `/settings/<id>` | Label | Cards | Declared in |
|---|---|---|---|---|
| 5 | `account` | Account | Profile, Security (members) | `src/core/auth/settingsCards.ts` |
| 8 | `notifications` | Notifications | Push notifications (members) | `src/core/records/settingsCards.ts` |
| 10 | `workspace` | Workspace | Workspace (members read, admins edit; includes the timezone) | `src/core/settings/settingsCards.ts` |
| 20 | `apps` | Apps | Apps (members read, admins hide and order) | `src/core/settings/settingsCards.ts` |
| 25 | `mcp` | MCP | MCP connector (members) | `src/core/mcp/settingsCards.ts` |
| 30 | `users` | Users | Users (admin) | `src/core/auth/settingsCards.ts` |
| 35 | `records` | Records | Custom fields (admin) | `src/core/records/settingsCards.ts` |
| 40 | `signin` | Sign-in | Google sign-in (admin) | `src/core/auth/settingsCards.ts` |
| 50 | `integrations` | Integrations | GitHub (`github.repo`, `github.token`, `requests.warning_text`), Google Sheets (admin) | `src/core/integrations/settingsCards.ts` |
| 60 | `data` | Data | Export, Files (`files.max_bytes`) (admin) | `src/core/settings/settingsCards.ts` |
| 70 | `ai` | AI | Providers, Agents, Memory, Nightly run (admin) | `src/core/agent/settingsCards.ts` |
| 80 | `mcp_servers` | MCP servers | Connected MCP servers (admin) | `src/core/mcp_servers/settingsCards.ts` |
| after core | `<slug>` | the app's name | The manifest's `settings_cards`, in launcher order: CRM (`crm`, admin), Todos (`todos`, members), Example (`example`, admin) | `src/apps/<slug>/contributions.ts` |

There is no Sheets admin page, so `sheets` stays reserved but unrouted. `/backups` is `src/core/backups/` (route plus an admin-only user-menu item). The header's install name comes from `GET /api/core/workspace` through `settings/useWorkspace.ts`.

## 4. Type generation (§12)

1. `scripts/gen-types.sh` builds the app with `create_app()` and a throwaway `DATA_DIR`, never running the lifespan, so **no database** is opened; building the app registers the routes. It dumps `app.openapi()`, runs `openapi-typescript` from the frontend's devDependencies, and writes `frontend/src/core/api/types.gen.ts`.
2. `types.gen.ts` is **committed**. CI regenerates it and fails on diff.
3. `core/api/client.ts` uses `openapi-fetch` `createClient<paths>()`.
4. Apps use `paths['/api/todos/…']` and `components['schemas'][…]`.
5. Routers are tagged by slug with stable `operationId`s so generated names do not churn.
6. In a fork, `types.gen.ts` is a generated file and is exempt from the scope check (`forks.md`).

**Request bodies are not the generated schema as is.** openapi-typescript marks every field that has a server-side default as required, so `components['schemas']['DealIn']` demands `currency`, `stage`, `notes` and the rest even though the server fills them. The operation's own body type, `paths['/api/crm/deals']['post']['requestBody']['content']['application/json']`, is that same schema, so it has the same problem. Type a request body as a `Partial<>` of the schema plus the fields the server requires, as `src/apps/crm/api.ts` does:

```ts
/** The generated DealIn marks defaulted fields required; the server fills them. */
export const createDeal = (body: Partial<DealIn> & Pick<DealIn, 'title'>) => postJson<Deal>(`${BASE}/deals`, body);
```

Responses are fine as generated: a defaulted field is always present in what the server returns.

## 5. Frontend tests

| Test | Rule |
|---|---|
| Apps contract | Every manifest has `contributions.ts` + `index.tsx` and vice versa; every settings card id has a loader; no `../<otherapp>/` imports. |
| bootSplit | Every app lazy; contributions eager but tiny. |
| Contrast | Guards on shipped CSS. |
| Components | `Timeline`, `CustomFields` by type, `SavedViewBar` stale-version refusal. |
| CRM grep | `apps/crm` contains no `contact_id\|company_id`. |
| TZ pin | Vitest runs with a non-UTC `TZ`. |
| Types | `gen-types` diff clean. |

## 6. The API block

Two Step 1 agents code against this block. It is reproduced verbatim.

```
GET  /api/auth/status  -> {setup_required: bool, google: bool, preview: bool}
POST /api/auth/setup   {token, email, name, password} -> 200 {user} + cookie; 404 when setup is not required or the token is wrong
POST /api/auth/login   {email, password} -> 200 {user} + cookie; 401 {detail:"invalid_credentials"}; 429 when rate-limited
POST /api/auth/logout  -> 204, clears the cookie
POST /api/auth/preview {role} -> 200 {user} + cookie (PREVIEW_MODE only, else 404)
GET  /api/me           -> {id, email, name, role: "admin"|"member", tz}; 401 when not signed in
GET  /api/core/apps    -> [{slug, name, description, path, icon, roles, order, badge, hidden, settings_cards, version}] for the caller's role; admins also receive hidden apps with hidden:true
GET  /api/health       -> {version, sqlite_version, fts5, preview, apps:[slug], last_backup_at}   (no auth)
GET  /up               -> 200 "ok"   (no auth)
GET  /api/example/widgets[?person_id=]   -> [Widget]  Widget = {id, name, color, owner_user_id, person_id, is_private, created_at, updated_at}
POST /api/example/widgets {name, color?, is_private?, person_id?} -> Widget
GET  /api/example/widgets/{id}           -> Widget; 404 when missing or not readable
PATCH /api/example/widgets/{id} {name?, color?, is_private?, person_id?} -> Widget
GET  /api/example/badge                  -> {count, label?}
GET  /api/core/timeline?entity_type=&entity_id=  -> [{id, kind: "note"|"comment"|"field_change"|"system", body, changes, author:{id,name}, created_at}]
POST /api/core/timeline {entity_type, entity_id, body} -> the new entry
GET  /api/core/files?entity_type=&entity_id=  -> [{id, filename, mime_type, byte_size, sha256, created_at, uploaded_by:{id,name}}]
POST /api/core/files  multipart fields entity_type, entity_id, file -> File
GET  /api/core/files/{id}/download   -> bytes, Content-Disposition: attachment
DELETE /api/core/files/{id}          -> 204
Badge routes return {count, label?}. Errors: `{detail}`; 401 not signed in, 403 denied, 404 missing or not readable, 422 invalid.
```

Pinned since the block was written (the block stays verbatim; these refine it):

- **Errors:** 404 when a record is missing or not readable, for reads and writes alike; 403 only when the record is readable but not writable, or a role-guarded route refuses the caller (`authorization.md` §2). The code also answers 409 for conflicts (`stale_view`, `duplicate_name`, `backup_in_progress`), 410 (`file_missing`, `key_already_shown`), 413 `file_too_large`, 429 for rate limits and throttles, 502 (`sheets_unavailable`, `github_error`) and 503 (`push_unavailable`, `scheduler_not_running`).
- **Login:** with 2FA on and an untrusted browser, `POST /api/auth/login` answers 200 `{totp_required: true, challenge}` with no cookie; `POST /api/auth/login/totp` finishes it (`auth.md` §6).
- **Timeline:** `GET` pages with `?before=<id>&limit=` (default 50, at most 200), newest first. `POST` also accepts `kind` (`note` by default, `comment` allowed). Mentions in `body` are `@[Name](user:ID)`, and `GET /api/core/timeline/mentionable?q=` feeds the picker (`records.md` §1).
- **Files:** `File` also carries `has_thumb`, and `GET /api/core/files/{id}/thumb` serves the thumbnail. `POST` returns 201 for a new attachment and 200 with the existing row for the same bytes on the same record. Download answers 410 `file_missing` when the bytes are gone. `DELETE` requires write access to the parent record (`records.md` §2).

### Routes documented elsewhere (each shape is pinned in its doc)

| Route | Doc | Workstream |
|---|---|---|
| `/api/core/contacts/{people,organizations,links,addresses,channels}` | `contacts.md` | W2 |
| `GET /api/core/reports/{key}/csv` | `records.md` | W2 |
| `/api/core/changelog` | `records.md` | W3 |
| `GET /api/core/export` (ZIP) | `sheets-and-export.md` | W4 |
| `POST /api/core/sheets/{id}/refresh` | `sheets-and-export.md` | W4 |
| `GET /api/agent/status`, `POST /api/agent/confirm`, chat SSE and other `/api/agent/...` | `agent.md` | W9 / W12 |
| `/mcp/<token>`, `/mcp` (bearer) | `mcp.md` | W14 |
| `/api/todos` + `/api/todos/badge` + `/api/todos/for/{entity_type}/{entity_id}` | Todos app | W7 |
| `/api/crm/...` | CRM app | W10 |
| Google start/callback, invites, reset, TOTP, users admin | `auth.md` | W1 |
| `POST /api/core/jobs/{name}/run` (admin run now) | `scheduler.md` | W3 |

The Todos routes `/api/todos/badge` and `/api/todos/for/{entity_type}/{entity_id}` are the app router's `/badge` and `/for/...` under its `/api/todos` mount.

## Tests that pin this

- Vitest: apps contract (contributions + index), bootSplit (every app lazy; contributions eager but tiny), contrast guards on shipped CSS, `Timeline`, `CustomFields` by type, `SavedViewBar` stale-version refusal, grep guard that `apps/crm` contains no `contact_id|company_id`; `gen-types` diff clean.
- Playwright (`PREVIEW_MODE=1`, seeded): pick role → launcher by role → … → Guide → Requests validation → Settings cards by role (example app's card present) → example record panel on a person → Back up now creates a file.

## Source

Build plan: §10 (all), §12 (all), Architecture (frontend tree, app contract frontend), §14 (bootSplit, TZ pin), Step 1 (frontend pieces), Step 2 W5/W6, Verification. API block (orchestrator), verbatim.
