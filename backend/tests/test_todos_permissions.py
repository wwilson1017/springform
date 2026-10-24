"""Todos with more than one person: who sees and changes what, the hierarchy rule, transfer and
deactivation, record links, reset, the published API, the Whisk tools and the HTTP surface."""

import pytest

from backend.apps.todos import api as todos_api, service
from backend.apps.todos.models import Area, Item, Project
from backend.core import clock, db as core_db, entities, registry
from backend.core.agent import registry as tools
from backend.core.errors import Forbidden, Invalid, NotFound
from backend.core.reports import registry as reports

API = "/api/todos"


def titles(rows):
    return [r["title"] for r in rows]


def _person() -> int:
    now = clock.now_iso()
    with core_db.transaction() as conn:
        return conn.execute("INSERT INTO core_people (name, created_at, updated_at) VALUES ('Ada', ?, ?)", (now, now)).lastrowid


@pytest.fixture
def two(app, make_user):
    return make_user(), make_user()


# ── Private, team, admin ──────────────────────────────────────────────────────


def test_a_private_todo_is_invisible_to_another_member_on_every_surface(login_as):
    owner, other = login_as("member"), login_as("member")
    person = _person()
    link = {"entity_type": "core.person", "entity_id": person}
    secret = owner.post(f"{API}/items", json={"title": "Secret plan", "context": "@hush", "tags": ["hidden"], **link}).json()
    shared = owner.post(f"{API}/items", json={"title": "Shared", "visibility": "team", **link}).json()
    owner.post("/api/core/timeline", json={"entity_type": "todos.item", "entity_id": secret["id"], "body": "hush"})
    url, note = f"{API}/items/{secret['id']}", {"entity_type": "todos.item", "entity_id": secret["id"]}

    assert titles(owner.get(f"{API}/items").json()) == ["Secret plan", "Shared"]
    assert titles(other.get(f"{API}/items").json()) == ["Shared"]
    assert other.get(f"{API}/items", params={"search": "secret"}).json() == []
    assert other.get(url).status_code == 404
    assert other.patch(url, json={"title": "Mine"}).status_code == 404
    assert other.post(f"{url}/complete").status_code == 404
    assert other.delete(url).status_code == 404
    bulk = other.post(f"{API}/items/bulk", json={"ids": [secret["id"]], "fields": {"star": True}}).json()
    assert bulk == {"updated": [], "not_found": [secret["id"]]}
    assert titles(other.get(f"{API}/for/core.person/{person}").json()) == ["Shared"]
    assert titles(owner.get(f"{API}/for/core.person/{person}").json()) == ["Secret plan", "Shared"]
    assert other.get("/api/core/timeline", params=note).status_code == 404
    assert other.post("/api/core/timeline", json={**note, "body": "hi"}).status_code == 404
    feed = other.get(f"{API}/changes").json()
    assert [t["id"] for t in feed["items"]] == [shared["id"]] and feed["removed"]["items"] == []
    f = other.get(f"{API}/filters").json()
    assert (f["contexts"], f["tags"], f["status_counts"]["inbox"]) == ([], [], 1)
    assert other.get(f"{API}/badge").json() == {"count": 1, "label": "Inbox"}
    assert owner.get(f"{API}/badge").json() == {"count": 2, "label": "Inbox"}
    assert other.get(f"{API}/review").json()["inbox"]["count"] == 1
    conn = core_db.get_conn()
    assert entities.titles_for(other.principal, conn, "todos.item", [secret["id"], shared["id"]]) == {shared["id"]: "Shared"}
    report = reports.get("todos.open_team_by_assignee")
    assert report.run({}, other.principal) == (["assignee", "open"], [["Unassigned", 1]])
    assert titles(tools.get("todos_list").handler(other.principal, {})) == ["Shared"]
    with pytest.raises(NotFound):
        todos_api.complete(other.principal.id, secret["id"])
    # Nor can it be used as a link target by someone who cannot read it.
    assert other.post(f"{API}/items", json={"title": "x", "entity_type": "todos.item", "entity_id": secret["id"]}).status_code == 422
    assert owner.get(url).json()["title"] == "Secret plan"


