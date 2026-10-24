"""core_set_reminder and core_list_my_reminders: the reminder belongs to the acting user, a local
time is read in the install timezone and stored in UTC, the write waits for its owner's approval,
and each user lists only their own."""

import pytest

from backend.apps.todos import service as todos
from backend.core import db as core_db, settings
from backend.core.agent.providers import fake
from backend.core.contacts import api as contacts
from backend.core.reminders import api as reminders
from backend.tests.test_core_contact_tools import Refused, approve, call, chat_write, propose


@pytest.fixture(autouse=True)
def _fake_provider(monkeypatch):
    monkeypatch.setenv("AGENT_FAKE_PROVIDER", "1")
    yield
    fake.reset()


@pytest.fixture
def jane(login_as, freeze):
    settings.set_setting("timezone", "America/Chicago", None)
    freeze("2026-10-24T15:00:00Z")
    member = login_as("member")
    with core_db.transaction() as conn:
        member.jane = contacts.create_person_in(conn, member.principal, name="Jane Example")["id"]
    return member


def test_a_reminder_is_the_user_s_and_due_in_utc(jane, login_as):
    other = login_as("member")
    run = propose(jane, "core_set_reminder", entity_type="core.person", entity_id=jane.jane, due_at="2026-10-30T09:00", note="Call about the spring order")
    assert core_db.rows("SELECT * FROM core_reminders") == [], "nothing happens before approval"
    assert other.post("/api/agent/confirm", json={"tool_run_id": run, "decision": "approve"}).status_code == 403
    made = approve(jane, run)["result"]
    assert (made["due_at"], made["due_local"]) == ("2026-10-30T14:00:00Z", "2026-10-30T09:00:00-05:00")  # 09:00 CDT
    assert (made["title"], made["url"]) == ("Jane Example", f"http://localhost:8000/people/{jane.jane}")
    row = core_db.one("SELECT * FROM core_reminders")
    assert (row["owner_user_id"], row["due_at"], row["entity_type"], row["entity_id"], row["note"]) == (
        jane.principal.id, "2026-10-30T14:00:00Z", "core.person", jane.jane, "Call about the spring order",
    )  # fmt: skip

    utc = chat_write(jane, "core_set_reminder", entity_type="core.person", entity_id=jane.jane, due_at="2026-11-03T15:00:00Z")
    assert (utc["due_at"], utc["due_local"]) == ("2026-11-03T15:00:00Z", "2026-11-03T09:00:00-06:00")  # CST after the change
    bad = approve(jane, propose(jane, "core_set_reminder", entity_type="core.person", entity_id=jane.jane, due_at="next Friday"))
    assert bad["status"] == "error" and bad["error"].startswith("due_at must be an ISO date-time")


def test_each_user_lists_their_own(jane, login_as):
    admin = login_as("admin")
    first = call(jane.principal, "core_set_reminder", entity_type="core.person", entity_id=jane.jane, due_at="2026-11-02T09:00")
    later = call(jane.principal, "core_set_reminder", entity_type="core.person", entity_id=jane.jane, due_at="2026-11-05T09:00")
    reminders.snooze(jane.principal, first["id"], "2026-11-03T09:00")
    assert [(r["id"], r["status"]) for r in call(jane.principal, "core_list_my_reminders")] == [(first["id"], "snoozed"), (later["id"], "open")]
    assert call(admin.principal, "core_list_my_reminders") == []
    reminders.complete(jane.principal, later["id"])
    assert [r["id"] for r in call(jane.principal, "core_list_my_reminders", status="done")] == [later["id"]]
    assert [r["id"] for r in call(jane.principal, "core_list_my_reminders", status="open", limit=1)] == [first["id"]]
    with pytest.raises(Refused, match="open or done"):
        call(jane.principal, "core_list_my_reminders", status="voided")


def test_an_unreadable_record_is_refused(jane, login_as):
    private = todos.create_item(login_as("member").principal, "Ask about holiday dates", visibility="private")
    with pytest.raises(Refused, match="not_found"):
        call(jane.principal, "core_set_reminder", entity_type="todos.item", entity_id=private["id"], due_at="2026-11-02T09:00")
    assert core_db.rows("SELECT * FROM core_reminders") == []
