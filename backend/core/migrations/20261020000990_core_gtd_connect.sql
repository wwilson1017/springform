-- Trusted outbound MCP servers and launcher link tiles (docs/agents/mcp.md §2). `trusted` is set only by
-- the GTD suite connect: that server's read-only tools run without an Approve card.
ALTER TABLE core_agent_mcp_servers ADD COLUMN trusted INTEGER NOT NULL DEFAULT 0;

-- Launcher tiles that open another site in a new tab. A tile made for a server goes when the server does.
CREATE TABLE core_launcher_links (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    title     TEXT NOT NULL,
    url       TEXT NOT NULL,
    icon      TEXT NOT NULL DEFAULT 'grid',
    position  INTEGER NOT NULL DEFAULT 0,
    hidden    INTEGER NOT NULL DEFAULT 0,
    server_id INTEGER REFERENCES core_agent_mcp_servers(id) ON DELETE CASCADE
);
