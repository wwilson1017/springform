-- The field changes one bulk tool run made, or would make while its card waits, read from
-- core_change_log by the server, and its Undo (docs/agents/agent.md §6, "Change lists and Undo").
CREATE TABLE core_agent_change_lists (
    tool_run_id    INTEGER PRIMARY KEY REFERENCES core_agent_tool_runs(id),
    user_id        INTEGER NOT NULL REFERENCES core_users(id),
    rows           TEXT NOT NULL,   -- JSON [{entity_type, entity_id, field, old, new}]: staged, then as applied
    notes          TEXT NOT NULL,   -- JSON [str]: what the tool's result said beyond the rows (`errors`, `notes`)
    created_at     TEXT NOT NULL,
    staged_mark    INTEGER,         -- newest core_change_log id when the card was staged (null: never staged)
    applied_at     TEXT,
    last_change_id INTEGER,         -- newest core_change_log id when the apply finished
    undone_at      TEXT,
    undo_result    TEXT             -- JSON {reverted, skipped: [{entity_type, entity_id, reason}]}
);

-- What the model reads after the run's result once the user has undone its list.
ALTER TABLE core_agent_tool_runs ADD COLUMN undo_note TEXT;
