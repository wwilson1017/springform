-- Whisk (docs/agents/agent.md §2): agents, conversations, messages (+ FTS), tool runs, provider keys.
-- Memory tables are core_agent_memory (…000510); MCP tables come with the MCP workstreams.

CREATE TABLE core_agents (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    slug              TEXT NOT NULL UNIQUE,
    name              TEXT NOT NULL,
    personality       TEXT NOT NULL DEFAULT '',       -- the admin's instructions; '' = none
    soul              TEXT NOT NULL DEFAULT '',
    provider_override TEXT,
    model_override    TEXT,
    model_tier        TEXT NOT NULL DEFAULT 'default' CHECK (model_tier IN ('default', 'light')),
    is_default        INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL
);

-- Private to user_id: every read filters on it (agent.md §3).
CREATE TABLE core_agent_conversations (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id               INTEGER NOT NULL REFERENCES core_users(id),
    agent_id              INTEGER NOT NULL REFERENCES core_agents(id),
    title                 TEXT NOT NULL DEFAULT '',
    is_private            INTEGER NOT NULL DEFAULT 0,
    summary               TEXT,                       -- compaction gist, stored already fenced
    summary_first_kept_id INTEGER,                    -- first message assembled verbatim after the gist
    last_context_tokens   INTEGER,                    -- the provider's last fullness reading
    tainted               INTEGER NOT NULL DEFAULT 0, -- untrusted content has entered this thread
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    compacted_at          TEXT
);
CREATE INDEX core_agent_conversations_user ON core_agent_conversations (user_id, updated_at);

-- One row per user message and per model iteration. content is JSON:
-- {"text": str, "tool_calls"?: [{"tool", "tool_use_id", "args"}], "model"?: str}.
-- Tool results live in core_agent_tool_runs (message_id), not here.
CREATE TABLE core_agent_messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES core_agent_conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'tool')),
    content         TEXT NOT NULL,
    tokens_in       INTEGER,
    tokens_out      INTEGER,
    created_at      TEXT NOT NULL
);
CREATE INDEX core_agent_messages_conversation ON core_agent_messages (conversation_id, id);

CREATE VIRTUAL TABLE core_agent_messages_fts USING fts5 (body, tokenize = 'unicode61 remove_diacritics 2');

CREATE TRIGGER core_agent_messages_fts_insert AFTER INSERT ON core_agent_messages BEGIN
    INSERT INTO core_agent_messages_fts (rowid, body) VALUES (new.id, coalesce(json_extract(new.content, '$.text'), ''));
END;

CREATE TRIGGER core_agent_messages_fts_delete AFTER DELETE ON core_agent_messages BEGIN
    DELETE FROM core_agent_messages_fts WHERE rowid = old.id;
END;

-- The pending store and the audit log (agent.md §6–7). Every tool call a turn makes gets a row.
CREATE TABLE core_agent_tool_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER REFERENCES core_agent_conversations(id) ON DELETE SET NULL,
    message_id      INTEGER REFERENCES core_agent_messages(id) ON DELETE SET NULL,
    tool_use_id     TEXT,
    tool            TEXT NOT NULL,
    tool_def_sha256 TEXT NOT NULL DEFAULT '',
    args            TEXT NOT NULL DEFAULT '{}',
    status          TEXT NOT NULL CHECK (status IN
                        ('pending', 'executing', 'done', 'denied', 'error', 'stale', 'uncertain', 'interrupted')),
    result          TEXT,
    error           TEXT,
    user_id         INTEGER NOT NULL REFERENCES core_users(id),
    source          TEXT NOT NULL CHECK (source IN ('chat', 'mcp', 'job')),
    requested_at    TEXT NOT NULL,
    resolved_at     TEXT,
    resolved_by     INTEGER REFERENCES core_users(id)
);
CREATE INDEX core_agent_tool_runs_conversation ON core_agent_tool_runs (conversation_id);
CREATE INDEX core_agent_tool_runs_message ON core_agent_tool_runs (message_id);
CREATE INDEX core_agent_tool_runs_status ON core_agent_tool_runs (status);

-- One row per model vendor. The key is stored encrypted (secrets.encrypt) and never returned.
CREATE TABLE core_agent_providers (
    provider      TEXT PRIMARY KEY,
    api_key_enc   TEXT NOT NULL DEFAULT '',
    model_default TEXT NOT NULL DEFAULT '',
    model_light   TEXT NOT NULL DEFAULT '',
    enabled       INTEGER NOT NULL DEFAULT 1,
    updated_at    TEXT NOT NULL
);