def test_a_team_todo_is_every_members_to_edit_complete_and_reassign(login_as):
    a, b = login_as("member"), login_as("member")
    url = f"{API}/items/{a.post(f'{API}/items', json={'title': 'Restock', 'visibility': 'team'}).json()['id']}"
    edited = b.patch(url, json={"title": "Restock cups", "assignee_user_id": b.user["id"]}).json()
    assert (edited["title"], edited["assignee_name"]) == ("Restock cups", b.user["name"])
    assert b.patch(url, json={"assignee_user_id": a.user["id"]}).json()["assignee_user_id"] == a.user["id"]
    assert b.patch(url, json={"assignee_user_id": 999}).status_code == 422
    assert b.patch(url, json={"visibility": "private"}).status_code == 403  # the owner's call
    assert b.patch(url, json={"owner_user_id": b.user["id"]}).status_code == 403  # the owner's or an admin's
    assert b.delete(url).status_code == 403
    assert b.post(f"{url}/complete").json()["status"] == "done"
    assert a.get(url).json()["title"] == "Restock cups"
    timeline = a.get("/api/core/timeline", params={"entity_type": "todos.item", "entity_id": int(url.rsplit("/", 1)[1])}).json()
    assert {e["author"]["id"] for e in timeline} == {b.user["id"]}
    # The owner may take it private once it is assigned to nobody else.
    b.patch(url, json={"assignee_user_id": b.user["id"]})
    assert a.patch(url, json={"visibility": "private"}).status_code == 422
    assert a.patch(url, json={"visibility": "private", "assignee_user_id": None}).json()["visibility"] == "private"
    assert b.get(url).status_code == 404


def test_admins_see_team_todos_and_their_own_never_anothers_private(login_as):
    admin, member = login_as("admin"), login_as("member")
    mine = member.post(f"{API}/items", json={"title": "Member's secret"}).json()
    team = member.post(f"{API}/items", json={"title": "Team", "visibility": "team"}).json()
    admin.post(f"{API}/items", json={"title": "Admin's own"})
    assert titles(admin.get(f"{API}/items").json()) == ["Team", "Admin's own"]
    assert admin.get(f"{API}/items/{mine['id']}").status_code == 404
    assert admin.get(f"{API}/changes").json()["items"][0]["id"] == team["id"]
    # An admin may make a private todo for someone else, and cannot read it afterwards.
    made = admin.post(f"{API}/items", json={"title": "For you", "owner_user_id": member.user["id"]}).json()
    assert (made["owner_user_id"], made["visibility"]) == (member.user["id"], "private")
    assert admin.get(f"{API}/items/{made['id']}").status_code == 404
    assert member.get(f"{API}/items/{made['id']}").status_code == 200
    # A member may not; a team todo owned by someone else is fine.
    assert member.post(f"{API}/items", json={"title": "x", "owner_user_id": admin.user["id"]}).status_code == 403
    assert member.post(f"{API}/items", json={"title": "x", "owner_user_id": admin.user["id"], "visibility": "team"}).status_code == 200
    # An admin may give a team todo away, and delete one.
    assert admin.patch(f"{API}/items/{team['id']}", json={"owner_user_id": admin.user["id"]}).json()["owner_user_id"] == admin.user["id"]
    assert admin.delete(f"{API}/items/{team['id']}").json() == {"deleted": team["id"]}


def test_private_assignees_and_owners_are_people(two):
    a, b = two
    with pytest.raises(Invalid, match="private todo can only be assigned to its owner"):
        service.create_item(a, "x", assignee_user_id=b.id)
    assert service.create_item(a, "x", assignee_user_id=a.id)["assignee_user_id"] == a.id
    with pytest.raises(Invalid, match="owner_user_id: no such active user"):
        service.create_item(a, "x", visibility="team", owner_user_id=999)
    with pytest.raises(Invalid, match="assignee_user_id: no such active user"):
        service.create_item(a, "x", visibility="team", assignee_user_id=999)
    assert service.create_item(a, "x", visibility="team", assignee_user_id=0)["assignee_user_id"] is None  # 0 clears


