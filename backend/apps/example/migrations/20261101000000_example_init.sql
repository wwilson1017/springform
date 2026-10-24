-- The integration fixture's one record type.
CREATE TABLE example_widgets (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    color         TEXT,
    owner_user_id INTEGER NOT NULL REFERENCES core_users(id),
    person_id     INTEGER REFERENCES core_people(id) ON DELETE SET NULL,
    is_private    INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX example_widgets_owner ON example_widgets (owner_user_id);
CREATE INDEX example_widgets_person ON example_widgets (person_id);
