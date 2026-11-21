"""Change lists and Undo (agent.md §6), end to end over HTTP with the FakeProvider."""

import dataclasses
import json

import pytest

from backend.apps.crm import deals
from backend.apps.todos import service as todos
from backend.core import db as core_db, entities
from backend.core.agent import assembly, change_lists, execute, history, registry
from backend.core.agent.providers import fake
from backend.core.agent.providers.fake import FakeProvider
from backend.core.agent.spec import ToolSpec
from backend.core.errors import Invalid


@pytest.fixture(autouse=True)
def _fake(monkeypatch):
    monkeypatch.setenv("AGENT_FAKE_PROVIDER", "1")
    fake.reset()
    yield
    fake.reset()


def chat(client, **body) -> list[dict]:
    r = client.post("/api/agent/chat", json=body)
    assert r.status_code == 200, r.text
    return [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]


def bulk(client, ids, fields, cid=None, tool="todos_bulk_update") -> tuple[int, list[dict]]:
    args = {"ids": ids, "fields": fields} if tool == "todos_bulk_update" else {"deal_ids": ids, "stage": fields}
    fake.script({"tool": tool, "args": args}, "Done or waiting.")
    evs = chat(client, message="bulk edit", **({"conversation_id": cid} if cid else {}))
    return evs[0]["id"], evs


def of(evs, kind) -> list[dict]:
    return [e for e in evs if e["type"] == kind]


def tainted_chat(client) -> int:
    fake.script("Hello.")
    cid = chat(client, message="hi")[0]["id"]
    history.mark_tainted(cid)  # so a routine bulk edit needs its card
    return cid


def todo(user, title, **fields) -> int:
    return todos.create_item(user, title, visibility="team", **fields)["id"]


def row(item_id) -> dict:
    return core_db.must(core_db.one("SELECT * FROM todos_items WHERE id = ?", (item_id,)))


def log_count() -> int:
    return core_db.one("SELECT count(*) AS n FROM core_change_log")["n"]


def confirm(client, run_id, decision="approve") -> dict:
    r = client.post("/api/agent/confirm", json={"tool_run_id": run_id, "decision": decision})
    assert r.status_code == 200, r.text
    return r.json()


def test_card_rows_are_read_by_the_server_and_nothing_is_written(login_as):
    a = login_as("member")
    one, two = todo(a.principal, "Order flour"), todo(a.principal, "Call the plumber")
    before = log_count()
    _, evs = bulk(a, [one, two], {"visibility": "private"})  # it hides them, so it asks
    [card] = of(evs, "confirm")
    assert card["change_list"] == {"changes": 2, "records": 2}
    got = a.get(f"/api/agent/change-lists/{card['tool_run_id']}").json()
    assert got["status"] == "staged" and got["hidden"] == 0
    assert [(r["title"], r["field"], r["old"], r["new"]) for r in got["rows"]] == [
        ("Order flour", "visibility", "team", "private"),
        ("Call the plumber", "visibility", "team", "private"),
    ]
    assert log_count() == before and row(one)["visibility"] == row(two)["visibility"] == "team"


def test_approve_applies_all_or_refuses_a_list_that_changed(login_as):
    a = login_as("member")
    one, two = todo(a.principal, "Order flour"), todo(a.principal, "Call the plumber")
    _, evs = bulk(a, [one, two], {"visibility": "private"})
    run_id = of(evs, "confirm")[0]["tool_run_id"]
    todos.update_item(a.principal, one, {"title": "Order rye flour"})  # while the card waits
    out = confirm(a, run_id)
    assert out == {"status": "error", "error": change_lists.CHANGED_BEFORE_APPLY}
    assert row(one)["visibility"] == row(two)["visibility"] == "team" and row(one)["title"] == "Order rye flour"
    assert a.get(f"/api/agent/change-lists/{run_id}").json()["status"] == "not_applied"

    _, evs = bulk(a, [one, two], {"visibility": "private"})
    run_id = of(evs, "confirm")[0]["tool_run_id"]
    assert confirm(a, run_id)["status"] == "done"
    assert row(one)["visibility"] == row(two)["visibility"] == "private"
    assert a.get(f"/api/agent/change-lists/{run_id}").json()["status"] == "applied"


def test_a_routine_bulk_update_runs_at_once_and_can_be_undone(login_as):
    a = login_as("member")
    one, two = todo(a.principal, "Order flour"), todo(a.principal, "Call the plumber")
    cid, evs = bulk(a, [one, two], {"star": True})
    assert not of(evs, "confirm")
    [end] = of(evs, "tool_end")
    assert end["status"] == "done" and end["change_list"] is True
    calls = [c for m in a.get(f"/api/agent/conversations/{cid}").json()["messages"] for c in m["tool_calls"]]
    assert [c["change_list"] for c in calls] == [True]  # a reload shows it too
    assert a.get(f"/api/agent/change-lists/{end['tool_run_id']}").json()["status"] == "applied"
    out = a.post(f"/api/agent/change-lists/{end['tool_run_id']}/undo").json()
    assert out["status"] == "undone" and out["reverted"] == 2 and out["skipped"] == []
    assert row(one)["star"] == row(two)["star"] == 0


