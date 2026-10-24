"""The MCP server an inbound link talks to (docs/agents/mcp.md §1).

The `mcp` SDK's low-level `Server` behind a stateless, JSON-response streamable HTTP transport.
The router resolves the link and sets `link_user` before handing the request here, so every
handler acts as the link's user:
- tools offered are `for_user(user)` ∩ `for_source("mcp")`: never protected context-file writes or
  remote tools, and role-filtered (an app's roles and each tool's `enabled`);
- a call runs at once, as that user, through `agent.execute.run_tool(source="mcp")`, which
  authorizes its targets and records a `core_agent_tool_runs` row. The MCP client's own approval
  prompt is the user's gate. No model is involved, so this works with zero AI keys.
"""

from __future__ import annotations

import asyncio
import contextvars
import json

import mcp_types as types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.types import Receive, Scope, Send

from backend.core import VERSION
from backend.core.agent import execute, registry as tool_registry
from backend.core.agent.spec import ToolSpec
from backend.core.auth.deps import User

MAX_BODY_BYTES = 4 * 1024 * 1024
link_user: contextvars.ContextVar[User] = contextvars.ContextVar("mcp_link_user")


def tools_for(user: User) -> list[ToolSpec]:
    reg = tool_registry.current()
    allowed = {s.name for s in reg.for_source("mcp")}
    return [s for s in reg.for_user(user) if s.name in allowed]


async def _list_tools(ctx, params) -> types.ListToolsResult:
    return types.ListToolsResult(tools=[
        types.Tool(
            name=s.name, description=s.description, input_schema=s.input_schema,
            annotations=types.ToolAnnotations(read_only_hint=not s.writes),
        )
        for s in tools_for(link_user.get())
    ])


def _text(text: str, is_error: bool = False) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)], is_error=is_error)


async def _call_tool(ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
    user = link_user.get()
    spec = next((s for s in tools_for(user) if s.name == params.name), None)
    if spec is None:
        return _text(f"Unknown tool {params.name!r}.", is_error=True)
    run = await asyncio.to_thread(execute.run_tool, user, spec, dict(params.arguments or {}), source="mcp")
    if run["status"] != "done":
        return _text(json.dumps({"status": run["status"], "error": run["error"]}), is_error=True)
    return _text(run["stored"])


_server = Server(
    "Springform", version=VERSION,
    instructions="This install's records and tools. Every call acts as the person who made this link.",
    on_list_tools=_list_tools, on_call_tool=_call_tool,
)


async def handle(scope: Scope, receive: Receive, send: Send) -> None:
    """Serve one MCP HTTP request; `link_user` must already be set."""
    # simplification: a fresh stateless manager per request, so nothing has to start it from the app
    # lifespan; one long-lived manager run from a router lifespan if per-request setup ever shows in profiles
    manager = StreamableHTTPSessionManager(
        _server, json_response=True, stateless=True, max_request_body_size=MAX_BODY_BYTES,
    )
    async with manager.run():
        await manager.handle_request(scope, receive, send)
