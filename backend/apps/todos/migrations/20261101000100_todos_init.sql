-- Todos: per-user GTD with private and team rows (plan §8; service.py states the rules).
-- Areas, projects and items each have an owner and a visibility: 'private' is the owner's
-- alone, 'team' is every member's. Nothing in SQL enforces who may see what; the service does.
-- `rev` is the todos_journal rev that last stamped the row (the change feed).

CREATE TABLE todos_areas (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_user_id    INTEGER NOT NULL REFERENCES core_users(id),
    visibility       TEXT NOT NULL DEFAULT 'private' CHECK (visibility IN ('private', 'team')),
    assignee_user_id INTEGER REFERENCES core_users(id),
    name             TEXT NOT NULL,
    notes            TEXT NOT NULL DEFAULT '',
    status           TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'dropped')),
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    rev              INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX todos_areas_owner ON todos_areas (owner_user_id, visibility);

CREATE TABLE todos_projects (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_user_id    INTEGER NOT NULL REFERENCES core_users(id),
    visibility       TEXT NOT NULL DEFAULT 'private' CHECK (visibility IN ('private', 'team')),
    assignee_user_id INTEGER REFERENCES core_users(id),
    name             TEXT NOT NULL,
    notes            TEXT NOT NULL DEFAULT '',
    purpose          TEXT NOT NULL DEFAULT '',           -- why it matters
    outcome          TEXT NOT NULL DEFAULT '',           -- what done looks like
    area_id          INTEGER REFERENCES todos_areas(id),
    status           TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'someday', 'completed', 'dropped')),
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    rev              INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX todos_projects_owner ON todos_projects (owner_user_id, visibility);
CREATE INDEX todos_projects_area ON todos_projects (area_id);

CREATE TABLE todos_items (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_user_id    INTEGER NOT NULL REFERENCES core_users(id),
    visibility       TEXT NOT NULL DEFAULT 'private' CHECK (visibility IN ('private', 'team')),
    assignee_user_id INTEGER REFERENCES core_users(id),
    title            TEXT NOT NULL,
    notes            TEXT NOT NULL DEFAULT '',
    project_id       INTEGER REFERENCES todos_projects(id),
    area_id          INTEGER REFERENCES todos_areas(id),  -- its own; NULL means its project's
    context          TEXT NOT NULL DEFAULT '',
    tags             TEXT NOT NULL DEFAULT '[]',          -- JSON array of strings
    people           TEXT NOT NULL DEFAULT '[]',          -- JSON array of strings
    status           TEXT NOT NULL DEFAULT 'inbox'
                     CHECK (status IN ('inbox', 'next_action', 'waiting_for', 'delegated', 'someday_maybe', 'done', 'dropped')),
    star             INTEGER NOT NULL DEFAULT 0,
    due_date         TEXT,                                -- YYYY-MM-DD, date-only by design
    revisit_on       TEXT,                                -- YYYY-MM-DD: off the working lists until then
    repeat           TEXT NOT NULL DEFAULT '',            -- '', daily, weekdays, weekly, monthly, yearly, every:N
    auto_star_on_due INTEGER NOT NULL DEFAULT 0,
    entity_type      TEXT,                                -- a linked record, any registered entity
    entity_id        INTEGER,
    source           TEXT NOT NULL DEFAULT 'app' CHECK (source IN ('ui', 'agent', 'app')),
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    completed_at     TEXT,
    rev              INTEGER NOT NULL DEFAULT 0,
    CHECK ((entity_type IS NULL) = (entity_id IS NULL))
);
CREATE INDEX todos_items_owner ON todos_items (owner_user_id, status);
CREATE INDEX todos_items_team ON todos_items (visibility, status);
CREATE INDEX todos_items_assignee ON todos_items (assignee_user_id);
CREATE INDEX todos_items_project ON todos_items (project_id);
CREATE INDEX todos_items_area ON todos_items (area_id);
CREATE INDEX todos_items_entity ON todos_items (entity_type, entity_id);

-- One row per audience: user_id 0 is the team (the system principal's id, on purpose), any
-- other is that user's private rows. `rev` is the audience's head in todos_journal. `floor`
-- (team row only) is the rev before the first stamp since install or the last app reset:
-- a cursor at or below it predates a reset and gets a full resend.
CREATE TABLE todos_sync (
    user_id        INTEGER PRIMARY KEY REFERENCES core_users(id),
    rev            INTEGER NOT NULL DEFAULT 0,
    floor          INTEGER NOT NULL DEFAULT 0,
    last_review_at TEXT
);

-- The change journal: the latest stamp of each row for each audience it was in. AUTOINCREMENT
-- so a rev is never reused, even after an app reset empties this table.
CREATE TABLE todos_journal (
    rev      INTEGER PRIMARY KEY AUTOINCREMENT,
    kind     TEXT NOT NULL CHECK (kind IN ('item', 'project', 'area')),
    row_id   INTEGER NOT NULL,
    audience INTEGER NOT NULL
);
CREATE UNIQUE INDEX todos_journal_row ON todos_journal (kind, row_id, audience);
CREATE INDEX todos_journal_audience ON todos_journal (audience, rev);
