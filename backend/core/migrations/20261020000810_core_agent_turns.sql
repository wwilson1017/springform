-- Server-owned Whisk turns (agent.md §5): one row per turn, and the events it streamed, so a
-- client that dropped can replay from a seq. The events are transport, not the record (the
-- conversation's messages and tool runs are), hence CASCADE and the 7-day prune.
CREATE TABLE core_agent_turns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES core_agent_conversations(id) ON DELETE CASCADE,
    user_id         INTEGER NOT NULL REFERENCES core_users(id),
    status          TEXT NOT NULL CHECK (status IN ('running', 'done', 'error', 'cancelled', 'interrupted')),
    started_at      TEXT NOT NULL,
    ended_at        TEXT
);
CREATE INDEX core_agent_turns_conversation ON core_agent_turns (conversation_id);
CREATE INDEX core_agent_turns_ended ON core_agent_turns (ended_at);

CREATE TABLE core_agent_turn_events (
    turn_id INTEGER NOT NULL REFERENCES core_agent_turns(id) ON DELETE CASCADE,
    seq     INTEGER NOT NULL,
    event   TEXT NOT NULL,  -- JSON: the event exactly as streamed, seq included
    PRIMARY KEY (turn_id, seq)
);