# ── The hierarchy rule ────────────────────────────────────────────────────────


def test_the_hierarchy_rule_on_create(two):
    a, b = two
    team_area, a_area = service.create_area(a, "Ops", visibility="team"), service.create_area(a, "Mine")
    team_project, a_project = service.create_project(a, "Shop", visibility="team"), service.create_project(a, "Quiet")
    with pytest.raises(Invalid, match="A team todo can only sit in a team project"):
        service.create_item(a, "x", visibility="team", project_id=a_project["id"])
    with pytest.raises(Invalid, match="A team todo can only sit in a team area"):
        service.create_item(a, "x", visibility="team", area_id=a_area["id"])
    with pytest.raises(Invalid, match="project_id: no such project"):  # b cannot see it at all
        service.create_item(b, "x", project_id=a_project["id"])
    with pytest.raises(Invalid, match="A team project can only sit in a team area"):
        service.create_project(a, "x", visibility="team", area_id=a_area["id"])
    with pytest.raises(Invalid, match="area_id: no such area"):
        service.create_project(b, "x", area_id=a_area["id"])
    assert service.create_item(a, "own private project", project_id=a_project["id"])["project_name"] == "Quiet"
    assert service.create_item(b, "private in a team project", project_id=team_project["id"])["project_name"] == "Shop"
    assert service.create_project(b, "private in a team area", area_id=team_area["id"])["area_name"] == "Ops"
    assert service.create_project(a, "private in own area", area_id=a_area["id"])["area_name"] == "Mine"


def test_the_hierarchy_rule_on_move_reassign_and_visibility_change(two):
    a, b = two
    a_area = service.create_area(a, "Mine")
    team_project, a_project = service.create_project(a, "Shop", visibility="team"), service.create_project(a, "Quiet")
    shared = service.create_item(b, "shared", visibility="team")
    # Move: a team todo into a private project.
    with pytest.raises(Invalid, match="A team todo can only sit in a team project"):
        service.update_item(a, shared["id"], {"project_id": a_project["id"]})
    assert service.update_item(a, shared["id"], {"project_id": team_project["id"]})["project_id"] == team_project["id"]
    # Visibility change of the child: a private todo in a private project cannot go team.
    quiet = service.create_item(a, "quiet", project_id=a_project["id"])
    with pytest.raises(Invalid, match="A team todo can only sit in a team project"):
        service.update_item(a, quiet["id"], {"visibility": "team"})
    # Reassign (a new owner): it would sit in someone else's private project.
    with pytest.raises(Invalid, match="private todo can only sit in a team project or one of its owner's private projects"):
        service.update_item(a, quiet["id"], {"owner_user_id": b.id})
    moved = service.update_item(a, quiet["id"], {"owner_user_id": b.id, "project_id": None})
    assert moved["owner_user_id"] == b.id
    with pytest.raises(NotFound):
        service.get_item(a, quiet["id"])
    # Visibility change of the parent: a project cannot go private holding team or someone else's todos.
    with pytest.raises(Invalid, match="holds team or someone else's todos"):
        service.update_container(a, "project", team_project["id"], {"visibility": "private"})
    service.update_item(a, shared["id"], {"project_id": None})
    service.create_item(b, "b's own, in the team project", project_id=team_project["id"])
    with pytest.raises(Invalid, match="holds team or someone else's todos"):
        service.update_container(a, "project", team_project["id"], {"visibility": "private"})
    lone = service.create_project(a, "Lone", visibility="team")
    service.create_item(a, "a's own", project_id=lone["id"])
    assert service.update_container(a, "project", lone["id"], {"visibility": "private"})["visibility"] == "private"
    # …nor change hands holding the old owner's todos, nor sit in the old owner's area afterwards.
    with pytest.raises(Invalid, match="holds team or someone else's todos"):
        service.update_container(a, "project", lone["id"], {"owner_user_id": b.id})
    # An area likewise, and a team project cannot move into a private area.
    team_area = service.create_area(a, "Ops", visibility="team")
    service.update_container(a, "project", team_project["id"], {"area_id": team_area["id"]})
    with pytest.raises(Invalid, match="holds team or someone else's projects or todos"):
        service.update_container(a, "area", team_area["id"], {"visibility": "private"})
    with pytest.raises(Invalid, match="A team project can only sit in a team area"):
        service.update_container(a, "project", team_project["id"], {"area_id": a_area["id"]})
    # Only the owner takes a team row private.
    with pytest.raises(Forbidden):
        service.update_container(b, "area", team_area["id"], {"visibility": "private"})


