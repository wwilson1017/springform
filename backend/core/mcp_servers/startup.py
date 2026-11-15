import threading

from backend.core.mcp_servers import client

_threads: list[threading.Thread] = []


def on_startup() -> None:
    """Discover outbound MCP servers in the background: boot never waits on the network."""
    t = threading.Thread(target=client.refresh_all, name="mcp-discover", daemon=True)
    _threads.append(t)
    t.start()


def join(timeout: float = 5) -> None:
    """Wait for discovery passes before `db.close()`: closing a connection mid-query crashes sqlite."""
    while _threads:
        _threads.pop().join(timeout)
