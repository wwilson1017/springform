"""Settings, GTD suite: the device connect against a stub suite (`fixtures/gtd_stub.py`, on loopback
with MCP_ALLOW_PRIVATE=1), the trusted server it stores (reads run without a card and taint, writes
ask), the launcher tiles, and disconnect. Never the real suite."""

import json
import time

import pytest

from backend.core import db as core_db
from backend.core.agent import history, registry
from backend.core.agent.providers import fake
from backend.core.gtd import service as gtd
from backend.core.mcp_servers import service as mcp_service
from backend.tests.fixtures import gtd_stub, mcp_stub

BASE = "/api/core/gtd"


@pytest.fixture(scope="module")
def suite():
    with gtd_stub.serve() as served:  # (base, state, calls)
        yield served


@pytest.fixture(autouse=True)
def _clean(monkeypatch, suite):
    monkeypatch.setenv("AGENT_FAKE_PROVIDER", "1")
    monkeypatch.setenv("MCP_ALLOW_PRIVATE", "1")
    _, state, _ = suite
    state.__dict__.update(vars(gtd_stub.fresh_state()))
    gtd._pending = None
    fake.reset()
    before = registry.current()
    yield
    registry.set_current(before)
    gtd._pending = None
    fake.reset()


@pytest.fixture
def admin(login_as, suite):
    client = login_as("admin")
    r = client.put("/api/core/settings", json={"values": {"gtd.base_url": suite[0]}})
    assert r.status_code == 200, r.text
    return client


def poll(admin):
    """One poll, as if the suite's interval had passed."""
    if gtd._pending is not None:
        gtd._pending["next_poll"] = 0
    return admin.post(f"{BASE}/connect/poll")


def connect(admin, suite) -> dict:
    _, state, _ = suite
    assert admin.post(f"{BASE}/connect").status_code == 200
    state.approved = True
    r = poll(admin)
    assert r.status_code == 200, r.text
    return r.json()


def events(response) -> list[dict]:
    assert response.status_code == 200, response.text
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def tiles(client) -> list[str]:
    return [t["title"] for t in client.get("/api/core/launcher/links").json()]


def test_connect_stores_a_trusted_server_and_the_tiles(admin, login_as, suite):
    base, state, _ = suite
    assert admin.get(BASE).json() == {"base_url": base, "server": None, "pending": None}

    started = admin.post(f"{BASE}/connect")
    assert started.status_code == 200 and gtd_stub.DEVICE not in started.text  # the device token stays here
    pending = started.json()["pending"]
    assert pending["user_code"] == gtd_stub.CODE and pending["url"].startswith("https://suite.example.test/")
    assert admin.post(f"{BASE}/connect").json()["pending"] == pending and state.connects == 1  # no second code

    assert poll(admin).json()["server"] is None  # still waiting
    state.approved = True
    done = poll(admin).json()
    server = done["server"]
    assert done["pending"] is None and server["prefix"] == "gtd" and server["name"] == "GTD suite"
    assert server["trusted"] is True and server["url"] == f"{base}/link/{gtd_stub.LINK}"
    assert {t["name"] for t in server["tools"]} == {"list_items", "add_item"}

    read, write = registry.get("gtd__list_items"), registry.get("gtd__add_item")
    assert read and write
    assert (read.always_confirm, read.trusted, read.untrusted_source, read.external_effect) == (False, True, True, True)
    assert (write.always_confirm, write.trusted) == (True, True)

    member = login_as("member")
    assert tiles(member) == ["Todo", "Notes", "Projects", "Sites", "Brain"]  # `mail` is not one of them
    assert member.get("/api/core/launcher/links").json()[0]["url"] == "https://todo.example.test"
    assert admin.post(f"{BASE}/connect").status_code == 409  # gtd_already_connected


def test_a_gtd_read_runs_without_a_card_and_taints_and_a_write_asks(admin, login_as, suite):
    _, _, calls = suite
    connect(admin, suite)
    member = login_as("member")
    fake.script(
        {"tool": "gtd__list_items", "args": {}},
        {"tool": "gtd__list_items", "args": {}},  # again, now in a tainted conversation
        {"tool": "gtd__add_item", "args": {"title": "Milk"}},
        "Adding milk needs your approval.",
    )
    seen = len(calls)
    evs = events(member.post("/api/agent/chat", json={"message": "what is on my list? add milk"}))
    reads = [e for e in evs if e["type"] == "tool_end" and e["tool"] == "gtd__list_items"]
    assert [e["status"] for e in reads] == ["done", "done"], [
        history.get_tool_run(e["tool_run_id"])["error"] for e in reads
    ]
    assert [e["tool"] for e in evs if e["type"] == "confirm"] == ["gtd__add_item"]
    assert calls[seen:] == [("list_items", {}), ("list_items", {})]  # the write has not reached the suite
    stored = history.get_tool_run(reads[0]["tool_run_id"])["result"]
    assert json.loads(stored).startswith('<untrusted_external_content id="') and mcp_stub.INJECTION in stored
    assert history.compaction_state(evs[0]["id"])["tainted"] == 1

    confirm = next(e for e in evs if e["type"] == "confirm")
    r = member.post("/api/agent/confirm", json={"tool_run_id": confirm["tool_run_id"], "decision": "approve"})
    assert r.json()["status"] == "done" and calls[-1] == ("add_item", {"title": "Milk"})


