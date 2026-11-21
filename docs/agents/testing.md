# Testing

**What this covers:** every item of the plan's Verification section, organised by suite (pytest, Vitest, Playwright, live), the tests the subsystem sections add, the conftest conventions, and the CI jobs that run them.
**Who reads it:** every implementer (each workstream owns the tests for its area), and whoever maintains `backend/testing/fixtures.py`, `frontend/vitest.config.ts` and `.github/workflows/ci.yml`.

## 1. Conventions

### pytest (`backend/testing/fixtures.py`)

The fixtures and guards live in a pytest plugin, `backend/testing/fixtures.py`, which the root `conftest.py` loads for every test. `testpaths` collects `backend/tests` (core) and `backend/apps` (each app).

**App tests** go in `backend/apps/<slug>/tests/` (with an `__init__.py`, so two apps can both have a `test_api.py`). `scripts/new-app.sh` scaffolds the folder with a starter test. They get every fixture below, the autouse isolation and the skip/xfail ban with no conftest of their own; a fork never edits `backend/tests/` or `backend/testing/`. Import the app absolutely (`from backend.apps.<slug> import api`): the contract test rejects relative imports that leave the app package. `backend/apps/example/tests/` is the worked example. `PASSWORD` and `make_client` import from `backend.testing.fixtures`.


1. **Real temp SQLite.** `db(tmp_path)` runs all migrations (core, then every app) on a fresh file. No services.
2. **No FakeConn.** Never fake the connection or the database.
3. **`freeze(iso)`**: a fixture that freezes `core.clock` at an ISO instant (reminders, scheduler, sweep ages, `at` catch-up).
4. **`login_as(role, email=None, on=app)`**: a fixture that creates a new user of that role and returns a new signed-in `TestClient` with `.user` (the `/api/me` shape) and `.principal` (the `User`). The first account goes through the real setup-token path as an admin; later ones sign in through `/api/auth/login`. **`make_user(role, email=None, password=…)`** creates a user directly, without HTTP.
5. **Skip/xfail ban**: the plugin fails collection when a test carries a `skip`, `skipif` or `xfail` marker (lifted from CakeCRM). `ALLOWED_SUPPRESSIONS` lists node ids allowed one, each with a reason; it is empty. `test_conftest_guards.py` self-tests it.
6. Two-member tests create two real members and one restrictive record: every `login_as("member")` call makes a new, distinct member.
7. Providers: a **FakeProvider** stands in for LLM providers; nothing calls a real model. **`model_requests`** records every FakeProvider call of the test, in order, as `{system, messages, tools}`.
8. HTTP to external services is mocked (Google token endpoint) or served locally: inbound MCP runs through `httpx2.ASGITransport`, and the outbound client talks to `backend/tests/fixtures/mcp_stub.py`, a two-tool `MCPServer` on a loopback port (with `MCP_ALLOW_PRIVATE=1`); `with mcp_stub.serve() as (url, calls):` stops it when the block ends.
9. The contract test runs against every app in `backend/apps/` and against `backend/tests/fixtures/bad_app`, which it must fail.
10. **Typed routes**: `test_routes_are_typed.py` fails when a `/api/core/*`, `/api/agent/*` or `/api/health` route answers without a response model, unless its `UNTYPED` allow-list names the route with a reason (streams, downloads and a few bodies not typed yet). `test_response_models.py` pins each typed route's keys in `fixtures/response_shapes.json`.
11. **No thread left running**: the test database is closed in one place, `_isolate`'s teardown, after waiting up to 5 s (`THREAD_GRACE`) for the threads the test started; a thread still alive then stops the run with the test id and the thread names rather than close the database under it (a connection closed while another thread steps it crashes SQLite, #52). Best effort: it compares one snapshot from the test's start, and parked AnyIO worker threads are exempt. `test_conftest_guards.py` self-tests it.

### Vitest (`frontend/vitest.config.ts`)

1. A **non-UTC `TZ` pin**, so date code that assumes UTC fails.
2. Guards: apps contract, bootSplit, contrast, grep guards.
3. Fail closed: `passWithNoTests: false`, `allowOnly: false` and `expect.requireAssertions`, so an empty run or an assertion-free test is red.

### Playwright

Runs against a seeded `PREVIEW_MODE=1` build with the FakeProvider and the Google preview stub. It freezes the server clock with `SPRINGFORM_FREEZE_CLOCK=<iso>`, which the server honours only in `PREVIEW_MODE`.

