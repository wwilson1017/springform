from backend.core import db as core_db
from backend.core.timeline import api as timeline


def _widget(client, **body) -> dict:
    r = client.post("/api/example/widgets", json={"name": "Gear", **body})
    assert r.status_code == 200, r.text
    return r.json()


def test_note_round_trip(login_as, freeze):
    freeze("2026-11-02T09:00:00Z")
    member = login_as("member")
    w = _widget(member)
    posted = member.post("/api/core/timeline", json={"entity_type": "example.widget", "entity_id": w["id"], "body": "  hello  "})
    assert posted.status_code == 200
    entry = posted.json()
    assert entry == {
        "id": entry["id"], "kind": "note", "body": "hello", "changes": None,
        "author": {"id": member.user["id"], "name": member.user["name"]}, "created_at": "2026-11-02T09:00:00Z",
    }
    listed = member.get("/api/core/timeline", params={"entity_type": "example.widget", "entity_id": w["id"]})
    assert listed.json() == [entry]


def test_comment_kind_and_before_paging(login_as):
    member = login_as("member")
    w = _widget(member)
    q = {"entity_type": "example.widget", "entity_id": w["id"]}
    ids = [member.post("/api/core/timeline", json={**q, "body": f"n{i}"}).json()["id"] for i in range(3)]
    assert member.post("/api/core/timeline", json={**q, "body": "c", "kind": "comment"}).json()["kind"] == "comment"
    assert member.post("/api/core/timeline", json={**q, "body": "x", "kind": "system"}).status_code == 422
    page = member.get("/api/core/timeline", params={**q, "limit": 2}).json()
    assert [e["kind"] for e in page] == ["comment", "note"] and page[1]["id"] == ids[2]
    assert [e["id"] for e in member.get("/api/core/timeline", params={**q, "before": page[-1]["id"]}).json()] == [ids[1], ids[0]]
    assert member.get("/api/core/timeline", params={**q, "limit": 201}).status_code == 422


def test_apps_write_system_rows_through_the_api(login_as):
    member = login_as("member")
    w = _widget(member)
    with core_db.transaction() as conn:
        timeline.add_system_in(conn, "example.widget", w["id"], "Merged widget #9 into this widget.")
    [entry] = member.get("/api/core/timeline", params={"entity_type": "example.widget", "entity_id": w["id"]}).json()
    assert (entry["kind"], entry["body"], entry["author"]["id"]) == ("system", "Merged widget #9 into this widget.", 0)


def test_note_validation_and_missing_records(login_as):
    member = login_as("member")
    w = _widget(member)
    post = lambda **b: member.post("/api/core/timeline", json={"entity_type": "example.widget", "entity_id": w["id"], "body": "x", **b})  # noqa: E731
    assert post(body="   ").status_code == 422
    assert post(entity_id=9999).status_code == 404
    assert post(entity_type="nope.thing").status_code == 404
    assert member.get("/api/core/timeline", params={"entity_type": "example.widget"}).status_code == 422


def test_record_changes_writes_one_timeline_row_and_change_log_rows(login_as):
    member = login_as("member")
    w = _widget(member, color="red")
    assert member.patch(f"/api/example/widgets/{w['id']}", json={"name": "Cog", "color": "blue"}).status_code == 200
    entries = member.get("/api/core/timeline", params={"entity_type": "example.widget", "entity_id": w["id"]}).json()
    assert len(entries) == 1 and entries[0]["kind"] == "field_change"
    assert entries[0]["changes"] == [{"field": "name", "old": "Gear", "new": "Cog"}, {"field": "color", "old": "red", "new": "blue"}]
    log = core_db.rows("SELECT app, entity, entity_id, field, old, new, user_id FROM core_change_log ORDER BY id")
    assert log == [
        {"app": "example", "entity": "example.widget", "entity_id": w["id"], "field": "name", "old": '"Gear"', "new": '"Cog"', "user_id": member.user["id"]},
        {"app": "example", "entity": "example.widget", "entity_id": w["id"], "field": "color", "old": '"red"', "new": '"blue"', "user_id": member.user["id"]},
    ]


def test_nothing_changed_writes_nothing(app, make_user):
    with core_db.transaction() as conn:
        assert timeline.record_changes_in(conn, "example.widget", 1, {"name": "a", "updated_at": "1"}, {"name": "a", "updated_at": "2"}, None) is None
    assert core_db.one("SELECT count(*) AS n FROM core_timeline")["n"] == 0
