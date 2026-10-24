"""Core contacts tools for Whisk: the specs validate and reach human users only, reads work for a
member and an admin, every write waits for its owner's approval on the real chat -> confirm path,
duplicate names come back as a result, and an inbound MCP link lists them. The chat helpers here
serve the timeline and reminder tool tests too."""

import json

import pytest

from backend.core import db as core_db
from backend.core.agent import engine, execute, registry
from backend.core.agent.providers import fake
from backend.core.auth.deps import system_user
from backend.core.contacts import api as contacts
from backend.tests.test_mcp_links import at, list_tools, mint

READS = {"core_search_contacts", "core_get_person", "core_get_organization", "core_list_my_reminders"}
WRITES = {"core_create_person", "core_create_organization", "core_link_person_organization", "core_add_note", "core_set_reminder"}


class Refused(Exception):
    """A tool run that ended in error; the message is the run's error text."""


def call(user, tool, /, **args):
    """Run a tool as chat approvals and MCP do (execute.run_tool), raising Refused on an error."""
    out = execute.run_tool(user, registry.get(tool), args, source="mcp")
    if out["status"] != "done":
        raise Refused(out["error"])
    return out["result"]


@pytest.fixture
def chat(monkeypatch):
    monkeypatch.setenv("AGENT_FAKE_PROVIDER", "1")
    fake.reset()
    yield
    fake.reset()


def propose(client, tool: str, /, **args) -> int:
    """One chat turn in which the model calls `tool`; the write waits for approval. Returns the run id."""
    fake.reset()
    fake.script({"tool": tool, "args": args}, "Done.")
    r = client.post("/api/agent/chat", json={"message": "go"})
    assert r.status_code == 200, r.text
    events = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]
    assert not [e for e in events if e["type"] == "tool_end"], "a write never runs before approval"
    return next(e for e in events if e["type"] == "confirm")["tool_run_id"]


def approve(client, run_id: int) -> dict:
    r = client.post("/api/agent/confirm", json={"tool_run_id": run_id, "decision": "approve"})
    assert r.status_code == 200, r.text
    return r.json()


def chat_write(client, tool: str, /, **args) -> dict:
    """Propose, approve as the conversation's owner, and return the result of the run (done)."""
    out = approve(client, propose(client, tool, **args))
    assert out["status"] == "done", out
    return out["result"]


def _seed(user) -> tuple[int, int]:
    with core_db.transaction() as conn:
        org = contacts.create_organization_in(conn, user, name="Acme Bakery Supply", domain="example.com")["id"]
        jane = contacts.create_person_in(conn, user, name="Jane Example", email="jane@example.com", title="Buyer")["id"]
        contacts.link_in(conn, user, jane, org, "buyer")
    return org, jane


def test_the_specs_validate_and_reach_active_humans_only(app, make_user):
    member, admin = make_user("member"), make_user("admin")
    specs = {s.name: s for s in registry.current().all() if s.name in READS | WRITES}
    assert specs.keys() == READS | WRITES
    assert [p for s in specs.values() for p in registry._problems(s)] == []
    assert {n for n, s in specs.items() if s.writes} == WRITES
    assert all(engine.needs_confirmation(specs[n], {}, tainted=False) for n in WRITES), "every write shows the Approve card"
    for user in (member, admin):
        assert READS | WRITES <= {s.name for s in registry.for_user(user)}
    assert not {s.name for s in registry.for_user(system_user())} & (READS | WRITES)
    assert not {s.name for s in registry.for_source("job")} & WRITES
    assert READS | WRITES <= {s.name for s in registry.for_source("mcp")}


