-- Custom fields and saved views (docs/agents/records.md §3, §4).

-- ── Custom fields ─────────────────────────────────────────────────────────────
-- Admin-managed definitions per entity type. Never deleted: DELETE archives, so a key stays
-- taken and its values come back if the definition is restored.
CREATE TABLE core_field_definitions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,                         -- a registered entity type, e.g. 'example.widget'
    key         TEXT NOT NULL,
    label       TEXT NOT NULL,
    type        TEXT NOT NULL CHECK (type IN ('text', 'number', 'boolean', 'date', 'select', 'multiselect', 'url', 'user')),
    options     TEXT,                                  -- JSON list of strings; select and multiselect only
    required    INTEGER NOT NULL DEFAULT 0,            -- advisory: shown in the UI, not enforced
    position    INTEGER NOT NULL DEFAULT 0,
    archived_at TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE (entity_type, key)
);

-- One row per set value. A cleared value has no row, so "non-empty" means "has a row".
CREATE TABLE core_field_values (
    entity_type   TEXT NOT NULL,
    entity_id     INTEGER NOT NULL,
    definition_id INTEGER NOT NULL REFERENCES core_field_definitions(id),
    value         TEXT NOT NULL,                       -- JSON
    updated_at    TEXT NOT NULL,
    updated_by    INTEGER REFERENCES core_users(id),
    PRIMARY KEY (entity_type, entity_id, definition_id)
);

-- ── Saved views ───────────────────────────────────────────────────────────────
-- A named set of filters, sort and columns for one screen ("surface"); never rows. Private to
-- the owner until shared. `version` is bumped on every edit; an edit naming an older version
-- is refused as stale.
CREATE TABLE core_saved_views (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    surface       TEXT NOT NULL,                       -- '<app>.<screen>', e.g. 'example.widgets'
    entity_type   TEXT,
    name          TEXT NOT NULL,
    version       INTEGER NOT NULL DEFAULT 1,
    payload       TEXT NOT NULL,                       -- JSON object, opaque to the server
    owner_user_id INTEGER NOT NULL REFERENCES core_users(id),
    is_shared     INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE UNIQUE INDEX core_saved_views_name ON core_saved_views (owner_user_id, surface, name COLLATE NOCASE);
CREATE INDEX core_saved_views_surface ON core_saved_views (surface, is_shared);
