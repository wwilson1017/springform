"""Outbound MCP: discovery into the registry, every remote call confirms, fencing, the address
policy at connection time (incl. DNS rebinding), and the admin routes. A real MCP server (the
stub fixture) runs on loopback, so discovery and calls go through the SDK and the guarded
transport for real; MCP_ALLOW_PRIVATE=1 is what lets them reach it."""

import json
from dataclasses import replace

import anyio
import httpcore2
import pytest

from backend.core import db as core_db, scheduler
from backend.core.agent import history, registry
from backend.core.agent.providers import fake
from backend.core.agent.registry import ToolSpecError
from backend.core.agent.spec import tool_def_sha256
from backend.core.mcp_servers import client, service, transport
from backend.tests.fixtures import mcp_stub

TOKEN = "stub-token"
BASE = "/api/core/mcp/servers"


@pytest.fixture(scope="module")
def stub():
    return mcp_stub.serve(TOKEN)  # (url, calls)


@pytest.fixture(autouse=True)
def _registry_and_fake(monkeypatch):
    monkeypatch.setenv("AGENT_FAKE_PROVIDER", "1")
    monkeypatch.delenv("MCP_ALLOW_PRIVATE", raising=False)
    fake.reset()
    before = registry.current()
    yield
    registry.set_current(before)
    fake.reset()


@pytest.fixture
def allow_private(monkeypatch):
    monkeypatch.setenv("MCP_ALLOW_PRIVATE", "1")


@pytest.fixture
def admin(login_as):
    return login_as("admin")