def test_a_repeating_team_todo_comes_back_with_its_visibility_and_assignee(two):
    a, b = two
    t = service.create_item(a, "Count the till", visibility="team", assignee_user_id=b.id, repeat="daily", status="next_action")
    service.complete(b, t["id"])
    [nxt] = service.list_items(a, status="next_action")
    assert (nxt["visibility"], nxt["assignee_user_id"], nxt["owner_user_id"]) == ("team", b.id, a.id)
    service.complete(a, service.create_item(a, "Stretch", repeat="daily", status="next_action")["id"])
    assert titles(service.list_items(a, status="next_action", visibility="private")) == ["Stretch"]
    assert service.list_items(b, search="Stretch") == []


# ── Work, Today and the badge ─────────────────────────────────────────────────


def test_badge_and_today_count_the_users_work(two, freeze):
    freeze("2026-08-08T12:00:00Z")
    a, b = two
    for user, title, fields in [
        (a, "my private inbox", {}),
        (a, "my private next", {"status": "next_action", "star": True}),
        (b, "team, unassigned", {"visibility": "team", "star": True}),
        (b, "team, mine", {"visibility": "team", "assignee_user_id": a.id, "due_date": "2026-08-08"}),
        (a, "team, theirs", {"visibility": "team", "assignee_user_id": b.id, "star": True}),
        (a, "deferred", {"revisit_on": "2026-08-09"}),
        (b, "b's private inbox", {"star": True}),
    ]:  # fmt: skip
        service.create_item(user, title, **fields)
    assert service.badge(a) == {"count": 3, "label": "Inbox"}  # private inbox, team unassigned, team mine
    assert service.badge(b) == {"count": 3, "label": "Inbox"}  # team unassigned, team theirs, b's private
    assert titles(service.today_view(a)) == ["team, mine", "my private next", "team, unassigned"]
    assert titles(service.list_items(a, mine=True)) == ["my private inbox", "my private next", "team, unassigned", "team, mine"]
    assert titles(service.list_items(a, assignee_user_id=b.id)) == ["team, theirs"]


# ── Deactivation and transfer ─────────────────────────────────────────────────


