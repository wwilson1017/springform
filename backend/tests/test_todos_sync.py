"""The change feed: what `changes` reports to each person, the team rev and per-person revs, and
tombstones for rows that leave someone's view. Ported in part from todo-gtd's test_changes.py."""

import pytest

from backend.apps.todos import service
from backend.core import db as core_db
from backend.core.errors import Invalid


def ids(out) -> dict:
    return {kind: [row["id"] for row in out[kind]] for kind in ("items", "projects", "areas")}


def gone(out) -> dict:
    return {kind: [row["id"] for row in out["removed"][kind]] for kind in ("items", "projects", "areas")}


def head(user) -> int:
    return service.changes(user)["next_since_rev"]


NOTHING = {"items": [], "projects": [], "areas": []}


@pytest.fixture
def two(app, make_user):
    return make_user(), make_user()


def test_a_sync_sees_each_addition_and_edit_once(two):
    me = two[0]
    start = service.changes(me)
    assert (start["changed"], start["more"], start["reset"], start["next_since_rev"]) == (False, False, False, 0)
    assert ids(start) == NOTHING and gone(start) == NOTHING

    area = service.create_area(me, "Home")
    project = service.create_project(me, "Fence", area_id=area["id"])
    a = service.create_item(me, "Buy paint", project_id=project["id"])
    b = service.create_item(me, "Call Sam")
    first = service.changes(me, start["next_since_rev"])
    assert first["changed"] is True
    assert ids(first) == {"items": [a["id"], b["id"]], "projects": [project["id"]], "areas": [area["id"]]}
    assert first["items"][0]["project_name"] == "Fence" and first["items"][0]["tags"] == []
    assert first["projects"][0]["open_count"] == 1

    again = service.changes(me, first["next_since_rev"])  # nothing since: the cheap check
    assert again["changed"] is False and again["next_since_rev"] == first["next_since_rev"]

    edited = service.update_item(me, b["id"], {"status": "dropped"})
    service.update_container(me, "project", project["id"], {"outcome": "A painted fence"})
    second = service.changes(me, first["next_since_rev"])
    assert ids(second) == {"items": [b["id"]], "projects": [project["id"]], "areas": []}
    assert second["items"][0]["status"] == "dropped"  # an archive is an edit; nothing vanishes
    assert second["items"][0]["rev"] == edited["rev"] > a["rev"]  # a write hands back its rev
    assert second["next_since_rev"] == head(me)


def test_bulk_edits_and_a_repeat_spawn_are_all_reported(two):
    me = two[0]
    a, b = (service.create_item(me, t, status="next_action") for t in ("a", "b"))
    routine = service.create_item(me, "Water plants", repeat="daily", due_date="2026-10-11")
    since = head(me)
    service.bulk_update(me, [a["id"], b["id"]], {"star": True})
    service.update_item(me, routine["id"], {"status": "done"})
    out = service.changes(me, since)
    assert ids(out)["items"][:3] == [a["id"], b["id"], routine["id"]]
    assert len(out["items"]) == 4 and out["items"][3]["title"] == "Water plants" and out["items"][3]["status"] == "inbox"


def test_each_caller_keeps_its_own_place_and_paging_has_no_gap_or_repeat(two):
    me = two[0]
    made = []
    for n in range(3):
        made.append(("items", service.create_item(me, f"t{n}")["id"]))
        made.append(("projects", service.create_project(me, f"p{n}")["id"]))
    made.append(("areas", service.create_area(me, "Home")["id"]))
    late = service.changes(me, limit=1)["next_since_rev"]
    assert ids(service.changes(me, late)) == ids(service.changes(me, late))  # reading moves nothing
    seen, since, calls = [], 0, 0
    while True:
        out = service.changes(me, since, limit=2)
        page = sorted((row["rev"], kind, row["id"]) for kind in ("items", "projects", "areas") for row in out[kind])
        seen += [(kind, row_id) for _, kind, row_id in page]
        since, calls = out["next_since_rev"], calls + 1
        if not out["more"]:
            break
        assert len(page) == 2
    assert seen == made and calls == 4 and since == head(me)


def test_bad_cursors(two):
    me = two[0]
    todo = service.create_item(me, "a")
    out = service.changes(me, head(me) + 50)  # ahead of this database: it was put back
    assert out["reset"] is True and ids(out)["items"] == [todo["id"]] and out["next_since_rev"] == head(me)
    for args in ({"since_rev": -1}, {"limit": 0}, {"limit": 501}):
        with pytest.raises(Invalid):
            service.changes(me, **args)