def test_undo_skips_a_record_edited_after_apply(login_as):
    a = login_as("member")
    one, two = todo(a.principal, "Order flour"), todo(a.principal, "Call the plumber")
    _, evs = bulk(a, [one, two], {"context": "@office"})
    run_id = of(evs, "tool_end")[0]["tool_run_id"]
    todos.update_item(a.principal, two, {"title": "Call the plumber today"})
    out = a.post(f"/api/agent/change-lists/{run_id}/undo").json()
    assert out["reverted"] == 1
    assert [(s["title"], s["reason"]) for s in out["skipped"]] == [
        ("Call the plumber today", change_lists.CHANGED_SINCE_APPLY)
    ]
    assert row(one)["context"] in ("", None) and row(two)["context"] == "@office"
    assert row(two)["title"] == "Call the plumber today"


def test_undo_is_once_and_owner_only(login_as):
    a, b = login_as("member"), login_as("member")
    one = todo(a.principal, "Order flour")
    _, evs = bulk(a, [one], {"star": True})
    run_id = of(evs, "tool_end")[0]["tool_run_id"]
    assert b.get(f"/api/agent/change-lists/{run_id}").status_code == 404
    assert b.post(f"/api/agent/change-lists/{run_id}/undo").json() == {"detail": "change_list_not_found"}
    assert a.post(f"/api/agent/change-lists/{run_id}/undo").status_code == 200
    again = a.post(f"/api/agent/change-lists/{run_id}/undo")
    assert again.status_code == 409 and again.json() == {"detail": "already_undone"}

    _, evs = bulk(a, [one], {"visibility": "private"})
    staged = a.post(f"/api/agent/change-lists/{of(evs, 'confirm')[0]['tool_run_id']}/undo")
    assert staged.status_code == 409 and staged.json() == {"detail": "not_applied"}
    assert not [s.name for s in registry.current().all() if "undo" in s.name]  # a user action, never a tool


def test_a_call_that_fails_or_changes_nothing_shows_no_card(login_as):
    a = login_as("member")
    one = todo(a.principal, "Order flour", star=True)
    cid = tainted_chat(a)
    for fields in ({"colour": "red"}, {"star": True}):  # an unknown field; a value it already holds
        _, evs = bulk(a, [one], fields, cid)
        [end] = of(evs, "tool_end")
        assert not of(evs, "confirm") and end["status"] == "error"
        assert not change_lists.exists(end["tool_run_id"])
    assert end["result"] == {"error": change_lists.NOTHING_TO_CHANGE}


def test_a_tainted_card_lists_what_the_tool_says_beyond_the_rows(login_as):
    a = login_as("member")
    daily = todo(a.principal, "Water the plants", repeat="daily")
    plain = todo(a.principal, "Order flour")
    cid = tainted_chat(a)
    _, evs = bulk(a, [daily, plain], {"status": "done"}, cid)
    run_id = of(evs, "confirm")[0]["tool_run_id"]
    assert a.get(f"/api/agent/change-lists/{run_id}").json()["notes"] == [
        "1 repeating todos get their next occurrence; Undo cannot take that back."
    ]


def test_the_repeat_note_counts_the_repeat_the_call_sets(login_as):
    a = login_as("member")
    daily, plain = todo(a.principal, "Water the plants", repeat="daily"), todo(a.principal, "Order flour")
    cid = tainted_chat(a)
    for fields, notes in (({"status": "done", "repeat": "daily"}, 2), ({"status": "done", "repeat": ""}, 0)):
        _, evs = bulk(a, [daily, plain], fields, cid)
        got = a.get(f"/api/agent/change-lists/{of(evs, 'confirm')[0]['tool_run_id']}").json()["notes"]
        assert got == (
            [f"{notes} repeating todos get their next occurrence; Undo cannot take that back."] if notes else []
        )


def test_undo_refuses_a_status_that_would_repeat_once_put_back(login_as):
    a = login_as("member")
    daily = todo(a.principal, "Water the plants", repeat="daily")
    todos.update_item(a.principal, daily, {"status": "done"})  # its next occurrence exists
    count = core_db.one("SELECT count(*) AS n FROM todos_items")["n"]
    _, evs = bulk(a, [daily], {"repeat": "", "status": "next_action"})
    out = a.post(f"/api/agent/change-lists/{of(evs, 'tool_end')[0]['tool_run_id']}/undo").json()
    assert [s["reason"] for s in out["skipped"]] == [todos.REPEAT_UNDO]
    assert core_db.one("SELECT count(*) AS n FROM todos_items")["n"] == count  # no second occurrence


