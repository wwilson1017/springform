"""Inbound MCP: per-user links that let claude.ai, Claude Desktop and Claude Code use Whisk's tools
as that user (docs/agents/mcp.md §1). `links.py` mints, lists and revokes them; `server.py` is the
MCP server; `router.py` holds the link routes and the `/mcp` endpoint.
"""
