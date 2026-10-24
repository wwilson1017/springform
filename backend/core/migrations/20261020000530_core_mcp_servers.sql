-- Outbound MCP servers Whisk may call (docs/agents/mcp.md §2). Admin-managed. The token is
-- encrypted with the install key (enc:v1:, '' = none). tools_json is what the last discovery put
-- in the registry ([{name, description, read_only_hint}], [] when disabled or failing).
CREATE TABLE core_agent_mcp_servers (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    name               TEXT NOT NULL,
    url                TEXT NOT NULL,
    token_enc          TEXT NOT NULL DEFAULT '',
    prefix             TEXT NOT NULL UNIQUE,
    enabled            INTEGER NOT NULL DEFAULT 1,
    tools_json         TEXT NOT NULL DEFAULT '[]',
    last_discovered_at TEXT,
    last_error         TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);
