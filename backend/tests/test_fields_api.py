"""Custom fields: admin-managed definitions, typed values behind entities.authorize, the
timeline/change-log trail, and the delete and merge hooks."""

import pytest
from fastapi.testclient import TestClient

from backend.apps.example import fields as example_fields
from backend.core import db as core_db, entities, scheduler
from backend.core.errors import Invalid, NotFound
from backend.core.fields import service as fields
from backend.core.fields.api import FieldSpec

DEFS = "/api/core/fields/definitions"
VALUES = "/api/core/fields/values"
W = "example.widget"


def _widget(client, **body) -> int:
    r = client.post("/api/example/widgets", json={"name": "Gear", **body})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _define(admin, **body) -> dict:
    r = admin.post(DEFS, json={"entity_type": W, **body})
    assert r.status_code == 200, r.text
    return r.json()


def _put(client, widget_id, values):
    return client.put(VALUES, json={"entity_type": W, "entity_id": widget_id, "values": values})


def test_definitions_crud_archive_and_restore(login_as):
    admin, member = login_as("admin"), login_as("member")
    colour = _define(admin, label="Paint colour", type="select", options=["red", "blue"], required=True)
    assert colour == {
        "id": colour["id"],
        "entity_type": W,
        "key": "paint_colour",
        "label": "Paint colour",
        "type": "select",
        "options": ["red", "blue"],
        "required": True,
        "position": 10,
        "archived_at": None,
        "owner_app": None,
        "retired_at": None,
        "created_at": colour["created_at"],
        "updated_at": colour["updated_at"],
    }
    size = _define(admin, label="Size", key="size_mm", type="number")
    assert size["position"] == 20 and size["options"] is None and size["required"] is False
    assert [d["key"] for d in member.get(DEFS, params={"entity_type": W}).json()] == ["paint_colour", "size_mm"]

    assert member.post(DEFS, json={"entity_type": W, "label": "Mine", "type": "text"}).json() == {
        "detail": "admin_only"
    }
    assert member.patch(f"{DEFS}/{size['id']}", json={"label": "x"}).status_code == 403
    assert member.delete(f"{DEFS}/{size['id']}").status_code == 403
    assert (
        admin.post(DEFS, json={"entity_type": W, "label": "Size", "key": "size_mm", "type": "text"}).status_code == 409
    )
    assert admin.post(DEFS, json={"entity_type": "nope.thing", "label": "X", "type": "text"}).status_code == 404
    for bad in (
        {"label": "X", "type": "colour"},  # unknown type
        {"label": "X", "type": "select"},  # select needs options
        {"label": "X", "type": "select", "options": ["a", "a"]},
        {"label": "X", "type": "text", "options": ["a"]},  # only (multi)select has options
        {"label": "  ", "type": "text"},
        {"label": "9 lives", "type": "text"},  # derived key must start with a letter
        {"label": "X", "key": "Bad Key", "type": "text"},
        {"label": "X", "key": "ok\n", "type": "text"},
    ):
        assert admin.post(DEFS, json={"entity_type": W, **bad}).status_code == 422, bad

    patched = admin.patch(
        f"{DEFS}/{colour['id']}", json={"label": "Colour", "options": ["red", "blue", "teal"], "position": 30}
    )
    assert patched.status_code == 200
    assert {k: patched.json()[k] for k in ("key", "label", "options", "position", "required")} == {
        "key": "paint_colour",
        "label": "Colour",
        "options": ["red", "blue", "teal"],
        "position": 30,
        "required": True,
    }
    assert admin.patch(f"{DEFS}/{colour['id']}", json={"type": "text"}).status_code == 422  # type never changes
    assert admin.patch(f"{DEFS}/{colour['id']}", json={"options": []}).status_code == 422
    assert admin.patch(f"{DEFS}/999", json={"label": "x"}).status_code == 404

    w = _widget(member)
    assert _put(member, w, {"paint_colour": "teal", "size_mm": 4}).status_code == 200
    assert admin.delete(f"{DEFS}/{colour['id']}").status_code == 204  # archive
    assert [d["key"] for d in member.get(DEFS, params={"entity_type": W}).json()] == ["size_mm"]
    archived = admin.get(DEFS, params={"entity_type": W, "include_archived": True}).json()
    assert [d["key"] for d in archived] == ["size_mm", "paint_colour"] and archived[1]["archived_at"]
    assert member.get(VALUES, params={"entity_type": W, "entity_id": w}).json() == {"size_mm": 4}
    assert _put(member, w, {"paint_colour": "red"}).json() == {"detail": "unknown field: paint_colour"}
    assert (
        admin.post(DEFS, json={"entity_type": W, "label": "Paint colour", "type": "text"}).status_code == 409
    )  # key stays taken

    assert admin.patch(f"{DEFS}/{colour['id']}", json={"archived": False}).json()["archived_at"] is None
    assert member.get(VALUES, params={"entity_type": W, "entity_id": w}).json() == {
        "size_mm": 4,
        "paint_colour": "teal",
    }