def test_disconnect_removes_the_server_the_tiles_and_the_tools(admin, suite):
    connect(admin, suite)
    gone = admin.delete(BASE)
    assert gone.status_code == 200 and gone.json()["server"] is None
    assert not [s for s in registry.current().all() if s.name.startswith("gtd__")]
    assert core_db.rows("SELECT * FROM core_launcher_links") == []
    assert core_db.rows("SELECT * FROM core_agent_mcp_servers") == []

    server = connect(admin, suite)["server"]  # removing it in the MCP servers card does the same
    assert admin.delete(f"/api/core/mcp/servers/{server['id']}").status_code == 204
    assert core_db.rows("SELECT * FROM core_launcher_links") == []
    assert admin.get(BASE).json()["server"] is None


def test_cancel_while_waiting_and_expired_codes(admin, suite):
    _, state, _ = suite
    admin.post(f"{BASE}/connect")
    assert admin.delete(BASE).json()["pending"] is None  # Cancel
    assert poll(admin).status_code == 409

    admin.post(f"{BASE}/connect")
    state.gone = True
    r = poll(admin)
    assert r.status_code == 409 and r.json()["detail"] == "gtd_connect_expired"
    assert admin.get(BASE).json()["pending"] is None


def test_rate_limits_and_the_poll_interval_are_honoured(admin, suite):
    _, state, _ = suite
    state.limited = True
    r = admin.post(f"{BASE}/connect")
    assert r.status_code == 502 and "60 minutes" in r.json()["detail"]

    state.limited, state.interval = False, 3
    admin.post(f"{BASE}/connect")
    admin.post(f"{BASE}/connect/poll")
    admin.post(f"{BASE}/connect/poll")  # within the suite's interval: not asked again
    assert state.polls == 1
    assert gtd._pending is not None and gtd._pending["interval"] == 3

    gtd._pending["next_poll"] = 0
    state.poll_limited = True
    assert admin.post(f"{BASE}/connect/poll").status_code == 200  # still waiting
    assert gtd._pending["next_poll"] > time.monotonic() + 100  # Retry-After: 120 s, not the 3 s interval


def test_a_wrong_address_spends_no_code(admin, suite):
    _, state, _ = suite
    state.config_status = 404
    r = admin.post(f"{BASE}/connect")
    assert r.status_code == 502 and "did not answer like a GTD suite" in r.json()["detail"]
    assert state.connects == 0


def test_an_approved_link_survives_a_prefix_clash_until_it_is_stored(admin, suite):
    base, state, _ = suite
    admin.post(f"{BASE}/connect")
    other = mcp_service.create(
        name="Other", url=f"{base}/nothing", prefix="gtd"
    )  # a row from before `gtd` was reserved
    state.approved = True
    r = poll(admin)
    assert r.status_code == 409 and r.json()["detail"] == "prefix_taken"
    assert state.gone  # the suite has handed the link out; only this install holds it now
    admin.delete(f"/api/core/mcp/servers/{other}")
    done = poll(admin).json()
    assert done["server"]["prefix"] == "gtd" and done["server"]["trusted"] is True


def test_gtd_is_reserved_and_a_hand_added_server_is_never_trusted(admin, suite):
    base, _, _ = suite
    body = {"name": "Mine", "url": f"{base}/nothing", "prefix": "gtd"}
    assert admin.post("/api/core/mcp/servers", json=body).status_code == 422  # a core namespace now
    assert admin.post("/api/core/mcp/servers", json={**body, "prefix": "mine", "trusted": True}).status_code == 422
    assert admin.post("/api/core/mcp/servers", json={**body, "prefix": "mine"}).json()["trusted"] is False
    mcp_service.create(name="Older", url=f"{base}/nothing", prefix="gtd")  # made before the reservation
    r = admin.post(f"{BASE}/connect")
    assert r.status_code == 409 and r.json()["detail"] == "gtd_prefix_taken"


def test_the_trusted_servers_address_and_prefix_are_fixed(admin, suite):
    server = connect(admin, suite)["server"]
    for change in ({"url": "https://elsewhere.example.test/mcp"}, {"prefix": "gtd2"}):
        r = admin.patch(f"/api/core/mcp/servers/{server['id']}", json=change)
        assert r.status_code == 409 and r.json()["detail"] == "trusted_server_fixed"
    off = admin.patch(f"/api/core/mcp/servers/{server['id']}", json={"enabled": False}).json()
    assert off["enabled"] is False and registry.get("gtd__list_items") is None


def test_base_url_setting_and_admin_only_routes(admin, login_as):
    for bad in ("ftp://x.test", "https://u:p@x.test", "https://x.test/path", ""):
        r = admin.put("/api/core/settings", json={"values": {"gtd.base_url": bad}})
        assert r.status_code == 422, bad
    ok = admin.put("/api/core/settings", json={"values": {"gtd.base_url": "https://x.test/"}})
    assert ok.json()["values"]["gtd.base_url"] == "https://x.test"

    member = login_as("member")
    for method, path in (
        ("get", BASE),
        ("post", f"{BASE}/connect"),
        ("post", f"{BASE}/connect/poll"),
        ("delete", BASE),
    ):
        assert getattr(member, method)(path).status_code == 403


def test_hidden_tiles_are_for_admins_only(admin, login_as, suite):
    connect(admin, suite)
    member = login_as("member")
    first = admin.get("/api/core/launcher/links").json()[0]
    assert member.patch(f"/api/core/launcher/links/{first['id']}", json={"hidden": True}).status_code == 403
    after = admin.patch(f"/api/core/launcher/links/{first['id']}", json={"hidden": True}).json()
    assert after[0] == {**first, "hidden": True}
    assert "Todo" not in tiles(member) and len(tiles(member)) == 4
    assert admin.patch("/api/core/launcher/links/9999", json={"hidden": True}).status_code == 404