## 2. pytest, by area

### Platform and database

- Contract guard passes for `example`/`crm`/`todos` and fails `bad_app`.
- Migrations apply in order (core before apps), checksums enforced, a failing fixture leaves no partial DDL.
- Fresh apply.
- Upgrade from the previous tag + a private fixture app applies cleanly, on both a fresh and an upgraded database, with a fixture whose historical migration references a deprecated core column.
- A lint fails any core migration not named `*_baseline.sql` that contains `DROP COLUMN`, `DROP TABLE` or `RENAME`, and a test proves a `*_baseline.sql` file may drop a table.
- The `requires_core` refusal, with a fixture declaring `<0.1`.
- `now_iso` is the only timestamp writer (grep test for `datetime('now')` / `CURRENT_TIMESTAMP`).
- No `httpx` inside `transaction()` (an autouse fixture makes `httpx` and `httpx2` sends raise inside one, in every test).
- Nested `transaction()` raises.
- A merge with a failing subscriber rolls back entirely (a core merge invoking a failing CRM subscriber leaves no partial change).
- After-commit hooks run after `COMMIT` only.
- Two drainers started by hand claim disjoint rows.
- A crash after an external effect replays once with the same idempotency key.
- App reset: reset an app holding a private record with attachments and notes, create a new record visible to another member, and assert none of the old content attaches to or is readable through it (run through the CRM's own reset entry point).

### Login

- Setup requires the token, consumes it, and 404s afterwards (against the real migrated, seeded database).
- Invite hash `'!'` can't log in.
- Password login with equal-time wrong-password.
- Account + IP limits via `core_login_attempts`.
- TOTP enrol / verify / replay / backup / trusted device.
- Google callback with a mocked token endpoint: invited signs in and gets linked; uninvited refused; wrong `aud` / `iss` / `nonce` / unverified email refused; mismatched `google_sub` refused.
- Epoch bump kills the cookie.
- `require_admin` 403.
- CSRF: cookie + cross-site POST refused; cookie + no fetch metadata refused; bearer-only passes.

### Authorization

- Two members: a private todo is invisible through todos, timeline, files, fields, reminders, search, reports and titles (and, per §4, change log, mention delivery, and a reminder fired after the todo went private).
- A member calling an admin-only app's API directly gets 403.

### Contacts

- Person ↔ two organizations with roles; primary uniqueness.
- Merge with every collision rule; merge repoints a deal and keeps score.

### Record services

- `record_changes_in` writes one timeline row + one change-log row per changed field and fires the hook after commit.
- File upload round-trips sha256, dedupes; a fresh blob survives `sweep`; an unreferenced blob survives 6 days and goes at 8.
- Deterministic interleaving: sweep claims the lock, an upload of the same bytes waits, sweep deletes, upload republishes; the file ends present and referenced.
- Download refused without `can_read`; served as attachment.
- Reminders fire under a frozen clock → notification row in the same transaction.
- `flush` retries and never duplicates.
- A team todo notifies a member, then goes private: before `flush` the delivery is dropped and the row hidden; after an in-app delivery the row is hidden on next read.

### Scheduler

- Stale `running` → `interrupted`.
- Missed `at` catches up once.
- A never-run `at` job waits for its next slot; a manual run after the slot is not followed by a catch-up.
- Overlapping job skipped.
- A job that ignores its timeout: no second instance starts, and the slot is released only when it ends.
- An `on_boot` job runs at the first tick of every start; shutdown waits for it before `db.close()`.
- Core and apps start no threads of their own (a scan of `backend/core` and `backend/apps`).

### CRM

- Deal lifecycle: lead → won → archive → restore → merge.
- Analytics fixture spanning 2026-03-08 and 2026-11-01 in `America/Chicago` equals hand-computed buckets.
- Money fixture (cents, no float).
- Unicode search fixture.
- Ported behavioural suites: `deal_lifecycle`, `bulk_move`, `closed_on`, `scoring`, `analytics`, `touch_count` parsers, `provenance`, `seed`, `smart_import`, `stage_criteria`, `today`, `dashboard_touches`, `weekly_review`; `test_crm_service` / `test_crm_router` rewritten as TestClient tests; 11 of the 28 Postgres integration files become ordinary tests.

### Todos

- Repeat respawn inherits visibility.
- Team edit advances the team rev.
- Deactivation hides private todos.
- Two-user permission and sync tests; ~5,000 of 8,281 donor test lines kept.

### Whisk

- Registry rejects duplicate / unprefixed / tier-on-read specs.
- `for_source("job")` excludes writes; `for_source("mcp")` excludes protected and remote tools.
- Zero-key status + 400.
- FakeProvider streams text + a write tool → `confirm`, pending run; approve by a non-owner 403; stale `tool_def_sha256` → `stale`; approve executes once with args from the DB (double approve = `already_resolved`); deny recorded; `executing` at startup → `interrupted`.
- Scenarios (below): an untrusted result is fenced and every later write confirms; a provider-side web search (Anthropic mode) taints the conversation; approve then continue; compaction shows the summarizer the identifiers and the model the gist; a dropped turn resumes; a readable record is named in the prompt and an unreadable one is left out; a result naming a record made private is withheld from the next turn. Removing the fence fails a scenario (`test_removing_the_untrusted_fence_fails_a_scenario`).
- Prompt budget (`test_prompt_budget.py`): the static system prompt plus the eager tool definitions of an admin's first turn (lifespan run, so the seeded soul.md counts) stay under `BUDGET_TOKENS` (characters / 4); a self-test flags a synthetic oversized prompt and passes a small one. Raise it on purpose, in the PR that needs it. With `PROMPT_REPORT=<file>` it appends the sizes and the chat tool surface (name, `writes`, `always_confirm`, `confirm_tier`, eager) as Markdown; CI writes that to the Backend job summary.
- Turn reliability (`agent.md` §5): a result over 25,000 characters is capped and fully readable through `core_read_result`; older results clear past 100,000 input tokens, the newest three kept. A fallback never happens after a write ran; each unfinished ending saves a note; the round limit gets a last answer. A repeating model is stopped on the third notice; an unbacked "I sent it." gets a correction.

### Whisk scenarios (`backend/tests/scenarios/*.yaml`)

`test_scenarios.py` runs every YAML file in `backend/tests/scenarios/` as one test (the id is the file name). A scenario signs in a new user, scripts the FakeProvider's replies for each step, drives real turns over HTTP through the server-owned turn (`detached.py` running `turns.TurnRunner`) on a client that runs the lifespan, and checks the events each step emits and what the model was sent. A feature that changes what the model sees or what the turn emits adds a scenario: a new YAML file, and a new key in the runner only when no existing one can say it. Unknown keys fail the test, so a typo never passes silently.

```yaml
name: An approved write runs, and continuing shows the model its result   # required
role: member                  # optional (default member); admin sees admin-only tools
context_window: 1000          # optional: the FakeProvider's window in tokens (small forces compaction)
tools:                        # optional test-only core tools, added to the live registry for this file
  - name: core_scen_save_widget   # core_ prefix
    writes: true                  # default false (a read)
    returns: {saved: widget-77}   # what the tool answers (default {ok: true})
    repeat: 2000                  # optional: answer a list of that many copies of `returns` (a big result)
    # also: description, confirm_tier: routine, always_confirm, untrusted_source, external_effect
records:                      # optional: example widgets owned by another user, by key
  shared: {name: Blue widget}             # readable by the scenario's user
  hidden: {name: Red widget, private: true}   # someone else's private widget: unreadable
steps:
  - send: Save the blue widget.          # one action per step (see below)
    # sql: [UPDATE ...]                  # optional: statements run in one transaction before the action
    replies:                             # queued for the FakeProvider: one entry per model call
      - {tool: core_scen_save_widget, args: {color: blue}}
      - Saving the widget needs your approval.
    events:                              # must appear in this order; others may sit between
      - {type: confirm, tool: core_scen_save_widget}   # a mapping matches the keys it names
      - done                             # a string matches the type
  - approve: core_scen_save_widget       # the newest confirm event for that tool
    status: done                         # optional: the /confirm response status
  - continue: true
    replies: [Saved widget-77.]
    request:                             # one check, or a list of them
      call: -1                           # which model call of this step (0 = first; default -1, the last)
      messages_contain: ['{"saved": "widget-77"}']
      messages_exclude: []
      messages_match: []                 # regular expressions (re.search), e.g. a fence opened and closed with one nonce
      system_contains: []
      system_exclude: []
```

| Action | Does |
|---|---|
| `send: <text>` | `POST /api/agent/chat` with the message, in the scenario's conversation once it has one |
| `continue: true` | The same with no message: the resume after approvals |
| `approve: <tool>` / `deny: <tool>` | `POST /api/agent/confirm` for the newest `confirm` event of that tool |
| `resume: true` | `GET /api/agent/turns/{id}/events?after=<last seq seen>` for the latest turn |

- `files: [{name, text} | {name, base64}]` on a `send` posts it to `/api/agent/chat/upload` as multipart, with those files (a CSV as `text`, a photo as `base64`).
- `page: <path>` and `record: <records key>` on a `send` or `continue` send the chat's page and record context (the record as `example.widget` with that widget's id).
- `usage: [...]` on any step: the `core_agent_usage` rows the step wrote, matched in order like `events` (a mapping matches the columns it names, others may sit between).
- `sql:` (one statement or a list) changes the data between turns, before the step's action: a record made private, say. Use explicit ids.
- `drop_after: <event type>` on a `send` or `continue` disconnects once that event arrives, and checks the turn is still running then (script slow `chunks` so it is); the turn carries on, and a later `resume` reads the rest.
- `replies` entries are FakeProvider turns (`providers/fake.py`): a string streams text, `{tool, args, text?}` calls a tool, a list makes several calls, `{error}` fails the call, `{chunks, delay}` streams slowly. A compaction summary is a model call too: it takes the next reply, before the turn's own. A step that leaves a reply unused fails (except a `drop_after` step, whose turn is still going).
- Every step that streams a turn also checks that the events are numbered without gaps (a resume continues from the last seq seen) and end on `done` or `error` (or on the `drop_after` event).
- Request checks look at the strings of the call's `messages` and `system`, so a fence reads as the model gets it, not JSON-escaped. Another test can read those calls with the `model_requests` fixture.
- Files and tools a scenario makes up use generic names (no people, businesses or real records).

