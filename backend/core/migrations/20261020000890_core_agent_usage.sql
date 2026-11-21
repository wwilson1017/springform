-- Whisk's usage ledger (agent.md §5, "Usage ledger"): one row per completed model call, chat and
-- background alike, so an owner can see what the install's AI keys spend. The cost is fixed when
-- the row is written, from the `agent.cost_rates` setting. No FK on the conversation: the ledger
-- outlives a deleted conversation.
CREATE TABLE core_agent_usage (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    at              TEXT NOT NULL,
    user_id         INTEGER REFERENCES core_users(id),  -- the conversation's user; NULL for background calls
    source          TEXT NOT NULL,  -- chat, compaction, observer, test, app (free text: later sources need no migration)
    conversation_id INTEGER,
    provider        TEXT NOT NULL,
    model           TEXT NOT NULL,
    input_tokens    INTEGER NOT NULL DEFAULT 0,  -- uncached input
    output_tokens   INTEGER NOT NULL DEFAULT 0,
    cache_read      INTEGER NOT NULL DEFAULT 0,
    cache_write     INTEGER NOT NULL DEFAULT 0,
    cost_micros     INTEGER  -- micro-dollars at the rate in force; NULL when the model had no rate
);
CREATE INDEX core_agent_usage_at ON core_agent_usage (at);
