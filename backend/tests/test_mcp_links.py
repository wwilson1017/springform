"""Inbound MCP links: minting, listing and revoking, and the /mcp endpoint end to end through the
SDK's own ClientSession over an in-process ASGI transport (no network, no AI keys)."""

import asyncio
import json
import logging
from contextlib import asynccontextmanager

import httpx2
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from backend.core import db as core_db, ratelimit
from backend.core.agent import registry as tool_registry
from backend.core.agent.spec import ToolSpec
from backend.core.auth.deps import system_user
from backend.core.errors import Forbidden
from backend.core.mcp import links, router as mcp_router
from backend.core.mcp.startup import ScrubLinkTokens

LINKS = "/api/core/mcp/links"


@pytest.fixture(autouse=True)
def _fresh_limits():
    ratelimit.clear_all()
    yield
    ratelimit.clear_all()


def mint(client, label="Claude") -> dict:
    r = client.post(LINKS, json={"label": label})
    assert r.status_code == 201, r.text
    return r.json()


def at(link: dict) -> str:
    return f"/mcp/{link['token']}"


@asynccontextmanager
async def mcp_session(app, path: str, **headers):
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://testserver", headers=headers) as http:
        async with streamable_http_client(f"http://testserver{path}", http_client=http) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session


def list_tools(app, path: str, **headers) -> dict:
    async def go():
        async with mcp_session(app, path, **headers) as s:
            return {t.name: t for t in (await s.list_tools()).tools}

    return asyncio.run(go())


def call_tool(app, path: str, name: str, args: dict):
    async def go():
        async with mcp_session(app, path) as s:
            return await s.call_tool(name, args)

    return asyncio.run(go())


def tool_run(tool: str) -> dict:
    return core_db.one("SELECT * FROM core_agent_tool_runs WHERE tool = ? ORDER BY id DESC", (tool,))


def test_a_link_is_shown_once_and_only_its_owner_lists_or_revokes_it(login_as):
    a, b = login_as("member"), login_as("member")
    made = mint(a, "Claude Desktop")
    assert made["url"] == f"http://localhost:8000/mcp/{made['token']}" and len(made["token"]) == 43
    listed = a.get(LINKS)
    assert listed.json() == [{"id": made["id"], "label": "Claude Desktop", "created_at": made["created_at"], "last_used_at": None}]
    assert made["token"] not in listed.text
    assert core_db.one("SELECT token_hash FROM core_agent_mcp_links")["token_hash"] != made["token"]
    assert a.post(LINKS, json={"label": "   "}).status_code == 422

    assert b.get(LINKS).json() == [] and b.delete(f"{LINKS}/{made['id']}").status_code == 404
    assert b.get(LINKS, params={"all": 1}).status_code == 403
    everyone = login_as("admin").get(LINKS, params={"all": 1})
    assert [(x["id"], x["user_id"], x["label"]) for x in everyone.json()] == [(made["id"], a.principal.id, "Claude Desktop")]
    assert made["token"] not in everyone.text

    assert a.delete(f"{LINKS}/{made['id']}").status_code == 204
    assert a.get(LINKS).json() == [] and a.delete(f"{LINKS}/{made['id']}").status_code == 404


def test_minting_is_refused_for_the_system_principal_and_inactive_users(db, make_user):
    with pytest.raises(Forbidden):
        links.mint(system_user(), "jobs")
    user = make_user("member")
    with core_db.transaction() as conn:
        conn.execute("UPDATE core_users SET is_active = 0 WHERE id = ?", (user.id,))
    with pytest.raises(Forbidden):
        links.mint(user, "stale session object")  # the live row decides, not the User in hand
    assert core_db.rows("SELECT * FROM core_agent_mcp_links") == []


def test_tools_are_role_filtered_and_a_write_runs_at_once_as_the_link_user(app, login_as):
    member, admin = login_as("member"), login_as("admin")
    m_link = mint(member)
    member_tools, admin_tools = list_tools(app, at(m_link)), list_tools(app, at(mint(admin)))
    assert {"example_list_widgets", "example_create_widget"} <= member_tools.keys()
    assert "example_count_widgets" not in member_tools and "example_count_widgets" in admin_tools
    assert "core_context_file_write" not in admin_tools  # protected: never over MCP, even for an admin
    assert member_tools["example_list_widgets"].annotations.read_only_hint is True
    assert member_tools["example_create_widget"].annotations.read_only_hint is False
    assert member_tools["example_create_widget"].input_schema["required"] == ["name"]

    made = call_tool(app, at(m_link), "example_create_widget", {"name": "From Claude"})
    assert not made.is_error and json.loads(made.content[0].text)["name"] == "From Claude"
    assert [(w["name"], w["owner_user_id"]) for w in core_db.rows("SELECT * FROM example_widgets")] == [("From Claude", member.principal.id)]
    run = tool_run("example_create_widget")
    assert (run["status"], run["source"], run["user_id"], run["conversation_id"]) == ("done", "mcp", member.principal.id, None)

    read = call_tool(app, at(m_link), "example_list_widgets", {})
    assert [w["name"] for w in json.loads(read.content[0].text)] == ["From Claude"]
    assert tool_run("example_list_widgets")["source"] == "mcp"
    refused = call_tool(app, at(m_link), "example_count_widgets", {})  # listed for admins only, so not callable
    assert refused.is_error and tool_run("example_count_widgets") is None
    assert member.get(LINKS).json()[0]["last_used_at"] is not None