def test_reads_as_a_member_and_an_admin(app, make_user):
    member, admin = make_user("member"), make_user("admin")
    org, jane = _seed(member)
    for user in (member, admin):
        [hit] = call(user, "core_search_contacts", query="jane")
        assert hit == {
            "kind": "person", "id": jane, "name": "Jane Example", "email": "jane@example.com",
            "url": f"http://localhost:8000/people/{jane}", "organizations": [{"id": org, "name": "Acme Bakery Supply", "role": "buyer"}],
        }  # fmt: skip
        assert [h["id"] for h in call(user, "core_search_contacts", query="acme", kind="organization")] == [org]
        assert call(user, "core_search_contacts", query="acme", kind="person") == []

        person = call(user, "core_get_person", id=jane)
        assert (person["title"], person["url"]) == ("Buyer", f"http://localhost:8000/people/{jane}")
        assert person["organizations"] == [
            {"id": org, "name": "Acme Bakery Supply", "role": "buyer", "is_primary": True, "url": f"http://localhost:8000/organizations/{org}"}
        ]
        assert [(c["kind"], c["value"]) for c in person["channels"]] == [("email", "jane@example.com")]
        organization = call(user, "core_get_organization", id=org)
        assert organization["domain"] == "example.com" and organization["url"].endswith(f"/organizations/{org}")
        assert [(p["id"], p["role"], p["url"]) for p in organization["people"]] == [(jane, "buyer", f"http://localhost:8000/people/{jane}")]
        with pytest.raises(Refused, match="not_found"):
            call(user, "core_get_person", id=9999)

    with core_db.transaction() as conn:
        twin = contacts.create_person_in(conn, member, name="Jane E.")["id"]
        contacts.merge_people_in(conn, member, jane, twin)
    merged = call(member, "core_get_person", id=twin)
    assert (merged["id"], merged["merged_from"]) == (jane, twin)


def test_writes_wait_for_the_owner_s_approval(login_as, chat):
    member, other = login_as("member"), login_as("member")
    run = propose(member, "core_create_organization", name="Acme Bakery Supply", domain="example.com")
    assert contacts.search(member.principal, "acme") == [], "nothing happens before approval"
    assert other.post("/api/agent/confirm", json={"tool_run_id": run, "decision": "approve"}).status_code == 403
    made = approve(member, run)
    assert made["status"] == "done" and made["result"]["created"] is True
    org = made["result"]["id"]
    assert made["result"]["url"] == f"http://localhost:8000/organizations/{org}"

    jane = chat_write(member, "core_create_person", name="Jane Example", email="jane@example.com", title="Buyer", organization_id=org, role="buyer")
    assert jane["created"] is True and jane["url"].endswith(f"/people/{jane['id']}")
    assert [(o["id"], o["role"]) for o in jane["organizations"]] == [(org, "buyer")]

    again = chat_write(member, "core_create_person", name="  jane EXAMPLE ")
    assert again["created"] is False and [p["id"] for p in again["existing"]] == [jane["id"]]
    assert chat_write(member, "core_create_organization", name="ACME bakery supply")["existing"]["id"] == org
    namesake = chat_write(member, "core_create_person", name="Jane Example", allow_duplicate=True)
    assert namesake["created"] is True and namesake["id"] != jane["id"]

    link = chat_write(member, "core_link_person_organization", person_id=namesake["id"], organization_id=org, role="owner", primary=True)
    assert (link["role"], link["is_primary"], link["organization"]["name"]) == ("owner", True, "Acme Bakery Supply")
    assert link["person"]["url"].endswith(f"/people/{namesake['id']}")
    people = contacts.people_for(member.principal, org)
    assert sorted((p["person_id"], p["role"]) for p in people) == [(jane["id"], "buyer"), (namesake["id"], "owner")]


def test_the_system_principal_never_writes(app, make_user):
    org, _ = _seed(make_user("member"))
    with pytest.raises(Refused, match="forbidden"):
        call(system_user(), "core_create_person", name="Jane Example", organization_id=org)


def test_an_mcp_link_lists_the_contacts_tools(app, login_as):
    tools = list_tools(app, at(mint(login_as("member"))))
    assert {"core_search_contacts", "core_create_person", "core_add_note", "core_set_reminder"} <= tools.keys()
    assert tools["core_search_contacts"].annotations.read_only_hint is True
