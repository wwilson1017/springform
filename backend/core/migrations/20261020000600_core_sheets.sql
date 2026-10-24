-- Connected Google Sheets (docs/agents/sheets-and-export.md). One row per sheet an app declares
-- in app.json `sheets`, seeded on startup; an admin fills in spreadsheet_id and range.

CREATE TABLE core_connected_sheets (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    app            TEXT NOT NULL,
    name           TEXT NOT NULL,
    description    TEXT NOT NULL DEFAULT '',
    spreadsheet_id TEXT NOT NULL DEFAULT '',
    range          TEXT NOT NULL DEFAULT '',            -- A1 notation, e.g. 'Widgets'!A1:F
    mode           TEXT NOT NULL CHECK (mode IN ('read', 'write')),
    schedule       TEXT NOT NULL DEFAULT 'hourly' CHECK (schedule IN ('hourly', 'daily', 'manual')),
    enabled        INTEGER NOT NULL DEFAULT 1,
    last_synced_at TEXT,                                -- last successful read or write
    last_error     TEXT,                                -- NULL after a success
    row_count      INTEGER,                             -- data rows cached (read) or written (write)
    last_attempt_at TEXT,                               -- last refresh started; the 60 s throttle
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    UNIQUE (app, name)
);

-- What the last successful refresh fetched. Apps read only this; never Google on a request.
CREATE TABLE core_sheet_cache (
    sheet_id   INTEGER PRIMARY KEY REFERENCES core_connected_sheets(id) ON DELETE CASCADE,
    fetched_at TEXT NOT NULL,
    header     TEXT NOT NULL DEFAULT '[]',             -- JSON list of strings
    rows       TEXT NOT NULL DEFAULT '[]'              -- JSON list of lists of strings
);
