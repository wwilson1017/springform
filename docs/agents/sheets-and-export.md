# Connected Sheets and export

**What this covers:** §9 in full: the Google service account, the connected-sheets tables, the published sheets client, refresh and its throttle, CSV streaming, the admin export policy and its row rules, and the never-export list.
**Who reads it:** W4 (Sheets + CSV + export policy + Sheets page), any app declaring `sheets` in `app.json` or `EXPORT` in `seed.py`, and anyone streaming a CSV.

Code: the `backend/core/sheets/` package (`api.py` the published client, `service.py`, `google.py`, `jobs.py`, `router.py`) and the `backend/core/export/` package (`csv_export.py`, `policy.py`, `service.py`, `router.py`).

## 1. Service account

Lifted from cake_os (private) `backend/core/google_sheets.py` (261).

1. The service-account JSON is stored encrypted in `core_settings['sheets.service_account_json']`.
2. `service_account_email()` is shown in the UI as: "share with this address: Viewer for read, Editor for write".
3. Settings has a Sheets key card; the Sheets admin page lists connected sheets (`frontend-shell.md`).

Also lifted from cake_os `backend/core/agents/tools/sheets_tools.py`: the A1 helpers (171–270), `forbidden_formula` / `check_values` (111–170), `read_range` (616), `write_range` (845).

## 2. Tables

```sql
core_connected_sheets(
  app, name,
  spreadsheet_id, range,
  mode CHECK (mode IN ('read','write')),
  schedule, enabled,
  last_synced_at, last_error, row_count
)
-- UNIQUE(app, name)
-- seeded from each app.json `sheets: [{name, mode, description}]`

core_sheet_cache(sheet_id, fetched_at, header, rows)
```

Open (pinned by the implementing workstream, which updates this doc): `id` is implied by `POST /api/core/sheets/{id}/refresh` and `core_sheet_cache.sheet_id` but not listed. `schedule`'s format and how it relates to the hourly job. Where the manifest's `description` is stored. The encoding of `header` and `rows` (JSON TEXT is the platform default).

## 3. The published client

```python
sheets.client(slug).read(name)  -> SheetData   # cache only; never calls Google on the request path
sheets.client(slug).write(name, rows)
sheets.client(slug).status(name)
```

1. `read` serves `core_sheet_cache` only.
2. Network calls happen **outside** `transaction()`; the cache write happens inside.
3. `forbidden_formula` / `check_values` guard written values.
4. The client is `backend.core.sheets.api.client(slug)`.

Open (pinned by the implementing workstream, which updates this doc): the `SheetData` shape, what `status` returns, whether `write` is synchronous on the request path and whether it refreshes the cache, and whether `write` on a `mode='read'` sheet is refused.

## 4. Refresh

| Trigger | Contract |
|---|---|
| Job `core.sheets_refresh` | Hourly. |
| `POST /api/core/sheets/{id}/refresh` | Manual refresh, **60 s throttle per range** (shape to be pinned by W4). |

Each refresh fetches from Google outside `transaction()`, then writes `core_sheet_cache` and updates `last_synced_at` / `last_error` / `row_count` inside one.

Open (pinned by the implementing workstream, which updates this doc): the throttle's response when it trips (status code, retry hint).

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
2. Plus each app's `EXPORT` map from `seed.py`: `{"<table>": {"entity_type": "<slug>.<name>" | None, "columns": [...]}}`.
3. Nothing else. The contract test checks that `EXPORT` names only owned tables, real columns and a registered entity type (or `None`).

### Never exported

1. `core_users.password_hash`.
2. TOTP secrets and backup codes.
3. Trusted devices.
4. Login token hashes and MCP token hashes.
5. `core_settings` secrets.
6. Provider keys.
7. Agent conversations, messages and memory.

### Rows follow the same rules as the screen (decided)

1. Each `EXPORT` entry names its entity type, or `None`.
2. Rows the exporting admin cannot `can_read` are left out (other members' private todos, private timeline rows on them).
3. The export is a business-data export. The full `/data` backup remains the privileged recovery path (`deploy.md`).

Open (pinned by the implementing workstream, which updates this doc): the ZIP's file naming (one CSV per table?) and how tables without an entity type (core tables, and app entries with `"entity_type": None`) are row-filtered.

## Tests that pin this

- Export ZIP columns pinned and secrets absent.
- A two-user test proves a private todo is absent from the other admin's export.
- Contract test: `EXPORT` names only owned tables, real columns and a registered entity type (or `None`).

## Source

Build plan: §9 (all), Architecture → app contract (`sheets`, `EXPORT`), §4 (reports CSV), §10 (Sheets admin, Settings cards), §11 (`core.sheets_refresh`), Step 1 (frozen stubs), Verification.