def add(admin, url, prefix="stub", token=TOKEN, **extra) -> dict:
    r = admin.post(BASE, json={"name": "Stub todos", "url": url, "token": token, "prefix": prefix, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def remote_names() -> list[str]:
    return sorted(s.name for s in registry.current().all() if s.remote)


def events(response) -> list[dict]:
    assert response.status_code == 200, response.text
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


# ── Discovery and the registry ────────────────────────────────────────────────


def test_discovery_registers_prefixed_remote_tools(admin, stub, allow_private):
    url, _ = stub
    server = add(admin, url)
    assert server["last_error"] is None and server["last_discovered_at"] and server["has_token"]
    assert "token" not in server and "token_enc" not in server
    assert {t["name"]: t["read_only_hint"] for t in server["tools"]} == {"list_items": True, "add_item": False}

    assert remote_names() == ["stub__add_item", "stub__list_items"]
    listing, adding = registry.get("stub__list_items"), registry.get("stub__add_item")
    for spec in (listing, adding):
        assert (spec.always_confirm, spec.untrusted_source, spec.external_effect, spec.mcp_exposed) == (True, True, True, False)
        assert (spec.app, spec.server_id, spec.server_url) == ("stub", str(server["id"]), url)
    assert (listing.writes, adding.writes) == (False, True)  # from the annotation, display and budget only
    assert listing.description.startswith("stub.list_items, a remote tool on Stub todos:")
    assert adding.input_schema["required"] == ["title"]
    # Never offered inbound or to unattended jobs.
    assert not {s.name for s in registry.for_source("mcp")} & set(remote_names())
    assert not {s.name for s in registry.for_source("job")} & set(remote_names())
    assert admin.get(BASE).json() == [server]


def test_hash_covers_the_url_and_a_url_change_makes_a_pending_approval_stale(admin, stub, allow_private):
    url, calls = stub
    server = add(admin, url)
    before = tool_def_sha256(registry.get("stub__add_item"))
    assert tool_def_sha256(replace(registry.get("stub__add_item"), server_url=url + "?v=2")) != before

    fake.script({"tool": "stub__add_item", "args": {"title": "Sugar"}}, "Shall I add it?")
    confirm = [e for e in events(admin.post("/api/agent/chat", json={"message": "add sugar"})) if e["type"] == "confirm"][0]

    moved = admin.patch(f"{BASE}/{server['id']}", json={"url": url + "?v=2"}).json()
    assert moved["url"] == url + "?v=2" and moved["last_error"] is None
    assert tool_def_sha256(registry.get("stub__add_item")) != before
    seen = len(calls)
    r = admin.post("/api/agent/confirm", json={"tool_run_id": confirm["tool_run_id"], "decision": "approve"}).json()
    assert r == {"status": "stale"} and len(calls) == seen


def test_failing_discovery_drops_the_servers_tools_and_records_the_error(admin, stub, allow_private):
    url, _ = stub
    server = add(admin, url)
    assert remote_names() == ["stub__add_item", "stub__list_items"]
    broken = admin.patch(f"{BASE}/{server['id']}", json={"token": "wrong"}).json()
    assert broken["last_error"] == "The server refused the request (HTTP 401); check the token" and broken["tools"] == []
    assert broken["last_discovered_at"] == server["last_discovered_at"]  # the last success
    assert remote_names() == []
    assert admin.get("/api/agent/status").status_code == 200  # the app is fine


def test_disabling_removes_tools_and_enabling_brings_them_back(admin, stub, allow_private):
    url, _ = stub
    server = add(admin, url)
    off = admin.patch(f"{BASE}/{server['id']}", json={"enabled": False}).json()
    assert (off["enabled"], off["tools"], remote_names()) == (False, [], [])
    on = admin.patch(f"{BASE}/{server['id']}", json={"enabled": True}).json()
    assert len(on["tools"]) == 2 and remote_names() == ["stub__add_item", "stub__list_items"]


def test_refresh_all_skips_nothing_and_the_hourly_job_is_registered(admin, stub, allow_private):
    url, _ = stub
    add(admin, url)
    registry.swap_server(str(service.rows()[0]["id"]), [])
    client.refresh_all()
    assert remote_names() == ["stub__add_item", "stub__list_items"]
    job = scheduler.jobs()["core.mcp_discover"]
    assert (job.every, job.fn) == (3600, client.refresh_all)


# ── Every remote call confirms; results are fenced ────────────────────────────


def test_a_remote_read_still_confirms_and_its_result_is_fenced(admin, stub, allow_private):
    url, calls = stub
    add(admin, url)
    seen = len(calls)
    fake.script({"tool": "stub__list_items", "args": {}}, "I need your approval to read the list.")
    evs = events(admin.post("/api/agent/chat", json={"message": "what is on my list?"}))
    confirm = [e for e in evs if e["type"] == "confirm"][0]
    assert confirm["tool"] == "stub__list_items" and "remote tool" in confirm["description"]
    assert not [e for e in evs if e["type"] == "tool_end"] and len(calls) == seen  # nothing ran yet
    assert history.get_tool_run(confirm["tool_run_id"])["status"] == "pending"

    r = admin.post("/api/agent/confirm", json={"tool_run_id": confirm["tool_run_id"], "decision": "approve"}).json()
    assert r["status"] == "done" and mcp_stub.INJECTION in r["result"] and calls[-1] == ("list_items", {})
    stored = json.loads(history.get_tool_run(confirm["tool_run_id"])["result"])
    assert stored.startswith('<untrusted_external_content id="') and 'source="stub__list_items"' in stored
    assert mcp_stub.INJECTION in stored and stored.rstrip().endswith(">")
    assert history.compaction_state(evs[0]["id"])["tainted"] == 1


def test_a_remote_write_runs_once_with_the_stored_args(admin, stub, allow_private):
    url, calls = stub
    add(admin, url)
    fake.script({"tool": "stub__add_item", "args": {"title": "Butter"}}, "Approve to add it.")
    confirm = [e for e in events(admin.post("/api/agent/chat", json={"message": "add butter"})) if e["type"] == "confirm"][0]
    ok = admin.post("/api/agent/confirm", json={"tool_run_id": confirm["tool_run_id"], "decision": "approve"}).json()
    assert ok == {"status": "done", "result": "Added 'Butter'"} and calls[-1] == ("add_item", {"title": "Butter"})
    again = admin.post("/api/agent/confirm", json={"tool_run_id": confirm["tool_run_id"], "decision": "approve"}).json()
    assert again["status"] == "already_resolved" and [c for c in calls if c == ("add_item", {"title": "Butter"})] == [calls[-1]]


# ── Address policy ────────────────────────────────────────────────────────────


def test_private_and_loopback_destinations_are_refused(admin, monkeypatch):
    async def internal_dns(host, port):
        return ["10.1.2.3"]

    monkeypatch.setattr(transport, "resolve", internal_dns)
    server = add(admin, "https://todos.example.com/mcp", prefix="internal")
    assert "10.1.2.3 is a loopback, private or link-local address" in server["last_error"] and server["tools"] == []
    monkeypatch.undo()
    monkeypatch.delenv("MCP_ALLOW_PRIVATE", raising=False)
    for literal in ("https://127.0.0.1:9/mcp", "https://[::ffff:127.0.0.1]:9/mcp", "https://169.254.169.254/mcp"):
        result = client.check(literal, "")
        assert result["ok"] is False and "refuses it" in result["error"], (literal, result)
    assert remote_names() == []


def test_http_needs_allow_private_and_then_only_reaches_private_addresses(stub, monkeypatch):
    url, _ = stub
    assert client.check(url, TOKEN) == {"ok": False, "tools": 0, "error": "http:// is not allowed; MCP servers must use https"}
    monkeypatch.setenv("MCP_ALLOW_PRIVATE", "1")
    assert client.check(url, TOKEN) == {"ok": True, "tools": 2}
    with pytest.raises(transport.Refused, match="public; use https"):
        transport.check("93.184.215.14", plain=True, allow=True)
    transport.check("93.184.215.14", plain=False, allow=False)  # https to a public address is the normal case


class _Inner(httpcore2.AsyncNetworkBackend):
    """Records where it was asked to connect instead of connecting."""

    def __init__(self):
        self.connected: list[str] = []

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self.connected.append(host)
        return object()


def test_dns_rebinding_is_refused_at_connection_time(monkeypatch):
    answers = iter([["93.184.215.14"], ["10.0.0.5"]])  # public to the first lookup, private to the next

    async def rebinding(host, port):
        return next(answers)

    monkeypatch.setattr(transport, "resolve", rebinding)
    inner = _Inner()
    backend = transport.GuardedBackend(plain=False, allow=False, inner=inner)
    anyio.run(backend.connect_tcp, "todos.example.com", 443)
    with pytest.raises(transport.Refused, match="10.0.0.5"):
        anyio.run(backend.connect_tcp, "todos.example.com", 443)
    assert inner.connected == ["93.184.215.14"]  # connected to the checked IP, never the private one

    async def mixed(host, port):
        return ["93.184.215.14", "192.168.1.10"]

    monkeypatch.setattr(transport, "resolve", mixed)
    with pytest.raises(transport.Refused, match="192.168.1.10"):
        anyio.run(backend.connect_tcp, "todos.example.com", 443)
    assert inner.connected == ["93.184.215.14"]  # every address is checked before any connection


def test_responses_are_capped_and_never_sent_inside_a_transaction(db, stub, monkeypatch):
    class Big:
        async def __aiter__(self):
            for _ in range(5):
                yield b"x" * (transport.MAX_RESPONSE // 4)

    async def drain():
        return [c async for c in transport._Capped(Big())]

    with pytest.raises(transport.Refused, match="over 1024 KB"):
        anyio.run(drain)

    monkeypatch.setenv("MCP_ALLOW_PRIVATE", "1")
    with core_db.transaction():
        assert client.check(stub[0], TOKEN)["error"] == "network call inside transaction()"


# ── Registry swap ─────────────────────────────────────────────────────────────


def test_swap_server_replaces_one_servers_tools_atomically(admin, stub, allow_private):
    url, _ = stub
    server = add(admin, url)
    key, local = str(server["id"]), len([s for s in registry.current().all() if not s.remote])
    listing = registry.get("stub__list_items")
    with pytest.raises(ToolSpecError, match="always_confirm, untrusted_source and external_effect"):
        registry.swap_server(key, [replace(listing, always_confirm=False)])
    assert remote_names() == ["stub__add_item", "stub__list_items"]  # unchanged after a refused swap
    registry.swap_server("other", [replace(listing, name="other__list_items", app="other", server_id="other")])
    registry.swap_server(key, [listing])
    assert remote_names() == ["other__list_items", "stub__list_items"]
    registry.swap_server(key, [])
    assert remote_names() == ["other__list_items"] and len(registry.current().all()) == local + 1


# ── Routes ────────────────────────────────────────────────────────────────────


def test_routes_are_admin_only_and_validate(admin, login_as, stub, allow_private):
    url, _ = stub
    member = login_as("member")
    assert member.get(BASE).status_code == 403
    assert member.post(BASE, json={"name": "x", "url": url, "prefix": "stub"}).status_code == 403
    for body in (
        {"name": "x", "url": url, "prefix": "Stub"},
        {"name": "x", "url": url, "prefix": "s"},
        {"name": "x", "url": url, "prefix": "todos"},  # an installed app's slug
        {"name": "x", "url": url, "prefix": "core"},
        {"name": "x", "url": "ftp://example.com/mcp", "prefix": "stub"},
        {"name": "x", "url": "https://user:pw@example.com/mcp", "prefix": "stub"},
        {"name": "", "url": url, "prefix": "stub"},
    ):
        assert admin.post(BASE, json=body).status_code == 422, body
    server = add(admin, url)
    assert admin.post(BASE, json={"name": "x", "url": url, "prefix": "stub"}).status_code == 409
    assert admin.post(f"{BASE}/{server['id']}/test").json() == {"ok": True, "tools": 2}
    refreshed = admin.post(f"{BASE}/{server['id']}/refresh").json()
    assert len(refreshed["tools"]) == 2 and refreshed["last_discovered_at"]
    cleared = admin.patch(f"{BASE}/{server['id']}", json={"token": ""}).json()
    assert cleared["has_token"] is False and cleared["last_error"] == "The server refused the request (HTTP 401); check the token"
    assert admin.delete(f"{BASE}/{server['id']}").status_code == 204
    assert admin.get(BASE).json() == [] and remote_names() == []
    assert admin.post(f"{BASE}/{server['id']}/refresh").status_code == 404
    assert admin.patch(f"{BASE}/{server['id']}", json={"name": "y"}).status_code == 404


def test_http_url_needs_allow_private(admin, stub):
    assert admin.post(BASE, json={"name": "x", "url": stub[0], "prefix": "stub"}).status_code == 422
