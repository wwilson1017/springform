import threading

from backend.core.mcp_servers import client


def on_startup() -> None:
    """Discover outbound MCP servers in the background: boot never waits on the network."""
    threading.Thread(target=client.refresh_all, name="mcp-discover", daemon=True).start()
