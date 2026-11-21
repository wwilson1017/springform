-- Whisk check-ins (agent.md §5, "Check-ins"): a prompt Whisk runs on a schedule as its owner, with
-- look-up tools only. `next_run_at` moves to the next slot before a run starts.
CREATE TABLE core_agent_checkins (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_user_id INTEGER NOT NULL REFERENCES core_users(id),
    name          TEXT NOT NULL,
    prompt        TEXT NOT NULL,
    schedule      TEXT NOT NULL,               -- every:<minutes> | daily@HH:MM | weekly:<mon..sun>@HH:MM, install timezone
    enabled       INTEGER NOT NULL DEFAULT 1,
    next_run_at   TEXT NOT NULL,
    failures      INTEGER NOT NULL DEFAULT 0,  -- failed runs in a row: 3 notify the owner, 10 pause it
    last_run_at   TEXT,
    last_status   TEXT,                        -- ok | silent | error
    last_error    TEXT,
    created_at    TEXT NOT NULL
);
CREATE INDEX core_agent_checkins_due ON core_agent_checkins (enabled, next_run_at);
CREATE INDEX core_agent_checkins_owner ON core_agent_checkins (owner_user_id);
