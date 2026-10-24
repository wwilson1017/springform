"""core_add_note: a routine write, so it runs inline in the chat turn: a note on any record the
user can write, authored by them; refused for another member's private todo and unknown types."""

import pytest

from backend.apps.todos import service as todos
from backend.core import db as core_db
from backend.core.agent.providers import fake
from backend.core.contacts import api as contacts
from backend.core.timeline import api as timeline
from backend.tests.test_core_contact_tools import Refused, call, inline


@pytest.fixture(autouse=True)
def _fake_provider(monkeypatch):
    monkeypatch.setenv("AGENT_FAKE_PROVIDER", "1")
    yield
    fake.reset()


def test_a_note_lands_on_the_record_as_the_user(login_as):
    member, other = login_as("member"), login_as("member")
    with core_db.transaction() as conn:
        jane = contacts.create_person_in(conn, member.principal, name="Jane Example")["id"]
    end = inline(member, "core_add_note", entity_type="core.person", entity_id=jane, body="Prefers calls after 2pm.")
    note = end["result"]
    assert end["status"] == "done"
    assert (note["body"], note["author"]["id"], note["url"]) == ("Prefers calls after 2pm.", member.principal.id, f"http://localhost:8000/people/{jane}")
    [entry] = timeline.list_for(member.principal, "core.person", jane)
    assert (entry["kind"], entry["author"]["id"]) == ("note", member.principal.id)

    todo = todos.create_item(member.principal, "Order flour", visibility="team")
    end = inline(other, "core_add_note", entity_type="todos.item", entity_id=todo["id"], body="Done Friday")
    assert (end["status"], end["result"]["author"]["id"]) == ("done", other.principal.id)


def test_another_member_s_private_todo_and_unknown_types_are_refused(login_as):
    owner, other, admin = login_as("member"), login_as("member"), login_as("admin")
    private = todos.create_item(owner.principal, "Ask about holiday dates", visibility="private")
    for client in (other, admin):
        end = inline(client, "core_add_note", entity_type="todos.item", entity_id=private["id"], body="Peeking")
        assert (end["status"], end["result"]) == ("error", {"error": "not_found"})
    assert timeline.list_for(owner.principal, "todos.item", private["id"]) == []
    with pytest.raises(Refused, match="entity_type must be one of: .*core.person"):
        call(owner.principal, "core_add_note", entity_type="people", entity_id=1, body="x")
