# Connected Sheets and export

**What this covers:** §9 in full: the Google service account, the connected-sheets tables, the published sheets client, refresh and its throttle, CSV streaming, the admin export policy and its row rules, and the never-export list.
**Who reads it:** W4 (Sheets + CSV + export policy + Sheets card), any app declaring `sheets` in `app.json` or `EXPORT` in `seed.py`, and anyone streaming a CSV.

Code: the `backend/core/sheets/` package (`api.py` the published client, `service.py`, `google.py`, `jobs.py`, `router.py`) and the `backend/core/export/` package (`csv_export.py`, `policy.py`, `service.py`, `router.py`).

## 1. Service account

Google access is `backend/core/sheets/google.py`: a new REST client, `GoogleSheets`, that signs its own service-account JWT, with `read(spreadsheet_id, a1)` and `write(spreadsheet_id, a1, rows)`. With `SHEETS_FAKE=1` it is `FakeSheets`, a canned table for local runs and tests. Only the guards and A1 helpers were lifted from cake_os.

1. The service-account JSON is stored encrypted in `core_settings['sheets.service_account_json']`, written by the admin-only `PUT /api/core/sheets/credentials {service_account_json}`.
2. The admin-only `GET /api/core/sheets/credentials` returns `{configured, service_account_email}`. The UI shows the email as: "share with this address: Viewer for read, Editor for write".
3. Settings → Google Sheets (one admin-only card, `frontend/src/core/integrations/`) holds the service-account key and lists the connected sheets with Refresh and a preview drawer. There is no separate Sheets page.

Lifted from cake_os `backend/core/agents/tools/sheets_tools.py`: the A1 helpers (171–270) and `forbidden_formula` / `check_values` (111–170).

## 2. Tables

```sql
core_connected_sheets(
  id, app, name, description,
  spreadsheet_id, range,           -- range in A1 notation
  mode CHECK (mode IN ('read','write')),
  schedule CHECK (schedule IN ('hourly','daily','manual')) DEFAULT 'hourly', enabled,
  last_synced_at, last_error, row_count,
  last_attempt_at,                 -- the last refresh started; drives the 60 s throttle
  created_at, updated_at
)
-- UNIQUE(app, name)
-- seeded from each app.json `sheets: [{name, mode, description}]`

core_sheet_cache(sheet_id PK, fetched_at, header JSON, rows JSON)   -- header: list of strings; rows: lists of strings
```

## 3. The published client

```python
sheets.client(slug).read(name)  -> SheetData   # cache only; never calls Google on the request path
sheets.client(slug).write(name, rows)
sheets.client(slug).status(name)
```

1. `read` serves `core_sheet_cache` only and returns `SheetData(header, rows, fetched_at, stale)`. Every row is padded to the header's width, and all cells are strings. `stale` is true when nothing is cached, the last refresh failed, or the cache is older than twice its schedule.
2. `status` returns `{configured, enabled, last_synced_at, last_error, row_count}`. `read` and `status` have `_in(conn, …)` forms.
3. `write` replaces a write-mode sheet's range synchronously and returns the rows Google updated. It calls Google, so it raises inside `transaction()` and has no `_in` form. It refuses (422) a read-mode sheet or rows that fail `check_values`, answers 502 when Google fails, and leaves the cache untouched.
4. The client is `backend.core.sheets.api.client(slug)`; an undeclared sheet name is 404.

## 4. Refresh

| Trigger | Contract |
|---|---|
| Job `core.sheets_refresh` | Hourly. |
| `POST /api/core/sheets/{id}/refresh` | Manual refresh, throttled to one per **60 s per connected sheet** (`last_attempt_at`). |

Each refresh fetches from Google outside `transaction()`, then writes `core_sheet_cache` and updates `last_synced_at` / `last_error` / `row_count` inside one.

A tripped throttle answers **429** `{detail: "throttled", retry_after}` with a `Retry-After` header. The other admin routes are `GET /api/core/sheets`, `PATCH /api/core/sheets/{id}` and `GET /api/core/sheets/{id}/preview`.

## 5. CSV streaming (`backend/core/export/csv_export.py`)

```python
stream_csv(header, rows, filename)
```

1. Every cell goes through CakeCRM `crm/export.py:90-102` `_cell` (formula-injection guard).
2. Used by `GET /api/core/reports/{key}/csv`. The admin export writes each table with `csv_export.write_csv(f, header, rows)` into the ZIP, which applies the same guard.
3. It is `backend.core.export.csv_export.stream_csv`.

## 6. Admin export (`GET /api/core/export`)

An admin downloads a ZIP of CSVs.

### Column allow-list

1. Core tables and columns listed in `CORE_EXPORT` in `backend/core/export/policy.py`.
2. Plus each app's `EXPORT` map from `seed.py`, in the same shape as `CORE_EXPORT`: `{"<table>": {"entity": ..., "columns": [...], "id_column"?: ..., "where"?: ..., "owner_column"?: ...}}`.
   - `entity`: the entity type that authorizes each row, or `None` for no row check. It may name row columns in braces, filled from the row: `"{entity_type}"` (timeline, files), `"core.{owner_type}"`.
   - `id_column`: the row column holding that record's id; default `"id"`, meaning the row is the record.
   - `where`: a fixed SQL filter on the table.
   - `owner_column`: for rows whose record id is NULL (attached to nothing), the column naming the user they belong to. Such rows go only to that user; without it they are left out.
3. Nothing else. The contract test checks that an app's `EXPORT` names only tables the app owns and real columns, that every entry has an `entity` (one of the app's own registered entity types, or `None`), and that `id_column` and `owner_column` name real columns. The brace forms are used by `CORE_EXPORT`.

### Never exported

`backend/core/export/policy.py` defines these, and `policy.check` enforces them on the merged policy:

1. Whole tables: `core_totp`, `core_trusted_devices`, `core_login_tokens`, `core_login_attempts`, `core_settings`, `core_outbox`, `core_backups`, `core_sheet_cache`.
2. Every table starting `core_agent_` or `core_mcp_`: conversations, messages, memory, provider keys and MCP tokens.
3. Columns, wherever they appear: `password_hash`, `secret_enc`, `backup_codes`, `token_hash`.

### Rows follow the same rules as the screen (decided)

1. Each `EXPORT` entry names its entity type in `entity`.
2. A row is exported only when `entities.authorize(read)` passes for the exporting admin. Rows they cannot read are left out (other members' private todos, private timeline rows on them). An entry whose `entity` is `None` has no row check.
3. The export is a business-data export. The full `/data` backup remains the privileged recovery path (`deploy.md`).

The ZIP is `springform-export-<timestamp>.zip`. It holds one `<table>.csv` per allowed table, plus `manifest.json` with `{version, created_at, exported_by, tables: [{name, file, columns, rows}]}`.

## Tests that pin this

- Export ZIP columns pinned and secrets absent.
- A two-user test proves a private todo is absent from the other admin's export.
- Contract test: `EXPORT` names only owned tables and real columns, and each entry's `entity` is one of the app's entity types or `None`.

## Source

Build plan: §9 (all), Architecture → app contract (`sheets`, `EXPORT`), §4 (reports CSV), §10 (Sheets admin, Settings cards), §11 (`core.sheets_refresh`), Step 1 (frozen stubs), Verification.
