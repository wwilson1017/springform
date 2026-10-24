# Frontend shell and the API block

**What this covers:** §10 and §12: what is lifted into `frontend/src/core` and `frontend/src/shared`, the app registry and routing, the bootSplit rule, the launcher, the settings registry, the Guide, Requests, ChangeLog, Backups, Jobs and Sheets pages, type generation, the `--color-sf-*` tokens, and the full API block the frontend and backend are coded against.
**Who reads it:** W6 (shell), W1/W9 (settings cards), W3/W4/W5 (core pages), W11/W12/W13 (record, agent and CRM frontends), and every backend author whose routes the frontend calls.

## 1. Lifted from CakeCRM

| Piece | CakeCRM source | Notes |
|---|---|---|
| `src/shared/` | `frontend/src/shared/` subset (~900 of 8,307 lines) | Toast, confirm, icons, styles, `MobileMenuDrawer`, … |
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

### bootSplit rule

1. Every app's `index.tsx` is **lazy**; nothing in the boot chunk imports an app's screens.
2. `contributions.ts` is **eager but tiny**: lazy loaders only, no screen code.
3. `bootSplit.test.ts` enforces both.

## 3. New core screens (~1,900 lines + tests)

| Screen | Contract |
|---|---|
| Launcher | Tiles by role from `GET /api/core/apps`; hidden tiles shown to admins (`hidden: true`); **badge polling every 60 s while visible**. |
| Layout / Nav | Core layout; apps' `nav` items from `contributions.ts`. |
| Settings | Cards: Workspace (incl. timezone, and `PUBLIC_URL` shown read-only), Apps (order/hide), GitHub token, Sheets key, Backups, Export, AI, MCP, Security, Users. Plus one section per app from `contributions.ts` `settingsCards`, keyed by the manifest's `settings_cards[].id`; `admin_only` cards for admins only. |
| Guide | `core/docs.py` ports CakeCRM `help/library.py`: front matter, **8k cap**, lazy warm, **deterministic search** over core docs (`backend/core/docs/`) and every app's `docs/`. |
| Requests | Form: title, app, description, plus configurable warning text → a GitHub issue labelled `app:<slug>`, created with a fine-grained token stored in settings (`core/github.py`). Board from `core_requests`, refreshed every 15 min (`core.requests_refresh`). |
| ChangeLog | Filters: app, user, entity. Rows authorized per row (`records.md` §8). |
| Backups | List, back up now, download, show the encryption key once (`deploy.md`). |
| Jobs | Runs, run now; dead outbox rows (`scheduler.md`, `database-and-transactions.md`). |
| Sheets admin | Connected sheets, status, refresh (`sheets-and-export.md`). |

W6 owns the settings registry and `settings/`. W1 (Security, Users) and W9 (AI, MCP) contribute cards **through the registry W6 defines in Step 1**; they do not edit `settings/`.

Core page paths: `/`, `/login`, `/setup`, `/invite/:token`, `/people`, `/people/:id`, `/organizations`, `/organizations/:id`, `/settings/*`, `/guide`, `/requests`, `/changelog`, `/backups`, `/jobs`, `/whisk`, `/reminders`, `/notifications`. Each first segment is a reserved slug (`apps-and-contracts.md` §1).

Open: the Sheets admin page's path (it is not in the list above; `sheets` is reserved). Open: the settings registry's card interface, and where core cards are declared. Open: the `core_requests` columns, the Requests routes, and where the "configurable warning text" is stored. Open: the Guide's routes. (The 8k cap is the donor's `MAX_TOPIC_CHARS = 8000`, characters per topic.)

## 4. Type generation (§12)

1. `scripts/gen-types.sh` dumps `app.openapi()` **without a DB** (routers are mounted at import), runs `openapi-typescript`, and writes `frontend/src/core/api/types.gen.ts`.
2. `types.gen.ts` is **committed**. CI regenerates it and fails on diff.
3. `core/api/client.ts` uses `openapi-fetch` `createClient<paths>()`.
4. Apps use `paths['/api/todos/…']` and `components['schemas'][…]`.
5. Routers are tagged by slug with stable `operationId`s so generated names do not churn.
6. In a fork, `types.gen.ts` is a generated file and is exempt from the scope check (`forks.md`).

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

- **Errors:** 404 when a record is missing or not readable, for reads and writes alike; 403 only when the record is readable but not writable, or a role-guarded route refuses the caller (`authorization.md` §2).

### Routes named elsewhere in the plan (shape to be pinned by the implementing workstream)

| Route | Doc | Workstream |
|---|---|---|
| `/api/core/contacts/{people,organizations,links,addresses,channels}` | `contacts.md` | W2 |
| `GET /api/core/reports/{key}?format=csv` | `records.md` | W2 |
| `/api/core/changelog` | `records.md` | W3 |
| `GET /api/core/export` (ZIP) | `sheets-and-export.md` | W4 |
| `POST /api/core/sheets/{id}/refresh` | `sheets-and-export.md` | W4 |
| `GET /api/agent/status`, `POST /api/agent/confirm`, chat SSE and other `/api/agent/...` | `agent.md` | W9 / W12 |
| `/mcp/<token>`, `/mcp` (bearer) | `mcp.md` | W14 |
| `/api/todos` + `/api/todos/badge` + `/api/todos/for/{entity_type}/{entity_id}` | Todos app | W7 |
| `/api/crm/...` | CRM app | W10 |
| Google start/callback, invites, reset, TOTP, users admin | `auth.md` | W1 |
| `run_now` (admin) | `scheduler.md` | W3 |

Open: `/api/todos/badge` and `/api/todos/for/...` are the plan's `/badge` and `/for/...` under the Todos mount; the full paths are inferred from the mount rule.

## Tests that pin this

- Vitest: apps contract (contributions + index), bootSplit (every app lazy; contributions eager but tiny), contrast guards on shipped CSS, `Timeline`, `CustomFields` by type, `SavedViewBar` stale-version refusal, grep guard that `apps/crm` contains no `contact_id|company_id`; `gen-types` diff clean.
- Playwright (`PREVIEW_MODE=1`, seeded): pick role → launcher by role → … → Guide → Requests validation → Settings cards by role (example app's card present) → example record panel on a person → Back up now creates a file.

## Source

Build plan: §10 (all), §12 (all), Architecture (frontend tree, app contract frontend), §14 (bootSplit, TZ pin), Step 1 (frontend pieces), Step 2 W5/W6, Verification. API block (orchestrator), verbatim.
