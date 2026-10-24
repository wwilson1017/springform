from backend.core import scheduler
from backend.core.mcp_servers import client

# Hourly rediscovery of every outbound MCP server; servers run one after another, 30 s each at most.
JOBS = [scheduler.Job("core.mcp_discover", client.refresh_all, every=3600, timeout=900)]