def test_undo_refuses_a_repeating_todo_status(login_as):
    a = login_as("member")
    daily = todo(a.principal, "Water the plants", repeat="daily")
    plain = todo(a.principal, "Order flour")
    _, evs = bulk(a, [daily, plain], {"status": "done"})
    out = a.post(f"/api/agent/change-lists/{of(evs, 'tool_end')[0]['tool_run_id']}/undo").json()
    assert out["reverted"] == 1 and [s["reason"] for s in out["skipped"]] == [todos.REPEAT_UNDO]
    assert row(daily)["status"] == "done" and row(plain)["status"] != "done"


def test_a_record_refused_mid_revert_keeps_none_of_its_writes(login_as, monkeypatch):
    a = login_as("member")
    one, two = todo(a.principal, "Order flour"), todo(a.principal, "Call the plumber")
    _, evs = bulk(a, [one, two], {"star": True, "context": "@office"})
    entity = entities.get("todos.item")

    def half(conn, user, item_id, old):
        todos.revert_in(conn, user, item_id, old)  # writes, then refuses
        if item_id == one:
            raise Invalid("refused after writing")

    monkeypatch.setitem(entities._ENTITIES, "todos.item", dataclasses.replace(entity, revert_in=half))
    out = a.post(f"/api/agent/change-lists/{of(evs, 'tool_end')[0]['tool_run_id']}/undo").json()
    assert out["reverted"] == 1 and [s["reason"] for s in out["skipped"]] == ["refused after writing"]
    assert (row(one)["star"], row(one)["context"]) == (1, "@office")  # rolled back to its savepoint
    assert row(two)["star"] == 0


def test_the_model_reads_an_undo_even_after_its_run_was_summarized(login_as):
    a = login_as("member")
    one = todo(a.principal, "Order flour")
    fake.script("Hello.")
    cid = chat(a, message="hi")[0]["id"]  # the opening exchange stays verbatim across compactions
    _, evs = bulk(a, [one], {"star": True}, cid)
    a.post(f"/api/agent/change-lists/{of(evs, 'tool_end')[0]['tool_run_id']}/undo")

    def notes() -> int:
        return json.dumps(assembly.assemble_messages(FakeProvider("fake"), cid)).count(
            "The user undid this change list"
        )

    assert notes() == 1
    for text in ("two", "three", "four"):
        fake.script(f"Reply {text}.")
        chat(a, message=text, conversation_id=cid)
    kept = core_db.one(
        "SELECT max(id) AS id FROM core_agent_messages WHERE conversation_id = ? AND role = 'user'", (cid,)
    )
    history.set_compaction(cid, "<gist>The user starred a todo.</gist>", kept["id"])
    assert notes() == 1  # its row is in the summarized middle now; the note rides on the gist


def test_crm_bulk_move_is_undone(login_as):
    a = login_as("member")
    with core_db.transaction() as conn:
        ids = [deals.create_in(conn, a.principal, {"title": t, "stage": "lead"})["id"] for t in ("Cakes", "Pies")]
    _, evs = bulk(a, ids, "qualified", tool="crm_bulk_move_deals")
    [end] = of(evs, "tool_end")
    assert end["change_list"] is True
    out = a.post(f"/api/agent/change-lists/{end['tool_run_id']}/undo").json()
    assert out["reverted"] == 2
    stages = core_db.rows("SELECT stage FROM crm_deals WHERE id IN (?, ?)", tuple(ids))
    assert [s["stage"] for s in stages] == ["lead", "lead"]
    events = core_db.rows("SELECT new_stage FROM crm_deal_stage_events WHERE deal_id = ? ORDER BY id", (ids[0],))
    assert [e["new_stage"] for e in events] == ["lead", "qualified", "lead"]


def test_change_list_needs_a_local_write():
    spec = ToolSpec(
        name="core_t",
        description="t",
        input_schema={"type": "object", "properties": {}},
        writes=True,
        external_effect=True,
        handler=lambda user, args: None,
        change_list=True,
    )
    with pytest.raises(registry.ToolSpecError, match="change_list"):
        registry.build_registry([spec])


def test_mcp_runs_record_no_change_list(login_as):
    a = login_as("member")
    one = todo(a.principal, "Order flour")
    spec = core_db.must(registry.get("todos_bulk_update"))
    out = execute.run_tool(a.principal, spec, {"ids": [one], "fields": {"star": True}}, source="mcp", client="t")
    assert out["status"] == "done" and not change_lists.exists(out["id"])
