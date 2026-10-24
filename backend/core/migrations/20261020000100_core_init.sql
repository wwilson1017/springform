-- Springform core schema, v0.1. Never edit this file once it has landed: later workstreams add
-- their own 20261020HHMMSS_core_<area>.sql. Within a major version core never drops or renames.
-- Timestamps are TEXT in canonical UTC form (YYYY-MM-DDTHH:MM:SSZ), written by core.clock only.
-- Tables other rows point at polymorphically use AUTOINCREMENT so a deleted id is never reused.
-- _migrations_applied is created by the migration runner before this file runs.

-- ── Users and login ─────────────────────────────────────────────────────────

CREATE TABLE core_users (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    email          TEXT NOT NULL,
    name           TEXT NOT NULL DEFAULT '',
    role           TEXT NOT NULL CHECK (role IN ('admin', 'member', 'system')),
    password_hash  TEXT NOT NULL DEFAULT '!',          -- '!' never authenticates
    google_sub     TEXT UNIQUE,
    is_active      INTEGER NOT NULL DEFAULT 1,
    token_epoch    INTEGER NOT NULL DEFAULT 0,         -- bumped to end every session of this user
    tz             TEXT,                               -- IANA zone; NULL = the install timezone
    invited_by     INTEGER REFERENCES core_users(id),
    last_login_at  TEXT,
    deactivated_at TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE UNIQUE INDEX core_users_email ON core_users (lower(trim(email)));

-- The system principal: attributes unattended actions (jobs, tool runs). It can never
-- authenticate, and is excluded from user listings and "every active user" expansions.
INSERT INTO core_users (id, email, name, role, password_hash, is_active, created_at, updated_at)
VALUES (0, 'system@springform.local', 'System', 'system', '!', 1, '2026-10-20T00:00:00Z', '2026-10-20T00:00:00Z');

CREATE TABLE core_totp (
    user_id      INTEGER PRIMARY KEY REFERENCES core_users(id) ON DELETE CASCADE,
    enabled      INTEGER NOT NULL DEFAULT 0,
    secret_enc   TEXT NOT NULL DEFAULT '',
    backup_codes TEXT NOT NULL DEFAULT '[]',           -- JSON list of bcrypt hashes
    last_used_at TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE core_trusted_devices (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES core_users(id) ON DELETE CASCADE,
    label      TEXT NOT NULL DEFAULT '',
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX core_trusted_devices_user ON core_trusted_devices (user_id);

CREATE TABLE core_login_tokens (
    token_hash TEXT PRIMARY KEY,                       -- sha256 of the token; the token is shown once
    user_id    INTEGER REFERENCES core_users(id) ON DELETE CASCADE,   -- NULL for the setup token
    purpose    TEXT NOT NULL CHECK (purpose IN ('invite', 'reset', 'setup')),
    expires_at TEXT,                                   -- NULL = until used (the setup token)
    used_at    TEXT,
    created_by INTEGER REFERENCES core_users(id),
    created_at TEXT NOT NULL
);
CREATE INDEX core_login_tokens_user ON core_login_tokens (user_id);

CREATE TABLE core_login_attempts (
    key TEXT NOT NULL,                                 -- 'acct:<email>' or 'ip:<address>'
    at  TEXT NOT NULL
);
CREATE INDEX core_login_attempts_key ON core_login_attempts (key, at);

-- ── Install state ───────────────────────────────────────────────────────────

CREATE TABLE core_settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,                          -- JSON; enc:v1:… when is_secret
    is_secret  INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    updated_by INTEGER REFERENCES core_users(id)
);

CREATE TABLE core_apps_state (
    slug     TEXT PRIMARY KEY,
    hidden   INTEGER NOT NULL DEFAULT 0,
    position INTEGER
);

CREATE TABLE core_change_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    at         TEXT NOT NULL,
    user_id    INTEGER REFERENCES core_users(id),
    app        TEXT NOT NULL,
    entity     TEXT NOT NULL,                          -- entity type, e.g. 'core.person'
    entity_id  INTEGER NOT NULL,
    field      TEXT NOT NULL,
    old        TEXT,                                   -- JSON
    new        TEXT,                                   -- JSON
    reason     TEXT,
    request_id TEXT,
    deleted_at TEXT                                    -- set when the record is deleted; history stays
);
CREATE INDEX core_change_log_entity ON core_change_log (entity, entity_id);
CREATE INDEX core_change_log_at ON core_change_log (at);

CREATE TABLE core_job_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    job           TEXT NOT NULL,
    app           TEXT NOT NULL,
    triggered_by  TEXT NOT NULL CHECK (triggered_by IN ('schedule', 'manual', 'nudge')),
    status        TEXT NOT NULL CHECK (status IN ('running', 'ok', 'error', 'timed_out', 'interrupted', 'skipped')),
    scheduled_for TEXT,                                -- install-local day an `at` job's run covers
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    error         TEXT
);
CREATE INDEX core_job_runs_job ON core_job_runs (job, started_at);

