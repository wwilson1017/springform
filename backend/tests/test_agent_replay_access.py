"""Stored tool results are rechecked when shown again (authorization.md §5, "Whisk tool results"): a
result naming a record the user can no longer read is withheld from later turns, the conversation
view, a replayed turn event and `core_read_result`, while the stored row keeps it."""

import json

import pytest

from backend.core import clock, db
from backend.core.agent import assembly, execute, history, registry as tool_registry
from backend.core.agent.providers import fake
from backend.core.agent.providers.fake import FakeProvider
from backend.core.agent.spec import ToolSpec

SCHEMA = {"type": "object", "properties": {}}
MARKER = "marker-q7"


@pytest.fixture(autouse=True)
def _fake(monkeypatch):
    monkeypatch.setenv("AGENT_FAKE_PROVIDER", "1")
    fake.reset()
    yield
    fake.reset()


@pytest.fixture
def extra_tools(app):
    """add(*specs): extra tools in the live registry for this test."""
    before = tool_registry.current()
    yield lambda *specs: tool_registry.set_current(tool_registry.build_registry([*before.all(), *specs]))
    tool_registry.set_current(before)


def chat(client, **body) -> list[dict]:
    r = client.post("/api/agent/chat", json=body)
    assert r.status_code == 200, r.text
    return [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]


def call(client, tool: str, args: dict, **body) -> tuple[dict, list[dict]]:
    evs = chat(client, **body, message=f"/tool {tool} {json.dumps(args)}")
    return next(e for e in evs if e["type"] == "tool_end"), evs


