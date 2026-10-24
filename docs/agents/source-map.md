# Source map and provenance

**What this covers:** where each Springform path comes from: donor repo, donor path, approximate line counts, and whether it is lifted, ported or new; the donor commit shas this map was built against; and the provenance rule for every lifted file.
**Who reads it:** every implementer who lifts or ports code, and whoever maintains `docs/PROVENANCE.md`.

## Donors

| Repo | Visibility | Branch | Head sha recorded for this map |
|---|---|---|---|
| CakeCRM (`wwilson1017/CakeCRM`) | public | `main` | `3a71a7dfa0ea2bb7b38285e5cfaba2b2533fad13` |
| chatty (`wwilson1017/chatty`) | public | `master` | `50d9e9547af3568e265bfd00fcc112897d5d0117` |
| todo-gtd | private | `master` | `f2f74d813a8778339dc18d9676c7be1d5b6bc288` |
| cake_os | private | `master` | `096fee2272eed05961c51fe9fc81c4cfb38fd072` |

All lifted code is the author's sole authorship (Decisions, License); the provenance check below confirms it per file. A lift records the sha it actually copied from, which may be newer than this table; `git fetch` the donor first.

**Actions:**

| Action | Meaning |
|---|---|
| lift | Copy, changing only what the plan names (SQL dialect, imports, table names, cut features). Needs a `docs/PROVENANCE.md` row. |
| port | Rewrite onto Springform's shapes (SQLite, core directory, `_in` forms) keeping the donor's behaviour; donor line ranges cited. Needs a `docs/PROVENANCE.md` row. |
| new | No donor. |

**Lines:** "plan" figures are the plan's (`donor → target` where it gives both). "head" figures were counted at the shas above. A `~` range is approximate.

## Platform core (SQLite rules, §1, §11)

| Springform path | Donor | Donor path | Lines | Action | Notes |
|---|---|---|---|---|---|
| `backend/core/db.py` (connection, `transaction()`) | todo-gtd | `backend/db.py` 499–540, 782–825 | file 825 (head) | lift | Pragmas per the plan (`synchronous=NORMAL`; donor has `FULL`); add `NestedTransaction`, outbox, nudge. |
| `backend/core/db.py` (migration runner) | CakeCRM | `backend/core/postgres.py:181-248` | file 262 (head) | port | Advisory lock → write lock; checksums, explicit `ROLLBACK`, `requires_core` check are new. |
| `backend/core/localtime.py` | CakeCRM | `backend/core/localtime.py` | 67 (head) | lift | |
| `backend/core/clock.py` | — | — | — | new | `now_iso()`, `normalize`. |
| `backend/core/secrets.py` | CakeCRM | `backend/core/secret_store.py` | 309 (head) | lift | Minus keychain. Key: env → `/data/.encryption-key` → generated. |
| `backend/core/secrets.py` (encryption) | CakeCRM | `backend/core/encryption.py` | 151 (head) | lift | `enc:v1:` format. Lands in `backend/core/secrets.py` with the key ladder, not as its own module. |
| `backend/core/backup/service.py` | todo-gtd | `backend/backup.py` | 103 (head) | port | Adapted: recovery sets, manifests written last, blob pinning, key fingerprint. |
| `scripts/restore.sh` | — | — | — | new | |
| `backend/core/scheduler.py` | todo-gtd | `backend/main.py` `_tick` (line 75) | ~300 target (plan) | port | Loop shape only; jobs, guard, semaphore, statuses are new. |
| `backend/core/ratelimit.py` | todo-gtd | `backend/ratelimit.py` | 119 (head) | lift | Not built yet (planned for the MCP inbound limiter, §6). Login rate limits are a sliding window over `core_login_attempts` in `backend/core/auth/service.py`. |
| `backend/core/logscrub.py` | — | — | — | — | Not built yet. Open (pinned by the implementing workstream, which updates this doc): source not stated (todo-gtd has `backend/logscrub.py`, 88 at head). |
| `backend/core/registry.py`, `entities.py`, `outbox.py`, `settings.py`, `errors.py`, `pagination.py`, `changelog.py`, `preview.py`, `platform/` | — | — | `entities.py` ~260 (plan), about 195 built | new | No `kv.py`: install settings are `settings.py` and `platform/keys.py`. |
| `backend/main.py` | — | — | — | new | |

