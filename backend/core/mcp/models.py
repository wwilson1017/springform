"""Response models for inbound MCP links. Only minting returns the token (and the URL built from it)."""

from backend.core.platform.models import Out


class McpLink(Out):
    id: int
    label: str
    created_at: str
    last_used_at: str | None


class McpLinkWithOwner(McpLink):
    """A row of `?all=true` (admins): every live link with its owner."""

    user_id: int
    user_name: str
    user_email: str


class NewMcpLink(McpLink):
    url: str
    token: str
