"""Whisk's outbound MCP client (docs/agents/mcp.md §2): discover a server's tools, put them in the
registry as remote ToolSpecs, and call them.

- Transport: the `mcp` SDK's streamable HTTP client and `ClientSession`, over `transport.http_client`
  (address policy at connection time, no redirects, 30 s, 1 MB). One short session per exchange.
- Discovery runs at startup (startup.py, in a thread), on Refresh, and hourly (core.mcp_discover).
  Each server's tools are swapped into the registry atomically; a failing server drops its tools
  and records last_error, never more.
- A remote tool's wire name is `<prefix>__<tool>` (providers forbid `.`), shown as `<prefix>.<tool>`.
  Remote annotations are untrusted metadata: `readOnlyHint` sets `writes` and is shown, but every
  remote call confirms (always_confirm), its result is fenced by the engine (untrusted_source), it
  runs outside any transaction (external_effect), and it is never exposed inbound or to jobs.
  tool_def_sha256 covers the server id and URL, so a URL change makes a pending approval stale.
"""

from __future__ import annotations

import logging
import re
import threading
from contextlib import asynccontextmanager

import anyio
import mcp_types as types
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from backend.core.agent import registry
from backend.core.agent.spec import ToolSpec
from backend.core.mcp_servers import service, transport

logger = logging.getLogger(__name__)

MAX_TOOLS = 200
MAX_DESCRIPTION = 1000
_WIRE_NAME = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_refresh_lock = threading.Lock()  # one discovery at a time, so an older answer never lands last


class RemoteError(Exception):
    pass


# ── One MCP exchange ──────────────────────────────────────────────────────────


def _run(exchange, *args):
    """Run an async exchange to completion from sync code (a worker thread), bounded by the
    timeout, raising its first real error instead of anyio's exception group."""

    async def bounded():
        with anyio.fail_after(transport.TIMEOUT):
            return await exchange(*args)

    try:
        return anyio.run(bounded)
    except BaseExceptionGroup as group:
        error: BaseException = group
        while isinstance(error, BaseExceptionGroup):
            error = error.exceptions[0]
        raise error from None


def describe(e: BaseException) -> str:
    if isinstance(e, TimeoutError):
        return f"Timed out after {transport.TIMEOUT:g} s"
    return (str(e) or type(e).__name__)[:500]


@asynccontextmanager
async def _session(url: str, token: str):
    async with transport.http_client(token) as http, streamable_http_client(url, http_client=http) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def _list(url: str, token: str) -> list[types.Tool]:
    tools: list[types.Tool] = []
    async with _session(url, token) as session:
        cursor = None
        while True:
            page = await session.list_tools(params=types.PaginatedRequestParams(cursor=cursor) if cursor else None)
            tools += page.tools
            cursor = page.next_cursor
            if not cursor or len(tools) >= MAX_TOOLS:
                return tools[:MAX_TOOLS]


async def _call(url: str, token: str, tool: str, args: dict) -> types.CallToolResult:
    async with _session(url, token) as session:
        return await session.call_tool(tool, args)


def list_tools(url: str, token: str) -> list[types.Tool]:
    return _run(_list, url, token)


def call_tool(url: str, token: str, tool: str, args: dict):
    """The remote result as the model will see it (the engine fences it): the text blocks, or the
    structured content when there is no text; `{"error": ...}` when the server flags an error."""
    result = _run(_call, url, token, tool, args)
    texts = [b.text for b in result.content if isinstance(b, types.TextContent)]
    if skipped := len(result.content) - len(texts):
        texts.append(f"[{skipped} non-text content block(s) omitted]")
    payload = "\n".join(texts) if texts or result.structured_content is None else result.structured_content
    return {"error": payload} if result.is_error else payload


# ── Remote specs and refresh ──────────────────────────────────────────────────


def _handler(server_id: int, url: str, tool: str):
    def handler(user, args: dict):
        row = service.row(server_id)
        if row is None or not row["enabled"] or row["url"] != url:
            raise RemoteError("This MCP server was changed or removed since the tool was offered.")
        return call_tool(url, service.token(row), tool, args)

    return handler


def _specs(row: dict, tools: list[types.Tool]) -> tuple[list[ToolSpec], list[dict]]:
    """(ToolSpecs, the display list). A tool whose wire name or schema providers would reject is
    skipped (logged)."""
    specs, shown = [], []
    for tool in tools:
        wire = f"{row['prefix']}__{tool.name}"
        if not _WIRE_NAME.match(wire) or tool.input_schema.get("type") != "object":
            logger.warning("MCP server %s: skipped tool %r (name or schema unusable)", row["id"], tool.name[:80])
            continue
        hint = tool.annotations.read_only_hint if tool.annotations else None
        description = (tool.description or "").strip()[:MAX_DESCRIPTION]
        specs.append(ToolSpec(
            name=wire,
            description=f"{row['prefix']}.{tool.name}, a remote tool on {row['name']}: {description}",
            input_schema=tool.input_schema,
            writes=hint is not True,
            handler=_handler(row["id"], row["url"], tool.name),
            always_confirm=True,
            untrusted_source=True,
            external_effect=True,
            mcp_exposed=False,
            app=row["prefix"],
            server_id=str(row["id"]),
            server_url=row["url"],
        ))
        shown.append({"name": tool.name, "description": description, "read_only_hint": hint is True})
    return specs, shown


def refresh(server_id: int) -> None:
    """Discover one server and swap its tools into the registry (a disabled or deleted server's
    tools are dropped). A failure drops the tools and records last_error; it never raises."""
    with _refresh_lock:
        row = service.row(server_id)
        if row is None:
            registry.swap_server(str(server_id), [])
            return
        try:
            specs, shown = _specs(row, list_tools(row["url"], service.token(row))) if row["enabled"] else ([], [])
            registry.swap_server(str(server_id), specs)
            error = None
        except Exception as e:
            logger.warning("MCP server %s discovery failed: %s", server_id, describe(e))
            registry.swap_server(str(server_id), [])
            shown, error = [], describe(e)
        service.record_discovery(server_id, shown, error, discovered=bool(row["enabled"]) and error is None)


def refresh_all(cancel: threading.Event | None = None) -> None:
    """Job core.mcp_discover (hourly) and the startup pass."""
    for row in service.rows():
        if cancel is not None and cancel.is_set():
            return
        refresh(row["id"])


def check(url: str, token: str) -> dict:
    """Connect and list tools without touching the registry or the table."""
    try:
        return {"ok": True, "tools": len(list_tools(url, token))}
    except Exception as e:
        return {"ok": False, "tools": 0, "error": describe(e)}