## Login (§2)

≈1,450 lifted / 650 new (plan).

| Springform path | Donor | Donor path | Lines | Action | Notes |
|---|---|---|---|---|---|
| `backend/core/auth/` (session, JWT, deps) | CakeCRM | `backend/core/auth.py` | 486 (plan, head) | lift | SQL-only port: `%s`→`?`, `FOR UPDATE`→`transaction()`, `now()`→`now_iso()`. |
| `backend/core/auth/totp.py` | CakeCRM | `backend/core/auth_2fa.py` | 407 (plan, head) | lift | |
| `backend/core/auth/service.py` | CakeCRM | `backend/users/service.py` | 396 (plan) / 395 (head) | lift | |
| `backend/core/auth/bootstrap.py` | CakeCRM | `backend/users/bootstrap.py` | 231 (plan, head) | lift | Setup token added (new). |
| `backend/core/auth/users_router.py` | CakeCRM | `backend/users/router.py` | 155 (head) | lift | |
| `backend/core/auth/google.py` | CakeCRM | `backend/gmail/oauth.py` (code exchange only) | ~200 target (plan); donor 86 (head) | new + lift | OIDC checks and linking are new. |
| `backend/core/auth/mail.py` | todo-gtd | `backend/signin.py` `_send` (line 61) | file 211 (head) | lift | Resend. |
| `backend/core/auth/csrf.py`, `invites.py`, `jwt.py`, `router.py` | — | — | — | new | Split of `auth.py` is not fixed by the plan. |
| `frontend/src/core/auth/AuthContext.tsx` | CakeCRM | `frontend/src/core/auth/AuthContext.tsx` | 227 (head) | lift | Drop sessionStorage/BroadcastChannel; `GET /api/me` with cookie. |
| `frontend/src/core/auth/LoginPage.tsx` | CakeCRM | `frontend/src/login/LoginPage.tsx` | 181 (head) | lift | + Google button + preview picker. |
| `SetupPage`, `InvitePage`, Security card, Users card | — | — | — | new | |

## Contacts (§3)

| Springform path | Donor | Donor path | Lines | Action | Notes |
|---|---|---|---|---|---|
| `backend/core/contacts/service.py` | CakeCRM | `backend/crm/service.py:315-1031` | ~650 (plan); file 4,172 (head) | port | Onto `core_people` / `core_organizations` / links / channels. |
| `backend/core/contacts/service.py` (`find_duplicates`) | CakeCRM | `backend/crm/analytics_service.py:234-330` | file 732 (head) | port | `find_duplicates` at line 317 at head. |
| `backend/core/contacts/api.py`, `router.py` | — | — | — | new | |
| `frontend/src/core/contacts/ContactPicker` | CakeCRM | `frontend/src/crm/components/RecordCombobox.tsx` + `frontend/src/crm/dealLinkPickers.ts` | 458 + 63 (head) | lift | Already generic. |
| `frontend/src/core/contacts/` pages + forms | CakeCRM | `frontend/src/crm/ContactsPage.tsx`, `ContactDetailPage.tsx`, `CompaniesPage.tsx`, `CompanyDetailPage.tsx`, `components/ContactForm.tsx`, `components/CompanyForm.tsx` | ~1,350 (plan); 139 + 391 + 104 + 243 + 326 + 148 = 1,351 (head) | lift | Detail pages render apps' `recordPanels`. |

## Record services (§4 table)