### MCP

- MCP link lists role-filtered tools and executes an attributed write via a real `ClientSession` over `httpx2.ASGITransport` (the `mcp` 2.x client speaks `httpx2`).
- Revoked and deactivated links 404.
- Origin refused.
- Outbound against the loopback `MCPServer` stub (`fixtures/mcp_stub.py`): discovery, prefixing, every call confirms, private address refused, fenced result.
- DNS rebinding: a stub resolver that returns a public address first and a private one second.

### Export

- Export ZIP columns pinned and secrets absent.
- A two-user test proves a private todo is absent from the other admin's export.

### Backup and restore

- Restore test: take a snapshot, restore the set (snapshot + files + key) into an empty volume, boot, open an attachment, decrypt a stored provider key.
- A second test restores with the wrong key and must fail before serving.

## 3. Vitest

- Apps contract: every manifest has `contributions.ts` + `index.tsx` and vice versa; every settings card id has a loader; no `../<otherapp>/` imports.
- bootSplit: every app lazy; contributions eager but tiny.
- Contrast guards on shipped CSS.
- `Timeline`.
- `CustomFields` by type.
- `SavedViewBar` stale-version refusal.
- A grep guard that `apps/crm` contains no `contact_id|company_id`.
- Type twins (`src/core/typeTwins.test.ts`): no `src/core/**/types.ts` declares an interface or object type under a generated schema name; it aliases `components['schemas'][…]` instead.
- `gen-types` diff clean (a CI step in the Frontend job, not a vitest).