def test_a_failing_external_effect_over_mcp_is_uncertain(app, login_as):
    def send(user, args):
        raise RuntimeError("the mail server hung up after DATA")

    before = tool_registry.current()
    tool_registry.set_current(tool_registry.build_registry([*before.all(), ToolSpec(
        name="core_send_note", description="Send a note out.", input_schema={"type": "object", "properties": {}},
        writes=True, external_effect=True, handler=send,
    )]))
    try:
        out = call_tool(app, at(mint(login_as("member"))), "core_send_note", {})
    finally:
        tool_registry.set_current(before)
    assert out.is_error and json.loads(out.content[0].text)["status"] == "uncertain"
    run = tool_run("core_send_note")
    assert (run["status"], run["source"]) == ("uncertain", "mcp") and "hung up" in run["error"]


def test_the_bearer_form_works_and_answers_401_without_a_good_token(app, client, login_as):
    link = mint(login_as("member"))
    for headers in ({}, {"Authorization": "Bearer nope"}, {"Authorization": f"Basic {link['token']}"}):
        r = client.post("/mcp", headers=headers)
        assert (r.status_code, r.headers["www-authenticate"]) == (401, "Bearer")
    assert "example_list_widgets" in list_tools(app, "/mcp", Authorization=f"Bearer {link['token']}")


def test_revoked_and_deactivated_links_are_404_never_401(client, login_as):
    admin, member = login_as("admin"), login_as("member")
    revoked, kept = mint(member), mint(member)
    member.delete(f"{LINKS}/{revoked['id']}")
    assert client.post(at(revoked)).status_code == 404
    assert client.post(at(kept)).status_code != 404  # still live: the SDK answers this empty body

    assert admin.post(f"/api/auth/users/{member.principal.id}/deactivate").status_code == 200
    assert client.post(at(kept)).status_code == 404 and client.post(at({"token": "x" * 43})).status_code == 404
    assert core_db.one("SELECT revoked_at FROM core_agent_mcp_links WHERE id = ?", (kept["id"],))["revoked_at"]
    admin.post(f"/api/auth/users/{member.principal.id}/reactivate")
    assert client.post(at(kept)).status_code == 404  # reactivation does not bring a link back


def test_origin_is_refused_and_there_is_no_oauth_to_discover(client, login_as):
    link = mint(login_as("member"))
    assert client.post(at(link), headers={"Origin": "https://example.com"}).status_code == 403
    assert client.post("/mcp", headers={"Origin": "null", "Authorization": f"Bearer {link['token']}"}).status_code == 403
    for path in ("/.well-known/oauth-authorization-server", "/.well-known/oauth-protected-resource/mcp",
                 "/register", "/authorize", "/token"):
        assert client.get(path).status_code == 404 and client.post(path).status_code == 404


def test_rate_limits_and_the_body_cap(client, login_as, monkeypatch):
    link = mint(login_as("member"))
    monkeypatch.setattr(mcp_router, "call_limiter", ratelimit.RateLimiter(window=60, max_hits=2))
    assert [client.post(at(link)).status_code == 429 for _ in range(3)] == [False, False, True]
    assert client.post(at(link)).headers["retry-after"] == "60"

    monkeypatch.setattr(mcp_router, "miss_limiter", ratelimit.RateLimiter(window=600, max_hits=2))
    assert [client.post(f"/mcp/wrong{i}").status_code for i in range(3)] == [404, 404, 429]
    assert client.post("/mcp").status_code == 401  # no token at all is not a guess
    ratelimit.clear_all()
    assert client.post(at(link), content=b"x" * (4 * 1024 * 1024 + 1)).status_code == 413


def stamp() -> str | None:
    return core_db.one("SELECT last_used_at FROM core_agent_mcp_links")["last_used_at"]


def test_last_used_is_stamped_at_most_once_a_minute(db, make_user, freeze):
    freeze("2026-11-02T09:00:00Z")
    made = links.mint(make_user("member"), "Claude Code")
    links.use(made["token"])
    freeze("2026-11-02T09:00:59Z")
    links.use(made["token"])
    assert stamp() == "2026-11-02T09:00:00Z"
    freeze("2026-11-02T09:01:00Z")
    assert links.use(made["token"])[1].email.startswith("member") and stamp() == "2026-11-02T09:01:00Z"


def test_access_log_lines_hide_the_link_token():
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                               ("10.0.0.1:5000", "POST", "/mcp/abcDEF123_-xyz?x=1", "1.1", 200), None)
    ScrubLinkTokens().filter(record)
    assert record.getMessage() == '10.0.0.1:5000 - "POST /mcp/***?x=1 HTTP/1.1" 200'
