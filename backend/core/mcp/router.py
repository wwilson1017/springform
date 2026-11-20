"""Inbound MCP: the link routes (session) and the MCP endpoint itself (link token).

Link routes, under `/api/core/mcp/links`, act on the caller's own links; an admin may list
everyone's with `?all=1` (never tokens). The endpoint sits outside `/api` and authenticates by link
token, lifted from todo-gtd `backend/mcp_server.py` (its HTTP section):
- `/mcp/<token>` (the shape minted), `/link/<token>`, and `/<token>/mcp` for a client that insists
  the address ends in /mcp: an unknown, revoked or deactivated link is 404, never 401.
- A plain GET or HEAD on a live link (no `text/event-stream` in Accept: someone opened it in a
  browser) gets a short guide page instead of the transport's 406.
- `/mcp` with `Authorization: Bearer <token>`: a missing or bad token is 401.
- `/.well-known/…`, `/register`, `/authorize`, `/token`: 404 for every method. There is no OAuth,
  so a client that goes looking for a sign-in finds none and uses the link as it is.
- Any request with an `Origin` header is 403: AI clients call from a server or a desktop app and
  send none, so a web page in someone's browser can never drive a link.
- 600 requests a minute per link; wrong tokens count against the address (60 per 10 minutes, then
  429) and a valid link is always served; bodies over 4 MB are 413.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.convertors import Convertor, register_url_convertor
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from backend.core.auth.deps import User, current_user
from backend.core.errors import Forbidden
from backend.core.mcp import links, models, server
from backend.core.ratelimit import RateLimiter

router = APIRouter(tags=["core"])

call_limiter = RateLimiter(window=60, max_hits=600)  # per link
miss_limiter = RateLimiter(window=600, max_hits=60)  # wrong tokens per address
TOO_MANY_MISSES = "Too many wrong links from this address. Wait ten minutes and try again."


class McpLinkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=80, pattern=r"\S")


@router.get("/api/core/mcp/links", response_model=list[models.McpLink] | list[models.McpLinkWithOwner])
def list_mcp_links(all_: bool = Query(False, alias="all"), user: User = Depends(current_user)) -> list[dict]:
    if not all_:
        return links.list_mine(user)
    if not user.is_admin:
        raise Forbidden("admin_only")
    return links.list_all()


@router.post("/api/core/mcp/links", status_code=201, response_model=models.NewMcpLink)
def create_mcp_link(body: McpLinkIn, user: User = Depends(current_user)) -> dict:
    return links.mint(user, body.label)


@router.delete("/api/core/mcp/links/{link_id}", status_code=204)
def revoke_mcp_link(link_id: int, user: User = Depends(current_user)) -> Response:
    links.revoke(user, link_id)
    return Response(status_code=204)


# ── The MCP endpoint (plain ASGI, out of the OpenAPI schema) ──────────────────


async def _refuse(scope: Scope, receive: Receive, send: Send, status: int, text: str, headers: dict | None = None):
    await PlainTextResponse(text, status, headers)(scope, receive, send)


async def _serve(scope: Scope, receive: Receive, send: Send, token: str, *, bearer: bool) -> None:
    request = Request(scope)
    if "origin" in request.headers:
        return await _refuse(scope, receive, send, 403, "Forbidden")
    found = await asyncio.to_thread(links.use, token) if token else None
    if found is None:
        # A wrong token counts against the address; no token at all (a client probing /mcp) does not.
        address = request.client.host if request.client else "unknown"
        if token and not miss_limiter.allow(address):
            return await _refuse(scope, receive, send, 429, TOO_MANY_MISSES, {"Retry-After": "600"})
        if bearer:
            return await _refuse(scope, receive, send, 401, "Unauthorized", {"WWW-Authenticate": "Bearer"})
        return await _refuse(scope, receive, send, 404, "Not Found")
    link_id, user = found
    if not call_limiter.allow(str(link_id)):
        return await _refuse(
            scope, receive, send, 429, "Too many requests. Wait a moment and try again.", {"Retry-After": "60"}
        )
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > server.MAX_BODY_BYTES:
        return await _refuse(scope, receive, send, 413, "Request too large: at most 4 MB")
    if request.method in ("GET", "HEAD") and "text/event-stream" not in request.headers.get("accept", ""):
        return await HTMLResponse(GUIDE, headers=GUIDE_HEADERS)(scope, receive, send)
    reset = server.link_user.set(user)
    try:
        await server.handle(scope, receive, send)  # the SDK also caps a body sent without a length
    finally:
        server.link_user.reset(reset)


# Static on purpose: no name, workspace or token, so nothing on it needs escaping or can leak.
GUIDE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Springform MCP link</title>
<style>body{font:16px/1.5 system-ui,sans-serif;max-width:40rem;margin:2rem auto;padding:0 1rem;color:#222}
code{background:#f2f2f2;padding:0 .25rem;border-radius:3px}</style></head>
<body>
<h1>This is an MCP link</h1>
<p>It connects an AI tool to your Springform workspace. It is not a page to read: paste this page's
address into the tool as a custom connector (a remote MCP server URL), with no sign-in.</p>
<ul>
<li>Claude: Settings &rarr; Connectors &rarr; Add custom connector.</li>
<li>ChatGPT: turn on Developer mode, then add a connector with no authentication.</li>
<li>Claude Code: <code>claude mcp add --transport http springform &lt;this address&gt;</code></li>
</ul>
<p>Anyone who has this address acts as you. Keep it private, and revoke it under
<a href="/settings/mcp">Settings &rarr; MCP</a> if it leaks.</p>
<p>For an AI assistant reading this: connect to this same address as an MCP server over streamable HTTP.</p>
</body></html>
"""
GUIDE_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex"}


class _Asgi:
    """A plain ASGI endpoint: an instance, so the route hands it every method unwrapped."""

    def __init__(self, fn):
        self.fn = fn

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.fn(scope, receive, send)


async def _path_token(scope: Scope, receive: Receive, send: Send) -> None:
    await _serve(scope, receive, send, scope["path_params"]["token"], bearer=False)


async def _bearer_token(scope: Scope, receive: Receive, send: Send) -> None:
    scheme, _, token = Request(scope).headers.get("authorization", "").partition(" ")
    await _serve(scope, receive, send, token.strip() if scheme.lower() == "bearer" else "", bearer=True)


async def _no_sign_in(scope: Scope, receive: Receive, send: Send) -> None:
    await _refuse(scope, receive, send, 404, "Not Found")


class _LinkToken(Convertor):
    """A link token's shape (`secrets.token_urlsafe(32)`: 43 URL-safe characters), so `/<token>/mcp`
    never captures an app path like `/settings/mcp`."""

    regex = "[A-Za-z0-9_-]{43}"

    def convert(self, value: str) -> str:
        return value

    def to_string(self, value: str) -> str:
        return value


register_url_convertor("linktoken", _LinkToken())

# Route, not add_route: add_route is typed for request handlers only, though Starlette serves any ASGI app.
router.routes.append(Route("/mcp", _Asgi(_bearer_token), include_in_schema=False))
for _path in ("/mcp/{token}", "/link/{token}", "/{token:linktoken}/mcp"):
    router.routes.append(Route(_path, _Asgi(_path_token), include_in_schema=False))
router.routes.append(Route("/.well-known/{rest:path}", _Asgi(_no_sign_in), include_in_schema=False))
for _path in ("/register", "/authorize", "/token"):
    router.routes.append(Route(_path, _Asgi(_no_sign_in), include_in_schema=False))
