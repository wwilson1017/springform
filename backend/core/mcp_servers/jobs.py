from backend.core import scheduler
from backend.core.mcp_servers import client

# Discovery of every outbound MCP server at every boot (the registry of remote tools lives in memory) and
# hourly; servers run one after another, 30 s each at most.
JOBS = [scheduler.Job("core.mcp_discover", client.refresh_all, every=3600, timeout=900, on_boot=True)]
