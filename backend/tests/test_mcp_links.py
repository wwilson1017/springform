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
from mcp.types import CallToolResult, Implementation, TextContent
from starlette.responses import PlainTextResponse

from backend.core import db as core_db, ratelimit
from backend.core.agent import registry as tool_registry
from backend.core.agent.spec import ToolSpec
from backend.core.auth.deps import system_user
from backend.core.errors import Forbidden
from backend.core.mcp import clients, links, router as mcp_router, server, startup as mcp_startup
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
async def mcp_session(app, path: str, client_info: Implementation | None = None, modern: bool = False, **headers):
    """A real ClientSession. `modern` speaks protocol 2026-07-28 (server/discover, then clientInfo
    on every request) instead of the legacy initialize handshake."""
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://testserver", headers=headers) as http:
        async with streamable_http_client(f"http://testserver{path}", http_client=http) as (read, write):
            async with ClientSession(read, write, client_info=client_info) as session:
                await (session.discover() if modern else session.initialize())
                yield session


def list_tools(app, path: str, **headers) -> dict:
    async def go():
        async with mcp_session(app, path, **headers) as s:
            return {t.name: t for t in (await s.list_tools()).tools}

    return asyncio.run(go())


def call_tool(app, path: str, name: str, args: dict, **session):
    async def go():
        async with mcp_session(app, path, **session) as s:
            return await s.call_tool(name, args)

    return asyncio.run(go())


def result_json(result: CallToolResult):
    """A tool result's one text block, parsed."""
    block = result.content[0]
    assert isinstance(block, TextContent)
    return json.loads(block.text)


def tool_run(tool: str) -> dict | None:
    return core_db.one("SELECT * FROM core_agent_tool_runs WHERE tool = ? ORDER BY id DESC", (tool,))


def test_a_link_is_shown_once_and_only_its_owner_lists_or_revokes_it(login_as):
    a, b = login_as("member"), login_as("member")
    made = mint(a, "Claude Desktop")
    assert made["url"] == f"http://localhost:8000/mcp/{made['token']}" and len(made["token"]) == 43
    listed = a.get(LINKS)
    assert listed.json() == [
        {"id": made["id"], "label": "Claude Desktop", "created_at": made["created_at"], "last_used_at": None}
    ]
    assert made["token"] not in listed.text
    assert core_db.one("SELECT token_hash FROM core_agent_mcp_links")["token_hash"] != made["token"]
    assert a.post(LINKS, json={"label": "   "}).status_code == 422

    assert b.get(LINKS).json() == [] and b.delete(f"{LINKS}/{made['id']}").status_code == 404
    assert b.get(LINKS, params={"all": 1}).status_code == 403
    everyone = login_as("admin").get(LINKS, params={"all": 1})
    assert [(x["id"], x["user_id"], x["label"]) for x in everyone.json()] == [
        (made["id"], a.principal.id, "Claude Desktop")
    ]
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
    destructive = {"crm_merge_deals"}  # drops the source's clashing custom-field values
    assert destructive <= admin_tools.keys()
    for tool in admin_tools.values():  # explicit hints: a write would otherwise read as destructive, open-world
        assert tool.title and tool.annotations.title == tool.title, tool.name
        assert tool.annotations.destructive_hint is (tool.name in destructive), tool.name
        assert tool.annotations.open_world_hint is False, tool.name
    assert member_tools["todos_create"].title == "Add a todo"
    assert member_tools["example_list_widgets"].title == "List widgets"  # derived from the name
    assert member_tools["example_create_widget"].input_schema["required"] == ["name"]

    made = call_tool(app, at(m_link), "example_create_widget", {"name": "From Claude"})
    assert not made.is_error and result_json(made)["name"] == "From Claude"
    assert [(w["name"], w["owner_user_id"]) for w in core_db.rows("SELECT * FROM example_widgets")] == [
        ("From Claude", member.principal.id)
    ]
    run = tool_run("example_create_widget")
    assert (run["status"], run["source"], run["user_id"], run["conversation_id"]) == (
        "done",
        "mcp",
        member.principal.id,
        None,
    )

    read = call_tool(app, at(m_link), "example_list_widgets", {})
    assert [w["name"] for w in result_json(read)] == ["From Claude"]
    assert tool_run("example_list_widgets")["source"] == "mcp"
    refused = call_tool(app, at(m_link), "example_count_widgets", {})  # listed for admins only, so not callable
    assert refused.is_error and tool_run("example_count_widgets") is None
    assert member.get(LINKS).json()[0]["last_used_at"] is not None


def test_a_failing_external_effect_over_mcp_is_uncertain(app, login_as):
    def send(user, args):
        raise RuntimeError("the mail server hung up after DATA")

    before = tool_registry.current()
    tool_registry.set_current(
        tool_registry.build_registry(
            [
                *before.all(),
                ToolSpec(
                    name="core_send_note",
                    description="Send a note out.",
                    input_schema={"type": "object", "properties": {}},
                    writes=True,
                    external_effect=True,
                    handler=send,
                ),
            ]
        )
    )
    try:
        out = call_tool(app, at(mint(login_as("member"))), "core_send_note", {})
    finally:
        tool_registry.set_current(before)
    assert out.is_error and result_json(out)["status"] == "uncertain"
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
    assert (
        client.post("/mcp", headers={"Origin": "null", "Authorization": f"Bearer {link['token']}"}).status_code == 403
    )
    for path in (
        "/.well-known/oauth-authorization-server",
        "/.well-known/oauth-protected-resource/mcp",
        "/register",
        "/authorize",
        "/token",
    ):
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
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        '%s - "%s %s HTTP/%s" %d',
        ("10.0.0.1:5000", "POST", "/mcp/abcDEF123_-xyz?x=1", "1.1", 200),
        None,
    )
    ScrubLinkTokens().filter(record)
    assert record.getMessage() == '10.0.0.1:5000 - "POST /mcp/***?x=1 HTTP/1.1" 200'