| Springform path | Donor | Donor path | Lines (plan donor → target) | Action | Notes |
|---|---|---|---|---|---|
| `backend/core/entities.py` | — | — | ~260 | new | |
| `backend/core/timeline/` | CakeCRM | `backend/crm/chatter_service.py`, `backend/crm/mention_notify.py` | 345 → 280; 84 | port | Scoring/touch imports at `chatter_service.py:25` become CRM subscribers. |
| `backend/core/files/` | CakeCRM | `backend/crm/attachment_service.py`, `backend/core/thumbnails.py` | 379 → 330; 260 (plan) / 245 (head) | port | Bytes move to `/data/files`; publication and sweep protocol new. |
| `backend/core/fields/` | CakeCRM | `backend/crm/field_service.py` | 427 → 400 | port | `VALID_ENTITY_TYPES` → `entities.get`. |
| `backend/core/views/` | CakeCRM | `backend/saved_views/` | 356 → 320 | port | `Json()` → `json.dumps`. |
| `backend/core/reports/` | — | — | new ~250 | new | `report_service.py` (477) stays CRM-owned. The `_cell` lift lives in `backend/core/export/csv_export.py`. |
| `backend/core/notifications/` | CakeCRM | `backend/notifications/` | 767 → 650 | port | Telegram branch → `register_channel`. |
| `backend/core/reminders/` | CakeCRM | `backend/reminders/` | 767 → 700 | port | `recurrence.py` unchanged; `crm.service`/`gtd_common` imports cut. |
| `frontend/src/core/records/` | CakeCRM | `frontend/src/crm/components/{NotesThread,ActivityTimeline,NoteComposer,MentionPicker,NoteAttachments,CustomFieldsSection,CustomFieldInputs,CustomFieldSettings,NotificationsBell,ReminderForm}.tsx`, `useCustomFieldsForm.ts`, `chatterAttachments.ts`, `RemindersPage.tsx`; `frontend/src/shared/collection/{SavedViewsMenu.tsx,savedViews.ts}` | ~2,700 lifted + 400 new (plan); head: 276, 232, 323, 185, 137, 165, 72, 215, 209, 205, 84, 156, 206; 396, 83 | lift | Donor files by name; the plan gives totals and the `NotesThread` + `ActivityTimeline` merge. `ReportTable` new. |

## Whisk (§5 table)