def test_a_team_edit_advances_every_members_feed_and_a_private_one_only_its_owners(two):
    a, b = two
    team = service.create_item(a, "Restock", visibility="team")
    assert ids(service.changes(b))["items"] == [team["id"]]
    a_since, b_since = head(a), head(b)

    service.create_item(a, "a's own")  # private: b's feed does not move, so b cannot even tell
    assert head(b) == b_since and head(a) > a_since
    service.update_item(b, team["id"], {"star": True})  # team: both move, and the same rev
    team_rev = core_db.one("SELECT rev FROM todos_sync WHERE user_id = 0")["rev"]
    assert head(b) == team_rev == service.get_item(a, team["id"])["rev"]
    assert ids(service.changes(b, b_since))["items"] == [team["id"]]
    assert ids(service.changes(a, a_since))["items"][-1] == team["id"]
    assert len(ids(service.changes(a, a_since))["items"]) == 2


def test_a_todo_that_goes_private_leaves_a_tombstone_in_everyone_elses_feed(two):
    a, b = two
    t = service.create_item(a, "Restock", visibility="team")
    a_since, b_since = head(a), head(b)
    private = service.update_item(a, t["id"], {"visibility": "private"})
    out = service.changes(b, b_since)
    assert ids(out) == NOTHING and out["removed"]["items"] == [{"id": t["id"], "rev": out["next_since_rev"]}]
    mine = service.changes(a, a_since)
    assert ids(mine)["items"] == [t["id"]] and gone(mine) == NOTHING and mine["items"][0]["rev"] == private["rev"]
    # Back to team: an upsert again, and no tombstone for a row b can see.
    b_since = head(b)
    service.update_item(a, t["id"], {"visibility": "team"})
    back = service.changes(b, b_since)
    assert ids(back)["items"] == [t["id"]] and gone(back) == NOTHING
    assert gone(service.changes(b)) == NOTHING  # a full sync shows only what is there now


def test_a_handed_over_todo_leaves_its_old_owner_and_reaches_its_new_one(two):
    a, b = two
    t = service.create_item(a, "Private errand")
    a_since, b_since = head(a), head(b)
    service.update_item(a, t["id"], {"owner_user_id": b.id})
    assert gone(service.changes(a, a_since))["items"] == [t["id"]]
    assert ids(service.changes(b, b_since))["items"] == [t["id"]]


def test_deletes_leave_tombstones_for_the_rows_audience(two):
    a, b = two
    team, own = service.create_item(a, "team", visibility="team"), service.create_item(a, "own")
    project = service.create_project(a, "Shared", visibility="team")
    a_since, b_since = head(a), head(b)
    service.delete_item(a, team["id"])
    service.delete_item(a, own["id"])
    service.delete_container(a, "project", project["id"])
    assert gone(service.changes(a, a_since)) == {"items": [team["id"], own["id"]], "projects": [project["id"]], "areas": []}
    assert gone(service.changes(b, b_since)) == {"items": [team["id"]], "projects": [project["id"]], "areas": []}


def test_a_project_going_private_and_an_admins_feed(app, make_user):
    admin, member = make_user("admin"), make_user()
    project = service.create_project(member, "Lease", visibility="team")
    secret = service.create_item(member, "member's own")
    service.create_item(admin, "admin's own")
    feed = service.changes(admin)
    assert ids(feed)["items"] == [i["id"] for i in service.list_items(admin)] and secret["id"] not in ids(feed)["items"]
    since = head(admin)
    service.update_container(member, "project", project["id"], {"visibility": "private"})
    assert gone(service.changes(admin, since))["projects"] == [project["id"]]


def test_edits_over_http_reach_the_other_members_feed(login_as):
    a, b = login_as("member"), login_as("member")
    start = b.get("/api/todos/changes").json()["next_since_rev"]
    todo = a.post("/api/todos/items", json={"title": "Call the plumber", "visibility": "team"}).json()
    added = b.get("/api/todos/changes", params={"since_rev": start}).json()
    assert [t["id"] for t in added["items"]] == [todo["id"]]
    a.patch(f"/api/todos/items/{todo['id']}", json={"tags": ["errand"]})
    out = b.get("/api/todos/changes", params={"since_rev": added["next_since_rev"]}).json()
    assert out["items"][0]["tags"] == ["errand"] and out["since_rev"] == added["next_since_rev"]
    a.patch(f"/api/todos/items/{todo['id']}", json={"visibility": "private"})
    later = b.get("/api/todos/changes", params={"since_rev": out["next_since_rev"]}).json()
    assert later["items"] == [] and [r["id"] for r in later["removed"]["items"]] == [todo["id"]]
    assert b.get("/api/todos/changes", params={"since_rev": later["next_since_rev"]}).json()["changed"] is False
