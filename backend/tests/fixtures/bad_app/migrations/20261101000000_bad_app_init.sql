-- Test fixture: every object here breaks an ownership rule except bad_app_things.
CREATE TABLE bad_app_things (
    id        INTEGER PRIMARY KEY,
    note      TEXT,
    widget_id INTEGER REFERENCES example_widgets(id)
);
CREATE TABLE widgets (id INTEGER PRIMARY KEY);
CREATE TABLE core_hack (id INTEGER PRIMARY KEY);
CREATE INDEX bad_app_users_name ON core_users (name);
CREATE VIEW bad_app_peek AS SELECT * FROM example_widgets;
