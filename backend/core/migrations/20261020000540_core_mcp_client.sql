-- The AI tool that made an inbound MCP call (docs/agents/mcp.md §1): its own clientInfo name, else
-- its User-Agent product. Self-reported, for provenance only. NULL for chat, jobs and older rows.
ALTER TABLE core_agent_tool_runs ADD COLUMN client TEXT;