def team_todo(owner, title: str) -> int:
    r = owner.post("/api/todos/items", json={"title": title, "notes": MARKER, "visibility": "team"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def replayed(cid: int) -> str:
    return json.dumps(assembly.assemble_messages(FakeProvider("fake"), cid))


def stored(run_id: int) -> dict:
    return db.must(db.one("SELECT records, result FROM core_agent_tool_runs WHERE id = ?", (run_id,)))


@pytest.mark.parametrize("change", ["private", "deleted"])
def test_a_result_naming_a_record_the_user_lost_is_withheld_everywhere(login_as, change):
    owner, member = login_as("member"), login_as("member")
    todo = team_todo(owner, "Restock bin seven")
    end, evs = call(member, "todos_get", {"id": todo})
    cid, turn, run = evs[0]["id"], evs[0]["turn_id"], end["tool_run_id"]
    assert end["status"] == "done" and json.loads(stored(run)["records"]) == [["todos.item", todo]]
    assert MARKER in replayed(cid)

    if change == "private":
        assert owner.patch(f"/api/todos/items/{todo}", json={"visibility": "private"}).status_code == 200
    else:
        assert owner.delete(f"/api/todos/items/{todo}").status_code == 200

    assert history.WITHHELD in replayed(cid) and MARKER not in replayed(cid)
    [shown] = [c for m in member.get(f"/api/agent/conversations/{cid}").json()["messages"] for c in m["tool_calls"]]
    assert shown["result"] == history.WITHHELD
    events = member.get(f"/api/agent/turns/{turn}/events?after=-1").text
    assert history.WITHHELD in events and MARKER not in events
    page, _ = call(member, "core_read_result", {"handle": f"r{run}"}, conversation_id=cid)
    assert page["status"] == "error" and "withheld" in page["result"]["error"]
    assert MARKER in stored(run)["result"]  # storage keeps it: the recheck only changes what is shown

    if change == "private":  # access that comes back shows it again
        assert owner.patch(f"/api/todos/items/{todo}", json={"visibility": "team"}).status_code == 200
        assert MARKER in replayed(cid)


def test_one_lost_row_withholds_the_whole_list(login_as):
    owner, member = login_as("member"), login_as("member")
    kept, lost = team_todo(owner, "Count bin one"), team_todo(owner, "Count bin two")
    end, evs = call(member, "todos_list", {})
    assert {tuple(r) for r in json.loads(stored(end["tool_run_id"])["records"])} >= {
        ("todos.item", kept),
        ("todos.item", lost),
    }
    owner.patch(f"/api/todos/items/{lost}", json={"visibility": "private"})
    text = replayed(evs[0]["id"])
    assert history.WITHHELD in text and "Count bin one" not in text


def test_a_project_that_goes_private_is_withheld(login_as):
    owner, member = login_as("member"), login_as("member")
    r = owner.post("/api/todos/projects", json={"name": "Shelf move", "purpose": MARKER, "visibility": "team"})
    assert r.status_code == 200, r.text
    project = r.json()["id"]
    end, evs = call(member, "todos_list_projects", {})
    assert ["todos.project", project] in json.loads(stored(end["tool_run_id"])["records"])
    assert owner.patch(f"/api/todos/projects/{project}", json={"visibility": "private"}).status_code == 200
    assert MARKER not in replayed(evs[0]["id"])


def test_a_page_read_before_the_change_is_withheld_after_it(login_as, extra_tools):
    owner, member = login_as("member"), login_as("member")
    todo = team_todo(owner, "Label shelf four")
    big = f"{MARKER}\n" + "".join(f"line {i:05d} {'x' * 40}\n" for i in range(1500))
    extra_tools(
        ToolSpec(
            name="core_big_todo_text",
            description="d",
            input_schema=SCHEMA,
            writes=False,
            handler=lambda u, a: big,
            reads=lambda args, result: [("todos.item", todo)],
        )
    )
    end, evs = call(member, "core_big_todo_text", {})
    cid = evs[0]["id"]
    page, _ = call(member, "core_read_result", {"handle": f"r{end['tool_run_id']}"}, conversation_id=cid)
    assert page["status"] == "done" and MARKER in page["result"]
    assert json.loads(stored(page["tool_run_id"])["records"]) == [["todos.item", todo]]
    owner.patch(f"/api/todos/items/{todo}", json={"visibility": "private"})
    assert MARKER not in replayed(cid)


def test_a_failing_reads_still_runs_the_tool_and_withholds_its_result(login_as, extra_tools):
    member = login_as("member")

    def boom(args, result):
        raise RuntimeError("bad matcher")

    def insert(conn, user, args):
        now = clock.now_iso()
        conn.execute("INSERT INTO core_people (name, created_at, updated_at) VALUES ('Shelf Co', ?, ?)", (now, now))
        return {"saved": MARKER}

    extra_tools(
        ToolSpec(name="core_boom_read", description="d", input_schema=SCHEMA, writes=False,
                 handler=lambda u, a: {"seen": MARKER}, reads=boom),
        ToolSpec(name="core_boom_write", description="d", input_schema=SCHEMA, writes=True, confirm_tier="routine",
                 handler_in=insert, targets=lambda a: [], reads=boom, summary="Save it."),
    )  # fmt: skip
    for tool in ("core_boom_read", "core_boom_write"):
        end, evs = call(member, tool, {})
        assert end["status"] == "done" and stored(end["tool_run_id"])["records"] == history.UNKNOWN
        assert MARKER not in replayed(evs[0]["id"])
    assert db.one("SELECT 1 FROM core_people WHERE name = 'Shelf Co'")  # the write committed


def test_older_runs_get_their_records_at_startup(login_as):
    owner, member = login_as("member"), login_as("member")
    todo = team_todo(owner, "Sweep aisle two")
    cid = chat(member, message="hello")[0]["id"]
    row = json.dumps({"id": todo, "title": "Sweep aisle two", "status": "inbox", "visibility": "team"})
    fenced = json.dumps('<untrusted_external_content id="ab">page</untrusted_external_content id="ab">')
    ids = {
        name: history.insert_tool_run(
            conversation_id=cid, tool=name, args={"id": todo}, status="done", user_id=member.user["id"], result=result
        )
        for name, result in [
            ("todos_get", row),
            ("core_gone_tool", row),
            ("core_gone_remote", fenced),
            ("core_find_tools", json.dumps({"loaded": ["todos_get"]})),
        ]
    }
    assert stored(ids["todos_get"])["records"] is None  # as a run stored before the column was
    assert execute.backfill_records() >= 3
    assert json.loads(stored(ids["todos_get"])["records"]) == [["todos.item", todo]]
    assert stored(ids["core_gone_tool"])["records"] == history.UNKNOWN  # its tool is gone: withheld
    assert stored(ids["core_gone_remote"])["records"] == "[]"  # a remote tool's fenced text
    assert stored(ids["core_find_tools"])["records"] == "[]"  # not a registry spec, but names no record


def test_each_shipped_module_names_what_its_results_carry(app, make_user):
    me = make_user("member")

    def named(tool: str, **args) -> tuple[set, dict]:
        out = execute.run_tool(me, db.must(tool_registry.current().get(tool)), args, source="mcp")
        assert out["status"] == "done", out["error"]
        return {tuple(r) for r in json.loads(stored(out["id"])["records"])}, out["result"]

    people, person = named("core_create_person", name="Shelf Person")
    assert people == {("core.person", person["id"])}
    assert named("core_search_contacts", query="Shelf")[0] == people
    deals, deal = named("crm_create_deal", title="Shelf order", person_id=person["id"])
    assert ("crm.deal", deal["id"]) in deals
    named("crm_create_deal", title="Shelf order", person_id=person["id"])
    assert ("crm.deal", deal["id"]) in named("crm_search_deals", q="Shelf")[0]
    assert ("crm.deal", deal["id"]) in named("crm_find_duplicate_deals")[0]
    assert named("crm_get_lead_score", deal_id=deal["id"])[0] == {("crm.deal", deal["id"])}
    assert named("crm_get_lead_score", person_id=person["id"])[0] == people
    assert named("core_add_note", entity_type="crm.deal", entity_id=deal["id"], body="Call back")[0] == {
        ("crm.deal", deal["id"])
    }
    when = "2030-01-01T09:00"
    assert ("crm.deal", deal["id"]) in named(
        "core_set_reminder", entity_type="crm.deal", entity_id=deal["id"], due_at=when
    )[0]
    assert ("crm.deal", deal["id"]) in named("core_list_my_reminders")[0]
    widgets, widget = named("example_create_widget", name="Shelf widget", is_private=True)
    assert widgets == {("example.widget", widget["id"])}
    assert named("example_list_widgets")[0] == widgets