CASES = [  # type, extra definition fields, good values, bad values
    ("text", {}, ["hello", "x" * 10_000], [5, True, ["a"], "x" * 10_001]),
    ("number", {}, [3, -2.5, 0], ["3", True, {"n": 3}]),
    ("boolean", {}, [True, False], [1, "true", 0]),
    ("date", {}, ["2026-11-02"], ["2026-02-30", "02/11/2026", "2026-11-02T09:00:00Z", "2026-11-02\n", 20261102]),
    ("select", {"options": ["s", "m", "l"]}, ["m"], ["xl", ["m"], 1]),
    ("multiselect", {"options": ["s", "m", "l"]}, [["l", "s"], ["m"]], [["s", "s"], ["xl"], "s", [1]]),
    (
        "url",
        {},
        ["https://example.com/a?b=1", "http://localhost:8000"],
        ["example.com", "ftp://x.y", "https://", "https://a b", "https://a.b\n"],
    ),
]


@pytest.mark.parametrize(("field_type", "extra", "good", "bad"), CASES, ids=[c[0] for c in CASES])
def test_value_validation_per_type(login_as, field_type, extra, good, bad):
    admin, member = login_as("admin"), login_as("member")
    _define(admin, label="F", key="f", type=field_type, **extra)
    w = _widget(member)
    for value in good:
        r = _put(member, w, {"f": value})
        assert r.status_code == 200 and r.json() == {"f": value}, (value, r.text)
    for value in bad:
        r = _put(member, w, {"f": value})
        assert r.status_code == 422 and r.json()["detail"].startswith("f: expected"), (value, r.text)
    assert member.get(VALUES, params={"entity_type": W, "entity_id": w}).json() == {"f": good[-1]}
    for empty in (None, "", []):
        _put(member, w, {"f": good[0]})
        assert _put(member, w, {"f": empty}).json() == {}  # cleared: no row
    assert core_db.one("SELECT count(*) AS n FROM core_field_values")["n"] == 0
    if field_type == "number":  # JSON has no Infinity or NaN; Python callers are refused too
        for value in (float("inf"), float("nan")):
            with pytest.raises(Invalid, match="f: expected a number"):
                fields.set_values(member.principal, W, w, {"f": value})


def test_user_values_must_be_active_people(login_as, make_user):
    admin, member = login_as("admin"), login_as("member")
    _define(admin, label="Owner", type="user")
    w = _widget(member)
    gone = make_user("member")
    with core_db.transaction() as conn:
        conn.execute("UPDATE core_users SET is_active = 0 WHERE id = ?", (gone.id,))
    assert _put(member, w, {"owner": admin.user["id"]}).json() == {"owner": admin.user["id"]}
    for bad in (gone.id, 0, 9999, str(admin.user["id"])):  # deactivated, the system principal, missing, a string
        assert _put(member, w, {"owner": bad}).status_code == 422, bad


def test_values_follow_the_record_authorization(login_as):
    admin, owner, other = login_as("admin"), login_as("member"), login_as("member")
    _define(admin, label="Note", type="text")
    secret, public = _widget(owner, is_private=True), _widget(owner)
    assert _put(owner, secret, {"note": "mine"}).status_code == 200

    q = {"entity_type": W, "entity_id": secret}
    assert other.get(VALUES, params=q).status_code == 404  # private: not even its existence
    assert _put(other, secret, {"note": "x"}).status_code == 404
    assert other.get(VALUES, params={**q, "entity_id": public}).status_code == 200
    assert _put(other, public, {"note": "x"}).status_code == 403  # readable, not writable
    assert _put(admin, public, {"note": "admin"}).status_code == 200
    assert other.get(VALUES, params={"entity_type": W, "entity_id": 999}).status_code == 404
    assert other.get(VALUES, params={"entity_type": "nope.thing", "entity_id": 1}).status_code == 404
    assert owner.get(VALUES, params=q).json() == {"note": "mine"}
    with pytest.raises(NotFound):
        fields.values_for(other.principal, W, secret)


