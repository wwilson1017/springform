-- Whisk's install-shared business memory (docs/agents/agent.md "Memory and privacy").
-- Conversations stay private to their user; nothing here stores message text.

-- Facts: one plain sentence each, valid from `valid_from` until `invalid_from` (NULL = still true).
-- Provenance (source_conversation_id, author_user_id, created_at) is shown to admins only.
-- source_conversation_id has no foreign key: the conversation table belongs to the engine and
-- a deleted conversation must not take the business fact with it.
CREATE TABLE core_agent_facts (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    text                   TEXT NOT NULL,
    tags                   TEXT NOT NULL DEFAULT '[]',          -- JSON array of strings
    valid_from             TEXT NOT NULL,
    invalid_from           TEXT,
    invalidated_by         INTEGER REFERENCES core_users(id),
    superseded_by          INTEGER REFERENCES core_agent_facts(id),
    source_conversation_id INTEGER,
    author_user_id         INTEGER NOT NULL REFERENCES core_users(id),
    created_at             TEXT NOT NULL
);
CREATE INDEX core_agent_facts_open ON core_agent_facts (invalid_from, valid_from);

CREATE VIRTUAL TABLE core_agent_facts_fts USING fts5 (
    text, tags, content = 'core_agent_facts', content_rowid = 'id',
    tokenize = 'unicode61 remove_diacritics 2'
);
CREATE TRIGGER core_agent_facts_fts_insert AFTER INSERT ON core_agent_facts BEGIN
    INSERT INTO core_agent_facts_fts (rowid, text, tags) VALUES (NEW.id, NEW.text, NEW.tags);
END;
CREATE TRIGGER core_agent_facts_fts_update AFTER UPDATE OF text, tags ON core_agent_facts BEGIN
    INSERT INTO core_agent_facts_fts (core_agent_facts_fts, rowid, text, tags) VALUES ('delete', OLD.id, OLD.text, OLD.tags);
    INSERT INTO core_agent_facts_fts (rowid, text, tags) VALUES (NEW.id, NEW.text, NEW.tags);
END;
CREATE TRIGGER core_agent_facts_fts_delete AFTER DELETE ON core_agent_facts BEGIN
    INSERT INTO core_agent_facts_fts (core_agent_facts_fts, rowid, text, tags) VALUES ('delete', OLD.id, OLD.text, OLD.tags);
END;

-- The observer's ledger, one row per conversation: after_turn() marks it pending, the nightly
-- observer reads user messages after through_message_id and moves the mark forward.
-- No foreign key to core_agent_conversations (the engine's table, migrated separately).
CREATE TABLE core_agent_observations (
    conversation_id    INTEGER PRIMARY KEY,
    through_message_id INTEGER NOT NULL DEFAULT 0,
    pending            INTEGER NOT NULL DEFAULT 1,
    marked_at          TEXT NOT NULL,
    observed_at        TEXT,
    facts_added        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX core_agent_observations_pending ON core_agent_observations (pending, marked_at);

-- Context files: admin-edited markdown per agent. soul.md and MEMORY.md are protected: they
-- change only through the confirmed chat tool, by an admin. agent_slug matches core_agents.slug
-- (the engine's table) by value.
CREATE TABLE core_agent_context_files (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_slug   TEXT NOT NULL,
    filename     TEXT NOT NULL COLLATE NOCASE,
    content      TEXT NOT NULL DEFAULT '',
    is_protected INTEGER NOT NULL DEFAULT 0,
    updated_at   TEXT NOT NULL,
    updated_by   INTEGER REFERENCES core_users(id),
    UNIQUE (agent_slug, filename)
);

CREATE VIRTUAL TABLE core_agent_context_files_fts USING fts5 (
    filename, content, content = 'core_agent_context_files', content_rowid = 'id',
    tokenize = 'unicode61 remove_diacritics 2'
);
CREATE TRIGGER core_agent_context_files_fts_insert AFTER INSERT ON core_agent_context_files BEGIN
    INSERT INTO core_agent_context_files_fts (rowid, filename, content) VALUES (NEW.id, NEW.filename, NEW.content);
END;
CREATE TRIGGER core_agent_context_files_fts_update AFTER UPDATE OF filename, content ON core_agent_context_files BEGIN
    INSERT INTO core_agent_context_files_fts (core_agent_context_files_fts, rowid, filename, content)
    VALUES ('delete', OLD.id, OLD.filename, OLD.content);
    INSERT INTO core_agent_context_files_fts (rowid, filename, content) VALUES (NEW.id, NEW.filename, NEW.content);
END;
CREATE TRIGGER core_agent_context_files_fts_delete AFTER DELETE ON core_agent_context_files BEGIN
    INSERT INTO core_agent_context_files_fts (core_agent_context_files_fts, rowid, filename, content)
    VALUES ('delete', OLD.id, OLD.filename, OLD.content);
END;