| Springform path | Donor | Donor path | Lines (plan) | Action | Notes |
|---|---|---|---|---|---|
| `backend/core/agent/providers/` | CakeCRM | `backend/providers/` (Anthropic and OpenAI only; Google, Ollama, Together, model listing, tier inference and pricing not lifted) | about 590 built (head: 3,038 py) | lift | `credentials.py` rewritten for `core_agent_providers` only; `fake.py` and `windows.py` new. |
| `backend/core/agent/spec.py`, `registry.py` | CakeCRM | `backend/assistant/registry.py`, `backend/assistant/confirm_tier.py` (folded into `spec.py`) | 212 → 150 / 160 new | port | Sources = core + apps + MCP; atomic swap. |
| `backend/core/agent/{engine,history,assembly,compaction,delimiters,write_budget}.py` | CakeCRM | `backend/assistant/` same names | ~2,500 (head: 840, 674, 318, 566, 370, 53) | lift | JSONB→TEXT; Gmail/page bindings cut; `turns.py` (564) skipped in v1; `uploads.py` not lifted. |
| `backend/core/agent/deferred.py` | chatty | `backend/core/agents/deferred_tools.py` | 350 (head 410) | lift | Group key = app slug, threshold 100. |
| `backend/core/agent/agents.py` | CakeCRM | `backend/assistant/identity.py` | 300 (head 737) | port | Rows, not a singleton. |
| `backend/core/memory/facts.py` | CakeCRM | `backend/memory/service.py` (Chatty's memory as CakeCRM ported it) | part of 1,800 | port | FTS5, temporal facts, soft invalidation. Chatty's `db.py` was not lifted directly. |
| `backend/core/memory/context_files.py` | CakeCRM | `backend/context_files/service.py` | part of 1,800 (head 1,274 py) | port | One module; tsvector → FTS5. Chatty's context-file layout. |
| `backend/core/memory/observer.py`, `dreaming.py`, `jobs.py` | chatty, CakeCRM | `backend/core/agents/memory/observer.py` (329) and CakeCRM `backend/memory/observer.py` | 580 | lift + new | The observer is lifted; dreaming is new plain Python (merges duplicate facts, no model call); Chatty's `dreaming/` was not lifted. Nightly, setting-gated. |
| `backend/core/agent/router.py` | CakeCRM | `backend/assistant/router.py` | 250 (head 428) | port | Minus uploads. |
| `backend/core/mcp/` (inbound server) | todo-gtd | `backend/mcp_server.py` HTTP section | 250 | new + lift | Plan cites ~700–946; at head the section is 832–946. Donor uses FastMCP; Springform uses the `mcp` low-level `Server`. |
| `backend/core/mcp_servers/` (outbound client) | — | — | 320 | new | |
| `frontend/src/core/agent/WhiskPage` | chatty | `frontend/src/agent/AgentPage.tsx` | 967 → ~400 | port | |
| `frontend/src/core/agent/AgentChatPanel` | chatty | `frontend/src/agent/components/AgentChatPanel.tsx` | 880 → ~500 | port | |
| `frontend/src/core/agent/useAgentChat` | chatty | `frontend/src/agent/hooks/useAgentChat.ts` | 653 → ~400 | port | |
| `frontend/src/core/agent/AgentMessageBubble` | chatty | `frontend/src/agent/components/AgentMessageBubble.tsx` | 515 → ~350 | port | |
| `ConversationSidebar`, `useConversations` | chatty | `frontend/src/agent/components/ConversationSidebar.tsx` (273), `frontend/src/agent/hooks/useConversations.ts` (197) | head | lift | |
| `MarkdownContent` | chatty | `frontend/src/agent/components/MarkdownContent.tsx` | 94 (head) | lift | As is. |
| `ContextFilesPage` | chatty | `frontend/src/agent/components/AgentContextEditor.tsx` | 453 (head) | port | |
| `ProviderSetup` + keys card | CakeCRM | `frontend/src/setup/ProviderSetup.tsx` | 129 (head) | lift | |
| MCP links / servers cards | — | — | ~300 | new | |

## CRM app (§7)

~9,500 backend lines kept of 17,945 (`backend/crm/`, head total matches); ≈20k frontend lines retained.

| Springform path | Donor | Donor path | Lines | Action | Notes |
|---|---|---|---|---|---|
| `backend/apps/crm/deals.py` | CakeCRM | `backend/crm/service.py:1032-2284` | ~1,250 | port | |
| `backend/apps/crm/dashboard.py` | CakeCRM | `backend/crm/service.py:2742-3450` + `backend/crm/today_service.py` (325) | ~1,030 | port | |
| `backend/apps/crm/analytics.py` | CakeCRM | `backend/crm/analytics_service.py` | 732 (head) | port | By name; Python bucketing in install tz. |
| `backend/apps/crm/scoring.py` | CakeCRM | `backend/crm/scoring_service.py` | 667 (head) | port | By name. |
| `backend/apps/crm/touch_count.py` | CakeCRM | `backend/crm/touch_count_service.py` | 1,253 (head) | port | Thread cut; `touch_dirty` + job `crm.touch_count`. |
| `backend/apps/crm/provenance.py` | CakeCRM | `backend/crm/provenance_service.py` | 301 (head) | port | By name. |
| `backend/apps/crm/stage_criteria.py` | CakeCRM | `backend/crm/stage_criteria.py` | 62 (head) | port | |
| `backend/apps/crm/seed.py` | CakeCRM | `backend/crm/seed_data.py` | 452 (head) | port | Writes through `contacts.api`. |
| `backend/apps/crm/smart_import.py` | CakeCRM | `backend/crm/smart_import.py` | 363 (head) | port | |
| `backend/apps/crm/tools.py` | CakeCRM | `backend/crm/tools.py` | 2,471 (head) | port | Todo/reminder/GTD tools dropped. |
| `backend/apps/crm/router.py` | CakeCRM | `backend/crm/router.py` | 1,887 (head); 72 → ~42 routes | port | |
| `backend/apps/crm/reports.py` | CakeCRM | `backend/crm/report_service.py` | 477 (head) | port | |
| `backend/apps/crm/activity.py` | CakeCRM | `activity_log` code | — | port | Open (pinned by the implementing workstream, which updates this doc): donor range not stated. |
| `backend/apps/crm/entities.py`, `hooks.py`, `api.py`, `migrations/20261101000000_crm_init.sql` | — | — | — | new | |
| `backend/apps/crm/docs/` | CakeCRM | `backend/help/content/` | 12 topics (of 44 files at head) | port | |
| Dropped | CakeCRM | GTD cluster (`gtd_*`, `todo_*`; 2,912 backend + 6,195 frontend), `alerts`, gmail/gmail_scan/telegram, the built-in assistant (Baker), `MemoryPage`, `AssistantLauncher`, `setup_status_service.py` | — | — | |
| `frontend/src/apps/crm/` | CakeCRM | `frontend/src/crm/` (27,601 non-test lines at head) | ≈20k retained | port | `PipelinePage.tsx` (2,164, ~80 lines change), `components/DealDetailBody.tsx` (1,235, ~60 lines change); contact swap = one scripted rename commit (118 refs in 32 files). Contacts/companies pages deleted. |

## Todos app (§8)

| Springform path | Donor | Donor path | Lines | Action | Notes |
|---|---|---|---|---|---|
| `backend/apps/todos/service.py` | todo-gtd | `backend/service.py` | 1,054 → ~800 | port | Keep status model, `_spawn_next_occurrence` (line 379), today/review/changes/contexts/filters. Drop lists, caps, Stripe, lifecycle, capture tokens, `X-List`, landing/connect. |
| `backend/apps/todos/router.py` | todo-gtd | `backend/router.py:191-322` (`build_router`) | file 789 (head) | port | At `/api/todos` + `/badge` + `/for/...`. |
| `backend/apps/todos/api.py`, `entities.py`, `tools.py`, migrations | — | — | — | new | Permission model and visibility are new. |
| `frontend/src/apps/todos/` | todo-gtd | `frontend/src/apps/todo-gtd/` | 8,759 lines, ~2,900 dropped | port | Minus account/landing/connect/capture; `api.ts` on core `fetchJson`; visibility toggle + assignee picker new. |
| Todos tests | todo-gtd | `frontend/src/apps/todo-gtd/` tests | ~5,000 of 8,281 kept | port | Head total for the folder (code + tests) is 17,040 = 8,759 + 8,281. |

## Sheets and CSV (§9)

| Springform path | Donor | Donor path | Lines | Action | Notes |
|---|---|---|---|---|---|
| `backend/core/sheets/google.py` (`GoogleSheets`, `parse_service_account`) | cake_os | `backend/core/google_sheets.py` | 261 (head); `service_account_email()` at 239 | lift | |
| `backend/core/sheets/google.py` (A1 helpers, `forbidden_formula`, `check_values`) | cake_os | `backend/core/agents/tools/sheets_tools.py`: A1 helpers 171–270, `forbidden_formula`/`check_values` 111–170, `read_range` 616, `write_range` 845 | file 1,115 (head) | lift | Line numbers confirmed at head. |
| Sheets client, cache, refresh, throttle | — | — | — | new | |
| `backend/core/export/csv_export.py` | CakeCRM | `backend/crm/export.py:90-102` `_cell` | file 157 (head) | lift | |
| `backend/core/export/policy.py` | — | — | — | new | |

## Platform screens (§10)

| Springform path | Donor | Donor path | Lines | Action | Notes |
|---|---|---|---|---|---|
| `frontend/src/shared/` | CakeCRM | `frontend/src/shared/` subset | ~900 (plan); folder is 8,307 (head) | lift | Toast, confirm, `ConfirmHost`, icons, styles, `MobileMenuDrawer`, … |
| `BootFallback` | CakeCRM | `frontend/src/core/components/BootFallback.tsx` | 36 (head) | lift | |
| `ChunkErrorBoundary` | CakeCRM | `frontend/src/core/components/ChunkErrorBoundary.tsx` | 298 (head) | lift | |
| `useTheme` + contrast tests | CakeCRM | `frontend/src/core/theme/useTheme.ts`, `hueContrast.test.ts`, `inkContrast.test.ts` | 87 (head) | lift | |
| `index.css` tokens | CakeCRM | `frontend/src/index.css` | 403 (head) | lift | Renamed `--color-sf-*`; stage hues → CRM. |
| `frontend/src/core/api/client.ts` | CakeCRM | `frontend/src/core/api/client.ts` | 143 (head) | lift | + `openapi-fetch`. |
| `bootSplit.test.ts` | CakeCRM | `frontend/src/bootSplit.test.ts` | 838 (head) | port | Every app lazy. |
| Settings registry | CakeCRM | `frontend/src/crm/settingsSections.ts` | 147 (head) | port | Core cards + one section per app. |
| `backend/core/guide/library.py` (Guide) | CakeCRM | `backend/help/library.py`, `backend/help/search.py` | 262 (head) | port | Front matter, 8k cap, lazy warm, deterministic search. |
| Launcher, Layout/Nav, Settings, Requests, ChangeLog, Backups, Jobs, Sheets pages; `backend/core/requests/github.py` | — | — | ~1,900 + tests | new | |

## Deploy, CI, maintainability (§13, §14)

| Springform path | Donor | Donor path | Lines | Action | Notes |
|---|---|---|---|---|---|
| `Dockerfile`, `entrypoint.sh`, `deploy/*`, `railway.json` | — | — | ~700 with scripts (W8) | new | |
| `scripts/new-fork.sh`, `check-fork-scope.sh`, `update-from-upstream.sh`, `new-app.sh`, `gen-types.sh` | — | — | — | new | |
| `scripts/seed-labels.sh` | CakeCRM | `scripts/seed-labels.sh` | 102 (head) | lift | + `app:<slug>` labels, `--repo`. |
| `.github/workflows/ci.yml` | CakeCRM | `.github/workflows/ci.yml` | 146 (head) | port | Structure: SHA-pinned actions, ruff, import check, pytest, frontend build/lint/test + types diff, gitleaks, image test; conditional Fork scope job new. |
| `AGENTS.md` | CakeCRM | `AGENTS.md` | 174 (head) | port | Headings kept (Commands, Topic docs, Hard lines, Backend rules, Frontend rules, Tests and CI, Scope, Commits and PRs); Springform body. |
| `docs/AUTO_ISSUES.md` | CakeCRM | `docs/AUTO_ISSUES.md` | 163 (head) | lift | Minus the cake_os mirror section. |
| `backend/tests/conftest.py` (skip/xfail ban) | CakeCRM | `backend/tests/conftest.py` | 264 (head) | port | Ban on `skip`/`skipif`/`xfail` markers. |
| `frontend/vitest.config.ts` (guards, TZ pin) | CakeCRM | `frontend/vitest.config.ts` | 92 (head) | port | Donor pins `TZ: 'America/Chicago'`. |
| `docs/agents/*.md` | CakeCRM | `docs/agents/` | — | new | Topic docs written for Springform; CakeCRM's are the format reference. |

## Provenance rule

1. **Every lifted or ported file** gets a row in `docs/PROVENANCE.md`: source repo, commit sha, path.
2. The lift checks authorship: `git log --follow --format=%an -- <path>` in the donor (every author must be the project author).
3. The lift greps the donor file for third-party notices: `Copyright`, `@license`, `Source:`, `StackOverflow`.
4. **Anything not the author's is rewritten or dropped.** (All checked so far is the author's.)
5. Record the sha you actually copied from; for a private donor the row names the repo and sha only.

Open (pinned by the implementing workstream, which updates this doc): the `docs/PROVENANCE.md` row format (columns, one row per file vs per range) is not stated.

## Tests that pin this

- None automated in the plan. The provenance check is a manual step of each lift (Risks 10).

## Source

Build plan: module tables and lift notes in §1, §2, §3, §4, §5, §7, §8, §9, §10, §13, §14, SQLite rules, Decisions (License), Risks 10. Line counts at head were measured against the shas above.