def test_a_change_writes_one_timeline_row_and_change_log_rows(login_as):
    admin, member = login_as("admin"), login_as("member")
    _define(admin, label="Colour", type="text")
    _define(admin, label="Size", type="number")
    w = _widget(member)
    timeline_q = {"entity_type": W, "entity_id": w}

    assert _put(member, w, {"colour": "red", "size": 3}).status_code == 200
    entries = member.get("/api/core/timeline", params=timeline_q).json()
    assert len(entries) == 1 and entries[0]["kind"] == "field_change"
    assert entries[0]["changes"] == [
        {"field": "field.colour", "old": None, "new": "red"},
        {"field": "field.size", "old": None, "new": 3},
    ]
    assert entries[0]["author"]["id"] == member.user["id"]

    _put(member, w, {"colour": "red", "size": None})  # colour unchanged, size cleared
    entries = member.get("/api/core/timeline", params=timeline_q).json()
    assert len(entries) == 2 and entries[0]["changes"] == [{"field": "field.size", "old": 3, "new": None}]
    log = core_db.rows("SELECT entity, entity_id, field, old, new, user_id FROM core_change_log ORDER BY id")
    assert [(r["field"], r["old"], r["new"]) for r in log] == [
        ("field.colour", "null", '"red"'),
        ("field.size", "null", "3"),
        ("field.size", "3", "null"),
    ]
    assert {(r["entity"], r["entity_id"], r["user_id"]) for r in log} == {(W, w, member.user["id"])}

    _put(member, w, {"colour": "red"})  # nothing changed: no new rows
    assert len(member.get("/api/core/timeline", params=timeline_q).json()) == 2

    assert _put(member, w, {"colour": "blue", "size": "big"}).status_code == 422  # all or nothing
    assert member.get(VALUES, params=timeline_q).json() == {"colour": "red"}


def test_entity_delete_removes_values(login_as):
    admin, member = login_as("admin"), login_as("member")
    _define(admin, label="Colour", type="text")
    gone, kept = _widget(member), _widget(member)
    _put(member, gone, {"colour": "red"})
    _put(member, kept, {"colour": "blue"})
    with core_db.transaction() as conn:
        entities.delete_record_in(conn, W, gone)
    assert core_db.rows("SELECT entity_id, value FROM core_field_values") == [{"entity_id": kept, "value": '"blue"'}]


def test_merge_keeps_the_targets_non_empty_values_else_the_sources(login_as):
    admin, member = login_as("admin"), login_as("member")
    for key in ("a", "b", "c", "d"):
        _define(admin, label=key.upper(), type="text")
    target, source, bystander = _widget(member), _widget(member), _widget(member)
    _put(member, target, {"a": "target a", "b": "target b"})
    _put(member, source, {"a": "source a", "c": "source c"})
    _put(member, bystander, {"d": "untouched"})
    with core_db.transaction() as conn:
        entities.on_entity_merged_in(conn, W, target, source)
    assert fields.values_for(member.principal, W, target) == {"a": "target a", "b": "target b", "c": "source c"}
    assert fields.values_for(member.principal, W, source) == {}
    assert fields.values_for(member.principal, W, bystander) == {"d": "untouched"}


def test_entity_types_lists_the_registry_for_the_definition_picker(login_as):
    types = login_as("member").get("/api/core/fields/entity-types").json()
    assert {"type": W, "label": "Widget", "label_plural": "Widgets"} in types
    assert {"type": "core.person", "label": "Person", "label_plural": "People"} in types
    assert [t["type"] for t in types] == [e.type for e in entities.all_entities()]


P = "core.person"
TIER = FieldSpec(P, "example_tier", "Tier", "select", options=("Gold", "Silver"))


def _sync(declared) -> int:
    """Run the boot reconcile; returns how many rows it changed."""
    with core_db.transaction() as conn:
        before = conn.total_changes
        fields.sync_declared_in(conn, declared)
        return conn.total_changes - before


def _row(key, entity_type=P) -> dict:
    return core_db.rows("SELECT * FROM core_field_definitions WHERE entity_type = ? AND key = ?", (entity_type, key))[0]