def test_deactivation_hides_private_todos_until_an_admin_transfers_them(login_as):
    admin, leaver, heir = login_as("admin"), login_as("member"), login_as("member")
    lid, hid = leaver.user["id"], heir.user["id"]
    area = leaver.post(f"{API}/areas", json={"name": "Clients"}).json()
    project = leaver.post(f"{API}/projects", json={"name": "Follow-ups", "area_id": area["id"]}).json()
    secret = leaver.post(f"{API}/items", json={"title": "Call the supplier", "project_id": project["id"], "assignee_user_id": lid}).json()
    shared = leaver.post(f"{API}/items", json={"title": "Team thing", "visibility": "team"}).json()
    with core_db.transaction() as conn:
        conn.execute("UPDATE core_users SET is_active = 0 WHERE id = ?", (lid,))
        assert service.hide_private_for_in(conn, lid) == {"items": 1, "projects": 1, "areas": 1}
    assert leaver.get(f"{API}/items").status_code == 401
    for viewer in (admin, heir):
        assert titles(viewer.get(f"{API}/items").json()) == ["Team thing"]
        assert viewer.get(f"{API}/items/{secret['id']}").status_code == 404
        assert viewer.get(f"{API}/projects").json() == []
    assert heir.post(f"{API}/transfer", json={"from_user_id": lid, "to_user_id": hid}).status_code == 403
    since = heir.get(f"{API}/changes").json()["next_since_rev"]
    assert admin.post(f"{API}/transfer", json={"from_user_id": lid, "to_user_id": hid}).json() == {"items": 1, "projects": 1, "areas": 1}
    got = heir.get(f"{API}/items/{secret['id']}").json()
    assert (got["owner_user_id"], got["assignee_user_id"], got["project_name"], got["area_name"]) == (hid, hid, "Follow-ups", "Clients")
    assert heir.get(f"{API}/projects/{project['id']}").json()["open_count"] == 1
    feed = heir.get(f"{API}/changes", params={"since_rev": since}).json()
    assert ([t["id"] for t in feed["items"]], [p["id"] for p in feed["projects"]], [a["id"] for a in feed["areas"]]) == (
        [secret["id"]], [project["id"]], [area["id"]])
    assert admin.get(f"{API}/items/{secret['id']}").status_code == 404  # still private, now the heir's
    assert heir.get(f"{API}/items/{shared['id']}").json()["owner_user_id"] == lid  # team rows stay put
    assert admin.post(f"{API}/transfer", json={"from_user_id": hid, "to_user_id": lid}).status_code == 422  # inactive
    assert admin.post(f"{API}/transfer", json={"from_user_id": hid, "to_user_id": hid}).status_code == 422


# ── Record links, reset ───────────────────────────────────────────────────────


def test_a_merged_record_repoints_its_todos_and_a_deleted_one_unlinks_them(two):
    me = two[0]
    p1, p2 = _person(), _person()
    t = service.create_item(me, "Call Ada", entity_type="core.person", entity_id=p1)
    with core_db.transaction() as conn:
        entities.on_entity_merged_in(conn, "core.person", p2, p1)
    assert service.get_item(me, t["id"])["entity_id"] == p2
    with core_db.transaction() as conn:
        entities.delete_record_in(conn, "core.person", p2)
    after = service.get_item(me, t["id"])
    assert (after["entity_type"], after["entity_id"], after["title"]) == (None, None, "Call Ada")
    assert after["rev"] > t["rev"]
    with pytest.raises(Invalid, match="entity_type and entity_id are set together"):
        service.update_item(me, t["id"], {"entity_type": "core.person"})
    with pytest.raises(Invalid, match="entity: no such record"):
        service.update_item(me, t["id"], {"entity_type": "core.person", "entity_id": 999})
    with pytest.raises(NotFound):
        service.list_for_record(me, "core.person", 999)


def test_an_app_reset_leaves_sqlite_sequence_alone(login_as):
    member = login_as("member")
    old = member.post(f"{API}/items", json={"title": "old"}).json()
    member.post("/api/core/timeline", json={"entity_type": "todos.item", "entity_id": old["id"], "body": "a note"})
    since = member.get(f"{API}/changes").json()["next_since_rev"]

    def sequences():
        return {r["name"]: r["seq"] for r in core_db.rows("SELECT name, seq FROM sqlite_sequence WHERE name LIKE 'todos_%'")}

    before = sequences()
    with core_db.transaction() as conn:
        registry.reset_app_in(conn, "todos")
    after = sequences()  # untouched: ids keep climbing (the journal's climbs with the tombstones)
    assert after["todos_items"] == before["todos_items"] and after["todos_journal"] >= before["todos_journal"]
    assert core_db.one("SELECT count(*) AS n FROM core_timeline WHERE entity_type = 'todos.item'")["n"] == 0
    assert member.get(f"{API}/changes", params={"since_rev": since}).json()["reset"] is True  # nothing since
    new = member.post(f"{API}/items", json={"title": "new"}).json()
    assert new["id"] > old["id"] and new["rev"] > since
    assert member.get(f"{API}/items/{old['id']}").status_code == 404
    assert member.get("/api/core/timeline", params={"entity_type": "todos.item", "entity_id": new["id"]}).json() == []
    feed = member.get(f"{API}/changes", params={"since_rev": since}).json()
    assert feed["reset"] is True and [t["id"] for t in feed["items"]] == [new["id"]]
    assert member.get(f"{API}/changes", params={"since_rev": feed["next_since_rev"]}).json()["reset"] is False