## 4. Playwright smoke

One flow, `PREVIEW_MODE=1`, seeded:

1. Pick role.
2. Launcher by role.
3. Todos: add, complete, mark team; the second role sees it.
4. Create organization → person → link with role → deal.
5. Note with @mention → attachment → reminder fires (frozen clock).
6. Guide.
7. Requests validation.
8. Settings cards by role (example app's card present).
9. Example record panel on a person (as admin; Example is hidden from members by default).
10. Back up now creates a file.
11. Password login → enable 2FA (pyotp) → Google login via the preview stub.
12. Whisk answers with FakeProvider → a write tool shows Approve and runs on approve → zero-key card.

### Browser smoke

`frontend/e2e/`, one spec per area, run with `npm run e2e` (that is `scripts/e2e.sh`; extra arguments go to `playwright test`). The script builds the SPA, boots two `PREVIEW_MODE=1` backends on fresh temp data dirs with `SPRINGFORM_FREEZE_CLOCK` (port 8160 with `AGENT_FAKE_PROVIDER=1`, port 8161 with no AI key), runs Chromium at 1280 and 390 px, stops both by PID and exits with Playwright's status. The HTML report, traces (first retry) and server logs land in `E2E_ARTIFACTS` (a temp dir by default; the script prints it). Against a backend you started yourself: `E2E_BASE_URL=… npx playwright test`.

- Sign-in: `e2e/fixtures.ts` gives a test `admin` and `member` sessions (`POST /api/auth/preview`), each its own context with `page`, `api` and `user`, and fails a test on any uncaught page error. Cookie-authenticated API calls send `Sec-Fetch-Site: same-origin`, as a browser does.
- Frozen clock: reminders fire by "Run now" on the Jobs page (`core.reminders_fire_due`), since the scheduler's own tick is frozen too. TOTP codes are computed for `E2E_FREEZE_CLOCK` (`e2e/totp.ts`), one step apart for enrolment and sign-in.
- Install-wide state runs in the desktop project only: Back up now (a frozen clock gives every set the same stamp) and hiding an app (on the keyless backend).
- A spec a known bug blocks is `test.fixme('<finding id>: …')`, never `skip`.

CI job (beside Frontend in `.github/workflows/ci.yml`):

```yaml
  browser-smoke:
    name: Browser smoke
    runs-on: ubuntu-24.04
    timeout-minutes: 15
    steps:
      - name: Checkout
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false
      - name: Set up Node 22
        uses: actions/setup-node@820762786026740c76f36085b0efc47a31fe5020 # v7.0.0
        with:
          node-version: "22"
          cache: npm
          cache-dependency-path: frontend/package-lock.json
      - name: Set up uv and Python 3.12
        uses: astral-sh/setup-uv@c18668ad3cf93ea998bef934396af7bb5c839dc7 # v10.2.0
        with:
          version: "0.12.24"
          python-version: "3.12"
          enable-cache: true
      - name: Install dependencies and Chromium
        run: |
          uv sync --frozen
          cd frontend && npm ci && npx playwright install --with-deps chromium
      - name: Smoke (Playwright)
        env:
          E2E_ARTIFACTS: ${{ runner.temp }}/e2e
        run: scripts/e2e.sh
      - name: Upload the report, traces and server logs
        if: failure()
        uses: actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9 # v7.0.2
        with:
          name: playwright-report
          path: ${{ runner.temp }}/e2e
          retention-days: 14
```

## 5. Live checks (Step 5)

- Fresh-VPS dry run in a Multipass Ubuntu 24.04 VM: `setup.sh` with `DOMAIN=localhost`, `/up`, `deploy.sh` to a second tag, including a restore drill into an empty volume.
- Railway preview with the root-owned volume.
- CI image test: run the container; `/api/health` reports `sqlite_version >= 3.51.3` and `fts5: true`.
- `new-fork.sh` + `update-from-upstream.sh` on a throwaway repo with the two-PR scope test (a PR touching core must fail; one touching an app must pass).

## 6. CI (`.github/workflows/ci.yml`)

Structure copied from CakeCRM: SHA-pinned actions, ruff check and ruff format, pyright, an import check, pytest, frontend build / lint / Prettier / test + the types diff, the browser smoke (§4), gitleaks, the image test. Required checks for branch protection: **Backend**, **Frontend**, **Secret scan**, and **Fork scope** (which always runs and passes upstream, where there is no `FORK.md`; `forks.md`).

The Backend job ends by writing the Whisk prompt size and chat tool surface to its job summary (`test_prompt_budget.py` with `PROMPT_REPORT`, §2 Whisk).

`scripts/check.sh` runs the Backend and Frontend jobs' checks locally; run it before a PR.

## Tests that pin this

This file is the test list. Each topic doc repeats the bullets for its area.

## Source

Build plan: Verification (all four suites), SQLite rules (tests), §1 (restore test), §4 (two-member and files tests), §6 (DNS rebinding), §7 (CRM tests), §8 (Todos tests), §9 (export tests), §11 (scheduler test), §13 (image test), §14 (conftest skip/xfail ban, vitest guards, TZ pin, `ci.yml` structure), Step 1 (conftest fixtures), Step 5.
