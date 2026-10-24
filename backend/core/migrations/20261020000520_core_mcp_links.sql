-- Inbound MCP links (docs/agents/mcp.md §1): each is an API key for its user. Only the token's
-- sha256 is stored; the token itself is shown once, when the link is made.
CREATE TABLE core_agent_mcp_links (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES core_users(id),
    token_hash   TEXT NOT NULL UNIQUE,
    label        TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at   TEXT
);
CREATE INDEX core_agent_mcp_links_user ON core_agent_mcp_links (user_id);
