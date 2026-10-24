# Database and transactions

**What this covers:** every rule in the plan's "SQLite rules": the connection and pragmas, `transaction()` and `NestedTransaction`, the `fn` / `fn_in(conn, …)` convention, sync hooks vs the durable outbox, the migration runner, identifiers and resets, timestamps, money, search, JSON, single-process locking, and the SQLite version floor.
**Who reads it:** anyone writing SQL, a service function, a hook, a migration, or porting Postgres code from CakeCRM.

All of this lives in `backend/core/db.py` unless stated.

## 1. Connection

Lifted from todo-gtd `backend/db.py` 499–540 and 782–825.

| Rule | Value |
|---|---|
| Connection scope | One connection per thread (`threading.local`), opened lazily by the thread's first use. |
| `isolation_level` | `None`. No implicit transactions; `transaction()` issues `BEGIN IMMEDIATE` itself; a bare read sees only committed data. |
| `PRAGMA journal_mode` | `WAL` |
| `PRAGMA synchronous` | `NORMAL` (the todo-gtd donor sets `FULL`; Springform's contract is `NORMAL`). |
| `PRAGMA foreign_keys` | `ON` |
| `PRAGMA busy_timeout` | `5000` |
| Data-dir probe | At init, write and delete a probe file in the data directory (`DATA_DIR`, default `./data`; `/data` in the container); refuse to start with an actionable error if it is not writable (the donor's probe). |
| Database file | `<DATA_DIR>/springform.sqlite`, so `/data/springform.sqlite` in the container. |
| `db.log_db()` | A seam that returns the main connection in v0.1 (one DB file). |

## 2. `transaction()`

```python
class NestedTransaction(Exception): ...

@contextmanager
def transaction() -> Iterator[Conn]:
    # 1. if this thread's connection is already in a transaction: raise NestedTransaction
    # 2. take the process-wide _write_lock
    # 3. BEGIN IMMEDIATE
    # 4. yield conn
    # 5. on any exception: ROLLBACK, re-raise
    # 6. COMMIT
    # 7. after COMMIT: nudge the outbox drainer (set an asyncio Event), fire-and-forget
```

Rules:

1. `transaction()` is **never nested**. It raises `NestedTransaction` if the thread's connection is already in one.
2. The write lock is process-wide (`_write_lock`), on top of SQLite's own `BEGIN IMMEDIATE` lock.
3. `transaction()` does **not** drain the outbox inline. It only nudges the drainer after `COMMIT`. A failed nudge can never make a committed API call look failed.
4. **No network or LLM call inside `transaction()`.** A test patches `transaction()` to fail on `httpx`/provider calls.
5. Local disk operations are allowed under the lock where a protocol needs them (file publication `rename`, sweep `unlink`; `records.md`).

## 3. The `fn` / `fn_in(conn, …)` convention

Every service function and every published `api.py` function comes in two forms (todo-gtd's `create_in` pattern):

| Form | Opens a transaction | Use |
|---|---|---|
| `fn(...)` | Yes, its own `transaction()` | Routers, jobs, top-level callers. |
| `fn_in(conn, ...)` | No; runs on the caller's `conn` | Code already inside a transaction: hooks, other services, `handler_in` tools, outbox consumers with local effects. |

Rules:

1. `fn(...)` is `with transaction() as conn: return fn_in(conn, ...)`, or equivalent.
2. `fn_in` never calls `transaction()` and never makes a network call.
3. **Every** published `api.py` function has an `_in(conn, …)` form, reads included, so a caller inside a transaction reads through its own `conn`.

## 4. Sync hooks vs the durable outbox

### Sync hooks (in-transaction)

Subscribers to the `HOOKS` keys `on_entity_deleted`, `on_entity_merged` and `on_record_changed` are `fn(conn, entity_type, entity_id, **kw)`. Core's `_in` dispatchers (`on_entity_deleted_in`, `on_entity_merged_in`, `on_record_changed_in`) call them **inside the caller's transaction**. A failing subscriber rolls the whole write back. They are for cheap bookkeeping only: set a flag, write a row. Registered from each app's `hooks.py`, never signals (`authorization.md` §3 has the registry side).

### Durable outbox (after commit)

Work that must happen after commit is **durable, not in-memory**. `record_changes_in` writes a `core_outbox` row in the same transaction as the change (through `after_record_changed_in`). `after_record_changed` subscribers are `fn(payload: dict)`: the drainer runs them after `COMMIT`, outside any transaction, and a subscriber may open its own. The payload is `{entity_type, entity_id, changes: {field: [old, new]}, user_id, at}`.

```sql
core_outbox(
  id,            -- integer primary key
  hook,          -- consumer name (e.g. after_record_changed)
  payload,       -- JSON TEXT
  created_at,    -- now_iso()
  claimed_at,    -- set by the drainer's atomic claim
  attempts,      -- bumped on failure
  processed_at,  -- set when the consumer's effect is recorded
  last_error,
  dead_at        -- set at the 5th failure
)
```

Drainer and consumer rules:

1. **There is exactly one drainer**: the scheduler job `core.outbox_drain` (every 30 s, plus the post-`COMMIT` nudge). The scheduler's per-job in-flight guard makes it single-flight.
2. **Atomic claim, one row per transaction:** `UPDATE core_outbox SET claimed_at=? WHERE id=? AND (claimed_at IS NULL OR claimed_at < ?)`, where the last parameter is now minus **600 s**: a claim older than that is stale and may be taken again. Two drainers started by hand claim disjoint rows.
3. A consumer with **local DB effects** performs them and sets `processed_at` in **one** transaction. It is exactly-once by construction: a crash between effect and `processed_at` cannot happen.
4. A consumer with **external effects** (LLM call, HTTP) is **at-least-once**. It uses the outbox `id` as its idempotency key where the remote supports one, and records the effect's own id before marking processed. After a crash the row is re-claimed when `claimed_at` is older than 600 s, and replays once with the same idempotency key.
5. Failures bump `attempts` and back off **30 s, 2 min, 10 min, 1 h, 6 h**. The 5th failure sets `dead_at`, and the row shows on the Jobs page.
6. Consumers never start a drain and never call `transaction()` while already inside one.
7. A consumer registers with `outbox.consumer(hook, external=False)`; `external=True` declares the external-effect, at-least-once kind (rule 4).
8. Worked example: the CRM sets `crm_deals.touch_dirty` in the sync hook (durable with the write) and does its LLM work from the outbox or its own job, never inside a write lock.

Open (pinned by the implementing workstream, which updates this doc): how an app's `after_record_changed` subscriber (`fn(payload)`, which may open its own transaction) maps onto `outbox.consumer(hook, external=…)`. Such a subscriber cannot commit its effect together with `processed_at`, so rule 3's exactly-once does not hold for it; until this is pinned, write it to be idempotent.

## 5. Migration runner

Ported from CakeCRM `backend/core/postgres.py:181-248`. Runs at **startup only**.

### Files and order

| Rule | Value |
|---|---|
| Core files | `backend/core/migrations/*.sql`, named `20261020HHMMSS_core_<name>.sql`. |
| App files | `backend/apps/<slug>/migrations/*.sql`, named `YYYYMMDDHHMMSS_<slug>_<name>.sql` (contract test regex `\d{14}_<slug>_`). |
| Collection | Core files first, then app files. Core always first. |
| Sort | Within each group, by `(timestamp, path)`. |
| Stamps | Core migrations are stamped `20261020…`; app migrations `>= 20261101…`. |
| Core init | `20261020000100_core_init.sql` (settings, change_log, job_runs, apps_state, requests, backups, outbox, file blobs, users incl. the system user, totp, trusted_devices, login_tokens, login_attempts, contacts tables, timeline, files). |
| Per workstream | Every workstream adds its **own** `20261020…_core_<area>.sql` and **never edits one that has landed**. |

### Applying a file

```python
try:
    conn.executescript(
        "BEGIN IMMEDIATE;" + sql +
        "INSERT INTO _migrations_applied(filename, sha256) VALUES (...);"
        "COMMIT;"
    )
except Exception:
    if conn.in_transaction:
        conn.execute("ROLLBACK")   # explicit: Python supplies no transaction policy here
    raise
```

1. One `executescript` per file: `BEGIN IMMEDIATE; …; INSERT INTO _migrations_applied …; COMMIT;`.
2. An explicit `ROLLBACK` in the `except` when `conn.in_transaction`. A failing file leaves no partial DDL.
3. `_migrations_applied(filename PK, sha256, applied_at)`. The sha256 of each applied file is recorded. **A changed applied file fails startup.**
4. **Before applying any migration**, the runner checks every installed app's `requires_core` against `springform-version` and refuses to start on a mismatch, naming the app.

`requires_core` is a PEP 440 specifier set (e.g. `>=0.1,<1`), parsed with `packaging`.

### What a migration may reference

1. Core migrations never reference app tables.
2. An app migration may reference only core tables that exist at the app's `requires_core` version.
3. Apps never reference each other.
4. Every `CREATE`/`ALTER` target in an app migration starts with `<slug>_`. `REFERENCES` may name `<slug>_*` or `core_*` tables only (the contract test checks this after migrating; `apps-and-contracts.md`).

### Core schema compatibility

1. **Within a major version, core never drops or renames a table or column.** Changes are additive: new tables, new nullable columns, new indexes.
2. A column core stops using is marked deprecated in `CHANGELOG.md` "Schema" and stays, nullable and unused, until the next major.
3. A major (`1.0`, `2.0`) may drop deprecated columns and ships a **baseline** migration. Apps crossing it re-baseline (squash their migrations) and raise `requires_core`.
4. **Lint:** every core migration except files named `*_baseline.sql` fails if it contains `DROP COLUMN`, `DROP TABLE` or `RENAME`. Only a major's baseline may drop.

## 6. Identifiers, resets

1. Every table that other rows point at polymorphically (anything in `ENTITIES`, `core_timeline`, `core_files`) uses `INTEGER PRIMARY KEY AUTOINCREMENT`, so a deleted id is never reused under an old timeline or audit reference.
2. **An app reset never touches `sqlite_sequence`.** `registry.reset_app_in(conn, slug)`:
   1. runs `entities.delete_record_in` for every row of the app's entity tables, which cascades timeline, files, fields, reminders, notifications and change-log rows through the `on_entity_deleted` subscribers;
   2. then `DELETE`s the app's non-entity `RESET_TABLES`;
   3. ids keep climbing.
3. Only the admin **factory reset** clears every table and every sequence together. It is allowed only when `PREVIEW_MODE` is on, or when no human user other than the caller exists **and** every app's `RESET_TABLES`, `core_people` and `core_organizations` hold zero rows. It is refused otherwise.
4. Change-log rows written before a delete keep `entity_id` and get `core_change_log.deleted_at` (`TEXT NULL`) set, so history stays distinguishable from any later record.
5. The CRM's port replaces CakeCRM's `TRUNCATE … RESTART IDENTITY` (`crm/service.py::_truncate_all`) with `registry.reset_app_in(conn, "crm")`; the reset regression test runs through the CRM's own reset entry point.

## 7. Timestamps

1. Canonical form: `YYYY-MM-DDTHH:MM:SSZ` (UTC, second precision).
2. Written only by `core.clock.now_iso()`. A test greps SQL for `datetime('now')` and `CURRENT_TIMESTAMP`.
3. User-supplied instants go through `clock.normalize(value: str | datetime, tz: str) -> str`, which returns the canonical UTC string.
4. Day bucketing for reports happens in Python via `zoneinfo` and the install timezone (`core/localtime.py`, lifted from CakeCRM). SQL only compares against precomputed UTC bounds. Never `substr(col,1,10)` (that is a UTC date).
5. The install timezone is `core_settings.timezone` (IANA, default UTC).

## 8. Money, search, JSON, keys

| Topic | Rule |
|---|---|
| Money | Integer cents (`value_cents INTEGER`), formatted in the UI. Never `REAL`. |
| Search | FTS5 with the `unicode61` tokenizer (case- and accent-folding). `LIKE … COLLATE NOCASE` is ASCII-only and used only for exact-ish filters. |
| JSON | Stored in `TEXT`; query with `json_each`, `json_extract`. |
| Foreign keys | Real foreign keys (`foreign_keys=ON`). |

## 9. Single process

1. Lifespan takes `fcntl.flock` on `/data/.springform.lock`.
2. A second process, or `--workers 2`, refuses to start.
3. The scheduler runs only in the lock holder.
4. Deploys are stop-before-start (compose recreate and Railway both do this; `deploy.md`).

## 10. SQLite ≥ 3.51.3

Required for the WAL-reset corruption fix.

| Where | How it is satisfied |
|---|---|
| Docker image | Stage `sqlite` builds the SHA-pinned 3.51.3 amalgamation; the runtime stage copies `libsqlite3.so.0*`. |
| Dev and CI | `pysqlite3-binary`, imported as `try: import pysqlite3 as sqlite3` (falling back to the stdlib module). |
| Startup | Asserts `sqlite3.sqlite_version_info >= (3, 51, 3)` **from the connection actually in use**, and that `fts5` is compiled in (`PRAGMA compile_options`). |
| CI image test | Runs the container and asserts `/api/health` reports `sqlite_version >= 3.51.3` and `fts5: true`. |

## 11. PG→SQLite checklist

Written for the CRM port (§7); grep each before a ported module is done.

| Postgres | SQLite |
|---|---|
| `FOR UPDATE` / `SKIP LOCKED` / advisory locks | Delete; the code runs inside `transaction()`. |
| `TRUNCATE … RESTART IDENTITY` | `registry.reset_app_in(conn, slug)` (never touch `sqlite_sequence`). |
| `now()` | `now_iso()` |
| `AT TIME ZONE` / `::date` | Python bounds. |
| `date_trunc` | Python bucketing in the install timezone (never `substr(col,1,10)`). |
| `EXTRACT(EPOCH …)/86400` | `julianday()` |
| `make_interval` | Precomputed cutoff. |
| `DISTINCT ON` | `ROW_NUMBER() OVER (…) = 1` |
| `= ANY(%s)` | `IN (SELECT value FROM json_each(?))` |
| `INTEGER[]` / `ANY()` | `json_each` |
| `ILIKE` | FTS for search; `LIKE … COLLATE NOCASE` for ASCII filters. |
| `::` casts | `CAST` |
| `NUMERIC` money | Integer cents. |
| `Json()` / JSONB | `json.dumps` / `json.loads`. |
| `psycopg2.errors.*` | `sqlite3.IntegrityError` |
| `%s` | `?` |
| `BIGSERIAL` | `INTEGER PRIMARY KEY AUTOINCREMENT` on entity tables. |
| `RETURNING`, `ON CONFLICT`, `FILTER`, window functions | Work as is. |

## 12. Retention

`core.job_runs_prune` keeps 30 days of `core_job_runs`. `core.login_attempts_prune` prunes `core_login_attempts` hourly.

## Tests that pin this

- Migrations apply in order (core before apps), checksums enforced, a failing fixture leaves no partial DDL.
- Fresh apply; an upgrade from the previous tagged release plus a private fixture app applies cleanly on both a fresh and an upgraded database, with a fixture whose historical migration references a deprecated core column.
- The DROP/RENAME lint fails a core migration not named `*_baseline.sql`; the `requires_core` refusal is tested with a fixture declaring `<0.1`.
- `now_iso` is the only timestamp writer (grep test).
- No `httpx` inside `transaction()` (`transaction()` patched to fail on `httpx`/provider calls).
- Nested `transaction()` raises.
- A core merge that invokes a failing CRM subscriber leaves no partial change (a merge with a failing subscriber rolls back entirely).
- After-commit hooks run after `COMMIT` only.
- Two drainers started by hand claim disjoint rows; a crash after an external effect replays once with the same idempotency key.
- Reset an app holding a private record with attachments and notes, create a new record visible to another member, and assert none of the old content attaches to or is readable through it.
- Analytics fixture spanning 2026-03-08 and 2026-11-01 in `America/Chicago` equals hand-computed buckets; money fixture (cents, no float); Unicode search fixture.
- CI image test: `sqlite_version >= 3.51.3`, `fts5: true`.

## Source

Build plan: Architecture → "SQLite rules" (all bullets); §1 (`core_change_log`, `_migrations_applied`); §4 (`record_changes_in`); §7 (PG→SQLite checklist); §11 (`core.outbox_drain`, `core.job_runs_prune`); §13 (Dockerfile sqlite stage, image test); Step 1; Verification.
