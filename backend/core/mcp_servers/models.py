"""Response models for outbound MCP servers. The token is write-only: only `has_token` comes back."""

from backend.core.platform.models import Out


class RemoteTool(Out):
    """A tool as the last discovery found it; `read_only_hint` is the server's claim, shown only."""

    name: str
    description: str
    read_only_hint: bool


class McpServer(Out):
    id: int
    name: str
    url: str
    prefix: str
    enabled: bool
    has_token: bool
    tools: list[RemoteTool]
    last_discovered_at: str | None
    last_error: str | None
    created_at: str
    updated_at: str


class McpServerCheck(Out):
    """Connect and list tools: `tools` is how many; `error` only when it failed."""

    ok: bool
    tools: int
    error: str | None = None
