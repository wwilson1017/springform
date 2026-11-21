-- Topic reminders (agent.md §5, "Topic reminders"): "when X comes up, remind me of Y". One user's
-- standing note, matched against that user's own typed messages only. A fire is recorded in place;
-- an intent stops firing after `max_fires`, within `cooldown_hours` of the last fire, and from
-- `expires_at`.
CREATE TABLE core_agent_intents (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL REFERENCES core_users(id),
    trigger_terms  TEXT NOT NULL,  -- JSON list of words or phrases; any one matching fires it
    note           TEXT NOT NULL,
    cooldown_hours INTEGER NOT NULL DEFAULT 24,
    max_fires      INTEGER NOT NULL DEFAULT 3,
    fires          INTEGER NOT NULL DEFAULT 0,
    last_fired_at  TEXT,
    expires_at     TEXT NOT NULL,
    created_at     TEXT NOT NULL
);
CREATE INDEX core_agent_intents_user ON core_agent_intents (user_id);
