"""Saved views: private until shared, owner-or-admin edits, and the stale-version refusal."""

VIEWS = "/api/core/views"
SURFACE = "example.widgets"


def _create(client, name="Red ones", **body) -> dict:
    r = client.post(VIEWS, json={"surface": SURFACE, "name": name, "payload": {"filters": {"color": ["red"]}}, **body})
    assert r.status_code == 200, r.text
    return r.json()


def _names(client) -> list[str]:
    return [v["name"] for v in client.get(VIEWS, params={"surface": SURFACE}).json()]


def test_create_shape_and_mine_plus_shared(login_as):
    admin, ann, bob = login_as("admin"), login_as("member"), login_as("member")
    view = _create(ann, entity_type="example.widget")
    assert view == {
        "id": view["id"], "surface": SURFACE, "entity_type": "example.widget", "name": "Red ones", "version": 1,
        "payload": {"filters": {"color": ["red"]}}, "owner": {"id": ann.user["id"], "name": ann.user["name"]},
        "is_shared": False, "can_edit": True, "created_at": view["created_at"], "updated_at": view["updated_at"],
    }
    _create(bob, "Bob's")
    _create(ann, "Elsewhere", surface="example.other")
    assert _names(ann) == ["Red ones"]
    assert _names(bob) == ["Bob's"]
    assert _names(admin) == []  # admins list their own and shared views too

    shared = ann.post(f"{VIEWS}/{view['id']}/share").json()
    assert shared["is_shared"] is True and shared["version"] == 1  # sharing is not an edit
    listed = bob.get(VIEWS, params={"surface": SURFACE}).json()
    assert [(v["name"], v["can_edit"]) for v in listed] == [("Bob's", True), ("Red ones", False)]
    assert [(v["name"], v["can_edit"]) for v in admin.get(VIEWS, params={"surface": SURFACE}).json()] == [("Red ones", True)]

    assert ann.post(f"{VIEWS}/{view['id']}/share").json()["is_shared"] is False  # no body flips it
    assert ann.post(f"{VIEWS}/{view['id']}/share", json={"is_shared": False}).json()["is_shared"] is False  # a body sets it
    assert _names(bob) == ["Bob's"]


def test_edits_need_the_current_version(login_as):
    ann = login_as("member")
    view = _create(ann)
    url = f"{VIEWS}/{view['id']}"
    renamed = ann.patch(url, json={"version": 1, "name": "Crimson"})
    assert renamed.status_code == 200 and renamed.json()["version"] == 2 and renamed.json()["name"] == "Crimson"
    stale = ann.patch(url, json={"version": 1, "payload": {"filters": {}}})
    assert stale.status_code == 409 and stale.json() == {"detail": "stale_view"}
    assert ann.patch(url, json={"version": True, "name": "x"}).status_code == 422  # strict int
    assert ann.patch(url, json={"name": "x"}).status_code == 422  # version is required
    edited = ann.patch(url, json={"version": 2, "payload": {"sort": "name"}, "entity_type": None}).json()
    assert (edited["version"], edited["payload"], edited["entity_type"], edited["name"]) == (3, {"sort": "name"}, None, "Crimson")


def test_only_the_owner_or_an_admin_changes_a_view(login_as):
    admin, ann, bob = login_as("admin"), login_as("member"), login_as("member")
    private, shared = _create(ann, "Private"), _create(ann, "Shared")
    ann.post(f"{VIEWS}/{shared['id']}/share")

    assert bob.patch(f"{VIEWS}/{private['id']}", json={"version": 1, "name": "x"}).status_code == 404  # invisible
    assert bob.delete(f"{VIEWS}/{private['id']}").status_code == 404
    assert bob.post(f"{VIEWS}/{private['id']}/share").status_code == 404
    assert bob.patch(f"{VIEWS}/{shared['id']}", json={"version": 1, "name": "x"}).status_code == 403  # visible, not his
    assert bob.delete(f"{VIEWS}/{shared['id']}").status_code == 403
    assert bob.post(f"{VIEWS}/{shared['id']}/share").status_code == 403

    assert admin.patch(f"{VIEWS}/{private['id']}", json={"version": 1, "name": "Tidied"}).json()["owner"]["id"] == ann.user["id"]
    assert admin.post(f"{VIEWS}/{private['id']}/share").json()["is_shared"] is True
    assert admin.delete(f"{VIEWS}/{shared['id']}").status_code == 204
    assert ann.delete(f"{VIEWS}/{private['id']}").status_code == 204
    assert ann.delete(f"{VIEWS}/{private['id']}").status_code == 404
    assert _names(ann) == [] and _names(bob) == []


def test_view_validation(login_as):
    ann, bob = login_as("member"), login_as("member")
    first = _create(ann, "Mine")
    assert ann.post(VIEWS, json={"surface": SURFACE, "name": " MINE ", "payload": {}}).json() == {"detail": "duplicate_name"}
    assert _create(bob, "Mine")["name"] == "Mine"  # names are per owner
    second = _create(ann, "Other")
    assert ann.patch(f"{VIEWS}/{second['id']}", json={"version": 1, "name": "mine"}).status_code == 409
    assert ann.get(VIEWS, params={"surface": "Bad Surface"}).status_code == 422
    for bad in (
        {"surface": "Bad Surface", "name": "x", "payload": {}},
        {"surface": SURFACE, "name": "  ", "payload": {}},
        {"surface": SURFACE, "name": "x" * 81, "payload": {}},
        {"surface": SURFACE, "name": "x", "payload": ["not", "an", "object"]},
        {"surface": SURFACE, "name": "x", "payload": {"big": "x" * 65536}},
        {"surface": SURFACE, "name": "x", "payload": {}, "entity_type": "nope.thing"},
        {"surface": SURFACE, "name": "x", "payload": {}, "rows": [1]},
    ):
        assert ann.post(VIEWS, json=bad).status_code == 422, bad
    assert ann.patch(f"{VIEWS}/{first['id']}", json={"version": 1, "payload": {"big": "x" * 65536}}).status_code == 422
    assert ann.get(VIEWS, params={"surface": SURFACE}).json()[0]["version"] == 1  # refused edits changed nothing