def test_declared_fields_are_created_kept_retired_and_restored(login_as, freeze):
    admin, member = login_as("admin"), login_as("member")
    person = member.post("/api/core/contacts/people", json={"name": "Ada Example"}).json()["id"]
    freeze("2026-11-02T09:00:00Z")
    _sync({"example": [TIER]})
    row = _row("example_tier")
    assert (row["owner_app"], row["retired_at"], row["archived_at"], row["label"]) == ("example", None, None, "Tier")
    listed = admin.get(DEFS, params={"entity_type": P}).json()
    assert [(d["key"], d["owner_app"], d["retired_at"]) for d in listed] == [("example_tier", "example", None)]
    put = member.put(VALUES, json={"entity_type": P, "entity_id": person, "values": {"example_tier": "Gold"}})
    assert put.json() == {"example_tier": "Gold"}

    freeze("2026-11-03T09:00:00Z")  # a restart writes nothing
    assert _sync({"example": [TIER]}) == 0 and _row("example_tier") == row
    _sync({"example": [FieldSpec(P, "example_tier", "Level", "select", options=("Gold", "Silver", "Bronze"))]})
    changed = _row("example_tier")
    assert (changed["label"], changed["position"], changed["updated_at"]) == ("Level", 10, "2026-11-03T09:00:00Z")

    # The admin may reorder and hide an app's field, not relabel it.
    tier = changed["id"]
    for body in ({"label": "x"}, {"required": True}, {"options": ["a"]}):
        r = admin.patch(f"{DEFS}/{tier}", json=body)
        assert (r.status_code, r.json()) == (403, {"detail": "app_owned"})
    assert admin.patch(f"{DEFS}/{tier}", json={"position": 5}).json()["position"] == 5
    assert admin.patch(f"{DEFS}/{tier}", json={"archived": True}).json()["archived_at"]
    _sync({"example": [TIER]})
    assert _row("example_tier")["archived_at"] and _row("example_tier")["position"] == 5  # boot keeps both
    assert admin.patch(f"{DEFS}/{tier}", json={"archived": False}).json()["archived_at"] is None

    freeze("2026-11-04T09:00:00Z")  # the app stops declaring it: archived and retired, value kept
    _sync({"example": []})
    retired = _row("example_tier")
    assert retired["archived_at"] == retired["retired_at"] == "2026-11-04T09:00:00Z"
    assert member.get(VALUES, params={"entity_type": P, "entity_id": person}).json() == {}
    assert core_db.rows("SELECT value FROM core_field_values WHERE definition_id = ?", (tier,)) == [{"value": '"Gold"'}]
    r = admin.patch(f"{DEFS}/{tier}", json={"archived": False})
    assert (r.status_code, r.json()) == (409, {"detail": "retired_by_app"})

    _sync({"example": [TIER]})  # declared again: back, with its value
    assert (_row("example_tier")["archived_at"], _row("example_tier")["retired_at"]) == (None, None)
    assert member.get(VALUES, params={"entity_type": P, "entity_id": person}).json() == {"example_tier": "Gold"}

    # Hidden by the admin, then retired, then declared again: it stays hidden.
    admin.patch(f"{DEFS}/{tier}", json={"archived": True})
    freeze("2026-11-05T09:00:00Z")
    _sync({})  # the app is gone altogether
    assert _row("example_tier")["retired_at"] == "2026-11-05T09:00:00Z"
    _sync({"example": [TIER]})
    assert _row("example_tier")["archived_at"] == "2026-11-04T09:00:00Z" and _row("example_tier")["retired_at"] is None

    with pytest.raises(ValueError, match="type is permanent"):
        _sync({"example": [FieldSpec(P, "example_tier", "Tier", "text")]})


def test_an_admins_field_with_the_declared_key_is_adopted_only_when_the_type_matches(login_as):
    admin = login_as("admin")
    notes = admin.post(DEFS, json={"entity_type": P, "label": "Notes", "key": "example_notes", "type": "text"}).json()
    size = admin.post(DEFS, json={"entity_type": P, "label": "Size", "key": "example_size", "type": "number"}).json()
    _sync({"example": [FieldSpec(P, "example_notes", "Notes", "text"), FieldSpec(P, "example_size", "Size", "text")]})
    assert _row("example_notes")["owner_app"] == "example" and _row("example_notes")["id"] == notes["id"]
    assert (_row("example_size")["owner_app"], _row("example_size")["type"]) == (None, "number")
    assert _row("example_size")["updated_at"] == size["updated_at"]


def test_the_example_field_appears_on_boot_and_archives_when_removed(app, monkeypatch):
    monkeypatch.setattr(scheduler, "jobs", lambda: {})  # boot without the scheduler's catch-up runs
    with TestClient(app):
        row = _row("example_finish", W)
    assert (row["owner_app"], row["archived_at"], row["options"]) == ("example", None, '["Matte", "Gloss"]')
    with TestClient(app):  # a restart leaves it as it was
        assert _row("example_finish", W) == row
    monkeypatch.setattr(example_fields, "FIELDS", [])
    with TestClient(app):
        assert _row("example_finish", W)["retired_at"] and _row("example_finish", W)["archived_at"]
    monkeypatch.setattr(
        example_fields, "FIELDS", [FieldSpec(W, "example_finish", "Finish", "select", ("Matte", "Gloss"))]
    )
    with TestClient(app):
        assert {k: v for k, v in _row("example_finish", W).items() if k != "updated_at"} == {
            k: v for k, v in row.items() if k != "updated_at"
        }