# ── The published API and the tools ──────────────────────────────────────────


def test_the_published_api(app, make_user):
    admin, a, b = make_user("admin"), make_user(), make_user()
    person = _person()
    made = todos_api.create(a.id, "Send the quote", entity_type="core.person", entity_id=person, due_date="2026-09-01", notes="n")
    assert (made["owner_user_id"], made["visibility"], made["source"], made["status"]) == (a.id, "private", "app", "inbox")
    with pytest.raises(Forbidden):
        todos_api.create(a.id, "for b", owner_user_id=b.id)
    assert todos_api.create(a.id, "for b", owner_user_id=b.id, visibility="team")["owner_user_id"] == b.id
    assert todos_api.create(admin.id, "private for b", owner_user_id=b.id)["visibility"] == "private"
    assert todos_api.create(0, "From a job", visibility="team")["owner_user_id"] == 0  # the system principal
    with pytest.raises(Invalid, match="owner_user_id: no such active user"):
        todos_api.create(0, "private for nobody")
    assert titles(todos_api.list_for_record(a, "core.person", person)) == ["Send the quote"]
    assert todos_api.list_for_record(b, "core.person", person) == []
    with pytest.raises(NotFound):
        todos_api.complete(b.id, made["id"])
    assert todos_api.complete(a.id, made["id"])["status"] == "done"
    assert todos_api.list_for_record(a, "core.person", person) == []
    assert [t["status"] for t in todos_api.list_for_record(a, "core.person", person, include_done=True)] == ["done"]
    with core_db.transaction() as conn:
        assert todos_api.create_in(conn, a.id, "inside a transaction")["title"] == "inside a transaction"
        assert todos_api.list_for_record_in(conn, a, "core.person", person) == []


def test_tools_are_registered_scoped_and_act_as_the_user(two):
    a, b = two

    def ours(specs):
        return [t.name for t in specs if t.app == "todos"]

    reads = ["todos_list", "todos_today", "todos_review"]
    assert ours(tools.for_user(a)) == [*reads, "todos_create", "todos_update", "todos_complete"]
    assert ours(tools.for_source("job")) == reads
    create, update, complete = (tools.get(f"todos_{n}") for n in ("create", "update", "complete"))
    assert (create.revision, create.confirm_tier, create.targets({"title": "x"})) == ("0.1.0", "routine", [])
    with core_db.transaction() as conn:
        made = create.handler_in(conn, a, {"title": "From Whisk", "visibility": "team", "status": "next_action"})
    assert (made["source"], made["visibility"]) == ("agent", "team")
    assert update.targets({"id": made["id"], "title": "x"}) == complete.targets({"id": made["id"]}) == [("todos.item", made["id"])]
    assert update.hides_when({"id": 1, "visibility": "private"}) and update.hides_when({"id": 1, "owner_user_id": 2})
    assert not update.hides_when({"id": 1, "title": "x"})
    with core_db.transaction() as conn:
        assert update.handler_in(conn, b, {"id": made["id"], "star": True, "due_date": None})["star"] is True
        assert complete.handler_in(conn, b, {"id": made["id"]})["status"] == "done"
    assert titles(tools.get("todos_list").handler(b, {"status": "done", "unknown": 1})) == ["From Whisk"]
    assert tools.get("todos_today").handler(a, {}) == []
    assert tools.get("todos_review").handler(a, {})["completed_last_week"]["count"] == 1
    secret = service.create_item(a, "secret")
    with pytest.raises(NotFound):  # what the engine runs on every target before handler_in
        entities.authorize(b, core_db.get_conn(), *update.targets({"id": secret["id"]})[0], "write")


# ── The HTTP surface ──────────────────────────────────────────────────────────