def test_scrubbed_link_shapes():
    token = "a" * 43
    assert [
        mcp_startup.scrub(p)
        for p in (f"/link/{token}", f"/{token}/mcp", f"/{token}/mcp?x=1", "/settings/mcp", f"/mcp/{token}")
    ] == ["/link/***", "/***/mcp", "/***/mcp?x=1", "/settings/mcp", "/mcp/***"]


def test_instructions_carry_the_guidance_of_the_apps_the_user_reaches(app, login_as):
    async def instructions(path):
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as http:
            async with streamable_http_client(f"http://testserver{path}", http_client=http) as (read, write):
                async with ClientSession(read, write) as session:
                    return (await session.initialize()).instructions

    text = asyncio.run(instructions(at(mint(login_as("member"))))) or ""
    assert "You are the user's GTD (Getting Things Done) partner" in text
    assert "Example: Widgets are sample records" in text
    assert text.endswith(server.UNTRUSTED_NOTE)


def test_every_link_shape_serves_mcp_and_a_browser_gets_the_guide(app, client, login_as, monkeypatch):
    async def transport(scope, receive, send):  # stands in for the SDK, whose event stream stays open
        await PlainTextResponse("from the transport", 299)(scope, receive, send)

    member = login_as("member")
    link = mint(member)
    shapes = (f"/mcp/{link['token']}", f"/link/{link['token']}", f"/{link['token']}/mcp")
    for path in shapes:
        assert "todos_list" in list_tools(app, path), path
        page = client.get(path)
        assert page.status_code == 200 and "This is an MCP link" in page.text, path
        assert page.headers["content-type"].startswith("text/html")
        assert (page.headers["cache-control"], page.headers["referrer-policy"]) == ("no-store", "no-referrer")
        assert link["token"] not in page.text
        assert client.head(path).status_code == 200
        assert client.get(path, headers={"Origin": "https://example.com"}).status_code == 403
        # An MCP client's GET asks for the event stream: the transport answers it, not the guide.
        with monkeypatch.context() as m:
            m.setattr(server, "handle", transport)
            assert client.get(path, headers={"Accept": "text/event-stream"}).status_code == 299
    unknown = "b" * 43
    for path in (f"/link/{unknown}", f"/{unknown}/mcp", f"/mcp/{unknown}"):
        assert client.get(path).status_code == 404
    member.delete(f"{LINKS}/{link['id']}")
    assert [client.get(p).status_code for p in shapes] == [404, 404, 404]


def test_token_first_shape_does_not_capture_app_paths(db, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from backend import main

    (tmp_path / "index.html").write_text("<!doctype html><title>SPA</title>")
    monkeypatch.setattr(main, "FRONTEND_DIST", tmp_path)
    spa = TestClient(main.create_app())
    for path in ("/settings/mcp", "/link/inbox"):  # an app may be named `link`: only a token-shaped segment is ours
        page = spa.get(path)
        assert page.status_code == 200 and "<title>SPA</title>" in page.text, path


def run_client() -> str | None:
    return core_db.one("SELECT client FROM core_agent_tool_runs ORDER BY id DESC")["client"]


def test_a_tool_run_records_the_calling_client(app, login_as):
    path = at(mint(login_as("member")))
    call_tool(app, path, "todos_today", {}, **{"User-Agent": "openai-mcp/1.0.0"})
    assert run_client() == "ChatGPT"
    call_tool(app, path, "todos_today", {})  # the SDK's own client sends an HTTP library's User-Agent
    assert run_client() is None
    # Protocol 2026-07-28 carries the client's own clientInfo on every request; it beats the User-Agent.
    call_tool(
        app, path, "todos_today", {}, client_info=Implementation(name="claude-ai", version="1"), modern=True,
        **{"User-Agent": "openai-mcp/1.0.0"},
    )  # fmt: skip
    assert run_client() == "Claude"
    assert core_db.one("SELECT client FROM core_agent_tool_runs WHERE source = 'chat'") is None


def test_a_todo_made_over_a_link_says_which_ai_made_it(app, login_as):
    member = login_as("member")
    made = call_tool(
        app, at(mint(member)), "todos_create", {"title": "Call the bank"}, **{"User-Agent": "openai-mcp/1.0"}
    )
    todo = member.get(f"/api/todos/items/{result_json(made)['id']}").json()
    assert (todo["source"], todo["source_client"]) == ("agent", "ChatGPT")


@pytest.mark.parametrize(
    ("declared", "user_agent", "expected"),
    [
        ("Cursor", "node", "Cursor"),
        (None, "Claude-User/1.0 (+https://example.com)", "Claude"),
        (None, "claude-code/2.0.1", "Claude Code"),
        (None, "python-httpx/0.28", None),
        (None, "Mozilla/5.0", None),
        (None, None, None),
        ("  ", "openai-mcp/1.0.0", "ChatGPT"),
        ("Evil\nTool\x00 " + "x" * 100, None, "Evil Tool " + "x" * 50),
        (None, " " * 5000 + "!", None),
    ],
)
def test_client_name(declared, user_agent, expected):
    assert clients.client_name(declared, user_agent) == expected
