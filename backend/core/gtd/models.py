"""Response models for Settings, GTD suite. The device token never leaves the server."""

from backend.core.mcp_servers.models import McpServer
from backend.core.platform.models import Out


class GtdPending(Out):
    """A connect waiting for approval in the GTD suite."""

    user_code: str
    url: str  # where the admin approves, opened in a new tab
    interval: int  # seconds between polls
    expires_in: int  # seconds left


class GtdState(Out):
    base_url: str
    server: McpServer | None  # the trusted `gtd` server once connected
    pending: GtdPending | None
