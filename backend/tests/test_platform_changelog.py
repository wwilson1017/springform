from backend.apps.example import service as widgets
from backend.apps.example.models import WidgetIn, WidgetPatch
from backend.core import db as core_db, entities
from backend.core.platform import service


def _changes(client, **params) -> list[dict]:
    r = client.get("/api/core/changelog", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_rows_are_filtered_by_read_access_and_gone_rows_go_only_to_their_writer(login_as):
    admin, owner, other = login_as("admin"), login_as("member"), login_as("member")
    secret = widgets.create_widget(owner.principal, WidgetIn(name="Secret", is_private=True))
    public = widgets.create_widget(owner.principal, WidgetIn(name="Public"))
    widgets.update_widget(owner.principal, secret["id"], WidgetPatch(color="red"))
    widgets.update_widget(owner.principal, public["id"], WidgetPatch(color="blue"))

    row = _changes(other)[0]
    assert row == {
        "id": row["id"], "at": row["at"], "user": {"id": owner.user["id"], "name": owner.user["name"]},
        "app": "example", "entity_type": "example.widget", "entity_id": public["id"], "title": "Public",
        "url": f"/example/widgets/{public['id']}", "field": "color", "old": "teal", "new": "blue",
        "reason": None, "deleted_at": None,
    }  # fmt: skip
    assert [r["entity_id"] for r in _changes(other)] == [public["id"]]  # another member's private widget: hidden
    assert [r["entity_id"] for r in _changes(admin)] == [public["id"]]  # admins cannot read it either
    assert [(r["entity_id"], r["title"]) for r in _changes(owner)] == [
        (public["id"], "Public"),
        (secret["id"], "Secret"),
    ]

    # A deleted private record's history stays with the person who wrote it; admins get no extra access.
    with core_db.transaction() as conn:
        entities.delete_record_in(conn, "example.widget", secret["id"])
    gone = [r for r in _changes(owner) if r["entity_id"] == secret["id"]]
    assert len(gone) == 1 and gone[0]["deleted_at"] and gone[0]["title"] is None and gone[0]["url"] is None
    assert gone[0]["new"] == "red"
    assert [r["entity_id"] for r in _changes(admin)] == [public["id"]]
    assert [r["entity_id"] for r in _changes(other)] == [public["id"]]

    # Two writers on one record: after the delete each sees only their own rows.
    widgets.update_widget(admin.principal, public["id"], WidgetPatch(color="gold"))
    with core_db.transaction() as conn:
        entities.delete_record_in(conn, "example.widget", public["id"])
    assert [(r["entity_id"], r["new"]) for r in _changes(admin)] == [(public["id"], "gold")]
    assert [(r["entity_id"], r["new"]) for r in _changes(owner)] == [(public["id"], "blue"), (secret["id"], "red")]
    assert _changes(other) == []

    # A row whose entity type is no longer installed counts as gone too.
    with core_db.transaction() as conn:
        conn.execute(
            """INSERT INTO core_change_log (at, user_id, app, entity, entity_id, field, old, new)
               VALUES ('2026-10-24T00:00:00Z', ?, 'gone', 'gone.thing', 1, 'name', '"a"', '"b"')""",
            (admin.user["id"],),
        )
    orphan = _changes(admin)[0]
    assert (orphan["entity_type"], orphan["deleted_at"], orphan["title"], orphan["url"]) == (
        "gone.thing",
        None,
        None,
        None,
    )
    assert all(r["entity_type"] != "gone.thing" for r in _changes(owner))


def test_filters_and_cursor_pagination_fill_pages_past_hidden_rows(login_as, monkeypatch):
    admin, owner, other = login_as("admin"), login_as("member"), login_as("member")
    secret = widgets.create_widget(owner.principal, WidgetIn(name="Secret", is_private=True))
    public = widgets.create_widget(owner.principal, WidgetIn(name="Public"))
    for i in range(5):  # interleave hidden and visible rows
        widgets.update_widget(owner.principal, secret["id"], WidgetPatch(name=f"Secret {i}"))
        widgets.update_widget(owner.principal, public["id"], WidgetPatch(name=f"Public {i}"))
    widgets.update_widget(admin.principal, public["id"], WidgetPatch(color="gold"))
    monkeypatch.setattr(service, "_SCAN_BATCH", 3)  # force several scan batches per page

    everything = _changes(other)
    assert len(everything) == 6 and all(r["entity_id"] == public["id"] for r in everything)
    assert [r["id"] for r in everything] == sorted((r["id"] for r in everything), reverse=True)
    assert {r["title"] for r in everything} == {"Public 4"}  # titles are current

    pages, before = [], None
    while True:
        page = _changes(other, limit=2, **({"before": before} if before else {}))
        if not page:
            break
        assert len(page) == 2
        pages.append(page)
        before = page[-1]["id"]
    assert [r["id"] for p in pages for r in p] == [r["id"] for r in everything]

    assert [r["field"] for r in _changes(other, user_id=admin.user["id"])] == ["color"]
    assert _changes(other, app="core") == []
    assert len(_changes(owner, entity_type="example.widget", entity_id=secret["id"])) == 5
    assert _changes(other, entity_type="example.widget", entity_id=secret["id"]) == []
