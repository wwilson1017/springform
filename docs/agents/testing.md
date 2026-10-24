# Testing

**What this covers:** every item of the plan's Verification section, organised by suite (pytest, Vitest, Playwright, live), the tests the subsystem sections add, the conftest conventions, and the CI jobs that run them.
**Who reads it:** every implementer (each workstream owns the tests for its area), and whoever maintains `backend/tests/conftest.py`, `frontend/vitest.config.ts` and `.github/workflows/ci.yml`.

## 1. Conventions

### pytest (`backend/tests/conftest.py`)

1. **Real temp SQLite.** `db(tmp_path)` runs all migrations (core, then every app) on a fresh file. No services.
2. **No FakeConn.** Never fake the connection or the database.
3. **`freeze(iso)`**: a fixture that freezes `core.clock` at an ISO instant (reminders, scheduler, sweep ages, `at` catch-up).
4. **`login_as(role, email=None, on=app)`**: a fixture that creates a new user of that role and returns a new signed-in `TestClient` with `.user`. The first account goes through the real setup-token path as an admin; later ones sign in through `/api/auth/login`. **`make_user(role, email=None, password=…)`** creates a user directly, without HTTP.
5. **Skip/xfail ban**: conftest fails collection when a test carries a `skip`, `skipif` or `xfail` marker (lifted from CakeCRM). `ALLOWED_SUPPRESSIONS` lists node ids allowed one, each with a reason; it is empty. `test_conftest_guards.py` self-tests it.
6. Two-member tests create two real members and one restrictive record: every `login_as("member")` call makes a new, distinct member.
7. Providers: a **FakeProvider** stands in for LLM providers; nothing calls a real model.
8. HTTP to external services is mocked (Google token endpoint) or served locally (a FastMCP stub, `httpx.ASGITransport`).
9. The contract test runs against every app in `backend/apps/` and against `backend/tests/fixtures/bad_app`, which it must fail.

### Vitest (`frontend/vitest.config.ts`)

1. A **non-UTC `TZ` pin**, so date code that assumes UTC fails.
2. Guards: apps contract, bootSplit, contrast, grep guards.

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
- No `httpx` inside `transaction()` (an autouse fixture makes `httpx` sends raise inside one, in every test).
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

### MCP

- MCP link lists role-filtered tools and executes an attributed write via a real `ClientSession` over `httpx2.ASGITransport` (the `mcp` 2.x client speaks `httpx2`).
- Revoked and deactivated links 404.
- Origin refused.
- Outbound against a local FastMCP stub: discovery, prefixing, every call confirms, private address refused, fenced result.
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
- `gen-types` diff clean.

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
9. Example record panel on a person.
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

Structure copied from CakeCRM: SHA-pinned actions, ruff, an import check, pytest, frontend build / lint / test + the types diff, gitleaks, the image test. Required checks for branch protection: **Backend**, **Frontend**, **Secret scan**, and **Fork scope** (which always runs and passes upstream, where there is no `FORK.md`; `forks.md`).

## Tests that pin this

This file is the test list. Each topic doc repeats the bullets for its area.

## Source

Build plan: Verification (all four suites), SQLite rules (tests), §1 (restore test), §4 (two-member and files tests), §6 (DNS rebinding), §7 (CRM tests), §8 (Todos tests), §9 (export tests), §11 (scheduler test), §13 (image test), §14 (conftest skip/xfail ban, vitest guards, TZ pin, `ci.yml` structure), Step 1 (conftest fixtures), Step 5.