CREATE TABLE core_outbox (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    hook         TEXT NOT NULL,
    payload      TEXT NOT NULL,                        -- JSON
    created_at   TEXT NOT NULL,
    available_at TEXT NOT NULL,                        -- not claimable before this (retry backoff)
    claimed_at   TEXT,
    attempts     INTEGER NOT NULL DEFAULT 0,
    processed_at TEXT,
    last_error   TEXT,
    dead_at      TEXT
);
CREATE INDEX core_outbox_pending ON core_outbox (available_at) WHERE processed_at IS NULL AND dead_at IS NULL;

CREATE TABLE core_requests (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    app          TEXT,                                 -- slug the request is about; NULL = core
    description  TEXT NOT NULL DEFAULT '',
    issue_number INTEGER,
    issue_url    TEXT,
    state        TEXT NOT NULL DEFAULT 'open',
    labels       TEXT NOT NULL DEFAULT '[]',           -- JSON
    created_by   INTEGER REFERENCES core_users(id),
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    synced_at    TEXT
);

CREATE TABLE core_backups (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL CHECK (status IN ('running', 'ok', 'error', 'skipped')),
    snapshot    TEXT,                                  -- file name under <data>/backups
    manifest    TEXT,
    byte_size   INTEGER,
    sha256      TEXT,
    error       TEXT
);

-- ── Contacts directory ──────────────────────────────────────────────────────