def test_routes_shapes_and_status_codes(login_as):
    m = login_as("member")
    area = m.post(f"{API}/areas", json={"name": "Home", "visibility": "team"}).json()
    project = m.post(f"{API}/projects", json={"name": "Garden", "area_id": area["id"], "visibility": "team"}).json()
    item = m.post(f"{API}/items", json={"title": "Dig", "project_id": project["id"], "visibility": "team", "context": "@yard"}).json()
    assert set(area) == set(Area.model_fields) and set(project) == set(Project.model_fields) and set(item) == set(Item.model_fields)
    assert (item["project_name"], item["area_name"], item["effective_area_id"], item["source"]) == ("Garden", "Home", area["id"], "ui")
    assert m.get(f"{API}/items/{item['id']}").json() == item
    assert m.patch(f"{API}/items/{item['id']}", json={"status": "next_action", "star": True}).json()["star"] is True
    assert [t["id"] for t in m.get(f"{API}/today").json()] == [item["id"]]
    for body in ({"title": ""}, {"title": "x", "bogus": 1}, {"title": "x", "status": "soon"}, {"title": "x", "due_date": "soon"}):
        assert m.post(f"{API}/items", json=body).status_code == 422, body
    assert m.patch(f"{API}/items/999", json={"title": "x"}).status_code == 404
    assert m.get(f"{API}/items", params={"status": "soon"}).status_code == 422

    other = m.post(f"{API}/items", json={"title": "Weed", "context": "yard"}).json()
    assert m.post(f"{API}/contexts/rename", json={"old": "@yard", "new": "yard"}).status_code == 409
    assert m.post(f"{API}/contexts/rename", json={"old": "@yard", "new": "yard", "merge": True}).json() == {
        "old": "@yard", "new": "yard", "updated": 1, "merged": True}
    assert m.post(f"{API}/contexts/rename", json={"old": "@nope", "new": "x"}).status_code == 404
    assert m.post(f"{API}/items/bulk", json={"ids": [item["id"], other["id"]], "fields": {"status": "done"}}).json() == {
        "updated": sorted([item["id"], other["id"]]), "not_found": []}
    assert m.post(f"{API}/items/bulk", json={"ids": [item["id"]], "fields": {"colour": "red"}}).status_code == 422
    assert m.post(f"{API}/items/{other['id']}/complete").json()["status"] == "done"

    review = m.get(f"{API}/review").json()
    assert review["completed_last_week"]["count"] == 2 and review["areas"][0]["id"] == area["id"]
    assert m.post(f"{API}/review/done").json()["days_since_review"] == 0
    f = m.get(f"{API}/filters").json()
    assert (f["contexts"], f["status_counts"]["done"], f["tz"]) == (["yard"], 2, "UTC")
    assert m.get(f"{API}/badge").json() == {"count": 0, "label": "Inbox"}
    assert m.get(f"{API}/changes", params={"since_rev": -1}).status_code == 422

    assert m.get(f"{API}/projects", params={"area_id": area["id"]}).json()[0]["open_count"] == 0
    assert m.patch(f"{API}/projects/{project['id']}", json={"status": "completed"}).json()["status"] == "completed"
    assert m.patch(f"{API}/projects/{project['id']}", json={"status": "paused"}).status_code == 422
    assert m.get(f"{API}/areas", params={"status": "active"}).json()[0]["name"] == "Home"
    assert m.patch(f"{API}/areas/{area['id']}", json={"name": "House"}).json()["name"] == "House"
    assert m.patch(f"{API}/areas/{area['id']}", json={}).status_code == 422
    assert m.delete(f"{API}/projects/{project['id']}").json() == {"deleted": project["id"]}
    assert m.get(f"{API}/items/{item['id']}").json()["project_id"] is None
    assert m.delete(f"{API}/areas/{area['id']}").json() == {"deleted": area["id"]}
    assert m.get(f"{API}/areas/{area['id']}").status_code == 404
    assert m.delete(f"{API}/items/{item['id']}").json() == {"deleted": item["id"]}
    assert m.get(f"{API}/items/{item['id']}").status_code == 404
