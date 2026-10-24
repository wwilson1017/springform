"""Admin routes for outbound MCP servers, under /api/core/mcp/servers. The token is write-only:
responses carry `has_token`, never the token. Create, update and Refresh run discovery before
answering, so the response shows the tools (or `last_error`)."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.core import registry as app_registry
from backend.core.auth.deps import require_admin
from backend.core.errors import NotFound
from backend.core.mcp_servers import client, service, transport

router = APIRouter(prefix="/api/core/mcp/servers", tags=["core"], dependencies=[Depends(require_admin)])

_PREFIX = re.compile(r"^[a-z][a-z0-9_]{1,19}$")


def _url(v: str | None) -> str | None:
    if v is None:
        return v
    v, parts = v.strip(), urlsplit(v.strip())
    schemes = ("https", "http") if transport.allow_private() else ("https",)
    if parts.scheme not in schemes or not parts.hostname or parts.username is not None:
        raise ValueError("url must be an https:// address (http:// only with MCP_ALLOW_PRIVATE=1), without a login")
    return v


def _prefix(v: str | None) -> str | None:
    if v is None:
        return v
    if not _PREFIX.match(v):
        raise ValueError("prefix must be 2-20 of a-z, 0-9 and _, starting with a letter")
    if v in app_registry.RESERVED_SLUGS or v in {a.slug for a in app_registry.installed()}:
        raise ValueError("prefix must not be a reserved name or an installed app's slug")
    return v


class ServerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    url: str = Field(max_length=2000)
    token: str = Field(default="", max_length=8192)
    prefix: str

    _check_url = field_validator("url")(_url)
    _check_prefix = field_validator("prefix")(_prefix)


class ServerPatch(BaseModel):
    """Omitted (or null) fields stay as they are; `token: ""` removes the token."""

    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=80)
    url: str | None = Field(default=None, max_length=2000)
    token: str | None = Field(default=None, max_length=8192)
    prefix: str | None = None
    enabled: bool | None = None

    _check_url = field_validator("url")(_url)
    _check_prefix = field_validator("prefix")(_prefix)


def _row(server_id: int) -> dict:
    row = service.row(server_id)
    if row is None:
        raise NotFound("mcp_server_not_found")
    return row


@router.get("")
def mcp_servers_list() -> list[dict]:
    return [service.view(r) for r in service.rows()]


@router.post("")
def mcp_servers_create(body: ServerIn) -> dict:
    server_id = service.create(**{**body.model_dump(), "name": body.name.strip(), "token": body.token.strip()})
    client.refresh(server_id)
    return service.get(server_id)


@router.patch("/{server_id}")
def mcp_servers_update(server_id: int, body: ServerPatch) -> dict:
    fields = {k: v.strip() if isinstance(v, str) else v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if fields:
        service.update(server_id, **fields)
    client.refresh(_row(server_id)["id"])
    return service.get(server_id)


@router.delete("/{server_id}", status_code=204)
def mcp_servers_delete(server_id: int) -> Response:
    service.delete(server_id)
    client.refresh(server_id)  # drops its tools from the registry
    return Response(status_code=204)


@router.post("/{server_id}/refresh")
def mcp_servers_refresh(server_id: int) -> dict:
    client.refresh(_row(server_id)["id"])
    return service.get(server_id)


@router.post("/{server_id}/test")
def mcp_servers_test(server_id: int) -> dict:
    """{ok, tools: n, error?}: connect and list tools; changes nothing."""
    row = _row(server_id)
    return client.check(row["url"], service.token(row))