CREATE TABLE core_people (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    given_name     TEXT,
    family_name    TEXT,
    email          TEXT,                               -- mirrors the primary email channel
    phone          TEXT,                               -- mirrors the primary phone channel
    title          TEXT,
    source         TEXT,
    status         TEXT,
    tags           TEXT NOT NULL DEFAULT '[]',         -- JSON
    notes          TEXT,
    owner_user_id  INTEGER REFERENCES core_users(id),
    archived_at    TEXT,
    merged_into_id INTEGER REFERENCES core_people(id),
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE INDEX core_people_merged ON core_people (merged_into_id);

CREATE TABLE core_organizations (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    domain         TEXT,
    website        TEXT,
    industry       TEXT,
    email          TEXT,
    phone          TEXT,
    notes          TEXT,
    source         TEXT,
    status         TEXT,
    tags           TEXT NOT NULL DEFAULT '[]',         -- JSON
    owner_user_id  INTEGER REFERENCES core_users(id),
    archived_at    TEXT,
    merged_into_id INTEGER REFERENCES core_organizations(id),
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE UNIQUE INDEX core_organizations_name ON core_organizations (lower(trim(name))) WHERE merged_into_id IS NULL;

CREATE TABLE core_person_organizations (
    id              INTEGER PRIMARY KEY,
    person_id       INTEGER NOT NULL REFERENCES core_people(id) ON DELETE CASCADE,
    organization_id INTEGER NOT NULL REFERENCES core_organizations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL DEFAULT '',
    is_primary      INTEGER NOT NULL DEFAULT 0,
    started_on      TEXT,
    ended_on        TEXT,
    created_at      TEXT NOT NULL,
    UNIQUE (person_id, organization_id, role)
);
CREATE UNIQUE INDEX core_person_organizations_primary ON core_person_organizations (person_id) WHERE is_primary = 1;
CREATE INDEX core_person_organizations_org ON core_person_organizations (organization_id);

CREATE TABLE core_addresses (
    id          INTEGER PRIMARY KEY,
    owner_type  TEXT NOT NULL CHECK (owner_type IN ('person', 'organization')),
    owner_id    INTEGER NOT NULL,
    kind        TEXT,
    line1       TEXT,
    line2       TEXT,
    city        TEXT,
    region      TEXT,
    postal_code TEXT,
    country     TEXT,
    is_primary  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX core_addresses_owner ON core_addresses (owner_type, owner_id);

CREATE TABLE core_contact_channels (
    id         INTEGER PRIMARY KEY,
    owner_type TEXT NOT NULL CHECK (owner_type IN ('person', 'organization')),
    owner_id   INTEGER NOT NULL,
    kind       TEXT NOT NULL CHECK (kind IN ('email', 'phone', 'url', 'other')),
    value      TEXT NOT NULL,
    label      TEXT,
    is_primary INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX core_contact_channels_owner ON core_contact_channels (owner_type, owner_id);

-- One FTS row per person (rowid = 2*id) and organization (rowid = 2*id + 1).
CREATE VIRTUAL TABLE core_contacts_fts USING fts5 (
    owner_type UNINDEXED, owner_id UNINDEXED, name, email, phone, body,
    tokenize = 'unicode61 remove_diacritics 2'
);
CREATE TRIGGER core_people_fts_insert AFTER INSERT ON core_people BEGIN
    INSERT INTO core_contacts_fts (rowid, owner_type, owner_id, name, email, phone, body)
    VALUES (2 * NEW.id, 'person', NEW.id, NEW.name, NEW.email, NEW.phone,
            concat_ws(' ', NEW.given_name, NEW.family_name, NEW.title, NEW.notes));
END;
CREATE TRIGGER core_people_fts_update AFTER UPDATE ON core_people BEGIN
    DELETE FROM core_contacts_fts WHERE rowid = 2 * OLD.id;
    INSERT INTO core_contacts_fts (rowid, owner_type, owner_id, name, email, phone, body)
    VALUES (2 * NEW.id, 'person', NEW.id, NEW.name, NEW.email, NEW.phone,
            concat_ws(' ', NEW.given_name, NEW.family_name, NEW.title, NEW.notes));
END;
CREATE TRIGGER core_people_fts_delete AFTER DELETE ON core_people BEGIN
    DELETE FROM core_contacts_fts WHERE rowid = 2 * OLD.id;
END;
CREATE TRIGGER core_organizations_fts_insert AFTER INSERT ON core_organizations BEGIN
    INSERT INTO core_contacts_fts (rowid, owner_type, owner_id, name, email, phone, body)
    VALUES (2 * NEW.id + 1, 'organization', NEW.id, NEW.name, NEW.email, NEW.phone,
            concat_ws(' ', NEW.domain, NEW.website, NEW.industry, NEW.notes));
END;
CREATE TRIGGER core_organizations_fts_update AFTER UPDATE ON core_organizations BEGIN
    DELETE FROM core_contacts_fts WHERE rowid = 2 * OLD.id + 1;
    INSERT INTO core_contacts_fts (rowid, owner_type, owner_id, name, email, phone, body)
    VALUES (2 * NEW.id + 1, 'organization', NEW.id, NEW.name, NEW.email, NEW.phone,
            concat_ws(' ', NEW.domain, NEW.website, NEW.industry, NEW.notes));
END;
CREATE TRIGGER core_organizations_fts_delete AFTER DELETE ON core_organizations BEGIN
    DELETE FROM core_contacts_fts WHERE rowid = 2 * OLD.id + 1;
END;

-- ── Record services ─────────────────────────────────────────────────────────

CREATE TABLE core_timeline (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type    TEXT NOT NULL,
    entity_id      INTEGER NOT NULL,
    kind           TEXT NOT NULL CHECK (kind IN ('note', 'comment', 'field_change', 'system')),
    body           TEXT NOT NULL DEFAULT '',
    changes        TEXT,                               -- JSON [{field, old, new}] for field_change
    author_user_id INTEGER REFERENCES core_users(id),
    created_at     TEXT NOT NULL,
    updated_at     TEXT,
    archived_at    TEXT
);
CREATE INDEX core_timeline_entity ON core_timeline (entity_type, entity_id, created_at);

CREATE TABLE core_timeline_mentions (
    id           INTEGER PRIMARY KEY,
    timeline_id  INTEGER NOT NULL REFERENCES core_timeline(id) ON DELETE CASCADE,
    user_id      INTEGER NOT NULL REFERENCES core_users(id),
    display_name TEXT NOT NULL,
    UNIQUE (timeline_id, user_id)
);

CREATE VIRTUAL TABLE core_timeline_fts USING fts5 (
    body, content = 'core_timeline', content_rowid = 'id',
    tokenize = 'unicode61 remove_diacritics 2'
);
CREATE TRIGGER core_timeline_fts_insert AFTER INSERT ON core_timeline BEGIN
    INSERT INTO core_timeline_fts (rowid, body) VALUES (NEW.id, NEW.body);
END;
CREATE TRIGGER core_timeline_fts_update AFTER UPDATE OF body ON core_timeline BEGIN
    INSERT INTO core_timeline_fts (core_timeline_fts, rowid, body) VALUES ('delete', OLD.id, OLD.body);
    INSERT INTO core_timeline_fts (rowid, body) VALUES (NEW.id, NEW.body);
END;
CREATE TRIGGER core_timeline_fts_delete AFTER DELETE ON core_timeline BEGIN
    INSERT INTO core_timeline_fts (core_timeline_fts, rowid, body) VALUES ('delete', OLD.id, OLD.body);
END;

-- Attachment bytes live on the volume at <data>/files/<sha[:2]>/<sha>; rows only describe them.
CREATE TABLE core_file_blobs (
    sha256             TEXT PRIMARY KEY,
    byte_size          INTEGER NOT NULL,
    created_at         TEXT NOT NULL,
    unreferenced_since TEXT                            -- set when the last core_files row goes
);

CREATE TABLE core_files (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id   INTEGER NOT NULL,
    timeline_id INTEGER REFERENCES core_timeline(id) ON DELETE SET NULL,
    filename    TEXT NOT NULL,
    mime_type   TEXT NOT NULL,
    byte_size   INTEGER NOT NULL,
    sha256      TEXT NOT NULL REFERENCES core_file_blobs(sha256),
    thumb       BLOB,
    uploaded_by INTEGER REFERENCES core_users(id),
    created_at  TEXT NOT NULL,
    UNIQUE (entity_type, entity_id, sha256)
);
CREATE INDEX core_files_sha ON core_files (sha256);
