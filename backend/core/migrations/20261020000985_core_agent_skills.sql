-- Whisk's skills (docs/agents/agent.md §2 and "Skills"): named methods an admin approved, listed by
-- name and description in the static prompt and loaded with core_skill_load. Install-shared, like facts.
-- Nothing deletes a row: a rejected proposal stays (so it is not proposed again) and an unused skill
-- is archived.
CREATE TABLE core_agent_skills (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    name                   TEXT NOT NULL,
    description            TEXT NOT NULL CHECK (length(description) <= 60),
    body                   TEXT NOT NULL,
    status                 TEXT NOT NULL CHECK (status IN ('proposed', 'active', 'archived', 'rejected')),
    author                 TEXT NOT NULL,              -- 'agent' (the review), or a core_users id as text
    pinned                 INTEGER NOT NULL DEFAULT 0, -- the curator never archives a pinned skill
    use_count              INTEGER NOT NULL DEFAULT 0,
    last_used_at           TEXT,
    source_conversation_id INTEGER,                    -- no FK, as core_agent_facts: outlives the conversation
    revises_id             INTEGER REFERENCES core_agent_skills(id),  -- an edit proposal's active skill
    revises_sha            TEXT,                       -- that skill's text when proposed: approval needs it unchanged
    created_at             TEXT NOT NULL,
    updated_at             TEXT NOT NULL,              -- name, description or body last changed
    approved_at            TEXT,
    approved_by            INTEGER REFERENCES core_users(id)
);
CREATE UNIQUE INDEX core_agent_skills_active_name ON core_agent_skills (name) WHERE status = 'active';
CREATE INDEX core_agent_skills_status ON core_agent_skills (status, name);

-- The skills review's ledger: one row per review that moved the watermark (the highest turn id it
-- accounted for); max(through_turn_id) is where the next review starts.
CREATE TABLE core_agent_skill_reviews (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    through_turn_id INTEGER NOT NULL,
    ran_at          TEXT NOT NULL,
    status          TEXT NOT NULL,   -- ok | nothing_to_read | bad_reply | discarded | error
    proposals       INTEGER NOT NULL DEFAULT 0
);
