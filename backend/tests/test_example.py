"""The integration fixture end to end, with two members and one private widget."""

import pytest

from backend.apps.example import api as example_api, jobs
from backend.core import clock, db as core_db, entities, settings
from backend.core.agent import registry as tools
from backend.core.auth.deps import system_user
from backend.core.errors import NotFound
from backend.core.reports import registry as reports


def _person() -> int:
    now = clock.now_iso()
    with core_db.transaction() as conn:
        return conn.execute("INSERT INTO core_people (name, created_at, updated_at) VALUES ('Ada', ?, ?)", (now, now)).lastrowid


def test_private_widget_is_invisible_to_another_member_on_every_surface(login_as):
    owner, other = login_as("member"), login_as("member")
    person = _person()
    secret = owner.post("/api/example/widgets", json={"name": "Secret", "is_private": True, "person_id": person}).json()
    public = owner.post("/api/example/widgets", json={"name": "Public", "person_id": person}).json()
    owner.post("/api/core/timeline", json={"entity_type": "example.widget", "entity_id": secret["id"], "body": "hush"})
    url = f"/api/example/widgets/{secret['id']}"
    timeline_q = {"entity_type": "example.widget", "entity_id": secret["id"]}

    assert [w["name"] for w in owner.get("/api/example/widgets").json()] == ["Secret", "Public"]
    assert [w["name"] for w in other.get("/api/example/widgets").json()] == ["Public"]
    assert other.get(url).status_code == 404
    assert other.patch(url, json={"name": "Mine"}).status_code == 404
    assert other.get("/api/core/timeline", params=timeline_q).status_code == 404
    assert other.post("/api/core/timeline", json={**timeline_q, "body": "hi"}).status_code == 404
    conn = core_db.get_conn()
    assert entities.titles_for(other.principal, conn, "example.widget", [secret["id"], public["id"]]) == {public["id"]: "Public"}
    assert [w["name"] for w in example_api.widgets_for_person(other.principal, person)] == ["Public"]
    with pytest.raises(NotFound):
        example_api.get_widget(other.principal, secret["id"])
    report = reports.get("example.widgets_by_color")
    assert report.run({}, other.principal) == (["color", "widgets"], [["teal", 1]])
    assert report.run({}, owner.principal) == (["color", "widgets"], [["teal", 2]])
    assert owner.get(url).json()["name"] == "Secret"


def test_public_widget_is_readable_but_only_owner_or_admin_writes(login_as):
    admin, owner, other = login_as("admin"), login_as("member"), login_as("member")
    w = owner.post("/api/example/widgets", json={"name": "Gear"}).json()
    url = f"/api/example/widgets/{w['id']}"
    assert other.get(url).status_code == 200
    assert other.patch(url, json={"name": "Mine"}).status_code == 403
    assert admin.patch(url, json={"name": "Admin's"}).json()["name"] == "Admin's"
    assert owner.patch(url, json={"is_private": True, "person_id": None}).json()["is_private"] is True
    assert other.get(url).status_code == 404


def test_widget_shape_defaults_and_validation(login_as):
    member = login_as("member")
    w = member.post("/api/example/widgets", json={"name": "Gear"}).json()
    assert set(w) == {"id", "name", "color", "owner_user_id", "person_id", "is_private", "created_at", "updated_at"}
    assert w["color"] == "teal" and w["owner_user_id"] == member.user["id"] and w["is_private"] is False  # setting default
    assert member.post("/api/example/widgets", json={"name": "Gear", "person_id": 999}).status_code == 422
    assert member.post("/api/example/widgets", json={"name": ""}).status_code == 422
    assert member.patch(f"/api/example/widgets/{w['id']}", json={"name": None}).status_code == 422
    assert member.get("/api/example/badge").json() == {"count": 1, "label": "Your widgets"}


def test_sync_hook_runs_with_the_edit(login_as):
    member = login_as("member")
    w = member.post("/api/example/widgets", json={"name": "Gear"}).json()
    member.patch(f"/api/example/widgets/{w['id']}", json={"color": "red"})
    assert settings.get_setting("example.last_changed_widget") == w["id"]


def test_tools_registered_and_scoped(login_as):
    member = login_as("member")
    names = [t.name for t in tools.for_user(member.principal)]
    assert names == ["example_list_widgets", "example_create_widget"]
    assert [t.name for t in tools.for_source("job")] == ["example_list_widgets"]
    create = tools.get("example_create_widget")
    assert create.app == "example" and create.revision == "0.1.0"
    with core_db.transaction() as conn:
        made = create.handler_in(conn, member.principal, {"name": "From a tool", "is_private": True})
    assert create.targets({"name": "x", "person_id": 5}) == [("core.person", 5)]
    assert tools.get("example_list_widgets").handler(member.principal, {})[0]["id"] == made["id"]
    assert [t.name for t in tools.for_user(system_user())] == names  # the job principal sees reads-capable tools


def test_tidy_job_is_attributed_to_the_system_principal(login_as):
    member = login_as("member")
    w = member.post("/api/example/widgets", json={"name": "Gear", "color": " RED "}).json()
    jobs.tidy(None)
    assert member.get(f"/api/example/widgets/{w['id']}").json()["color"] == "red"
    entry = member.get("/api/core/timeline", params={"entity_type": "example.widget", "entity_id": w["id"]}).json()[0]
    assert entry["author"] == {"id": 0, "name": "System"}


def test_settings_defaults_and_secrets(app, make_user):
    admin = make_user("admin")
    assert settings.get_setting("timezone") == "UTC"
    assert settings.get_setting("example.default_color") == "teal"
    settings.set_setting("example.default_color", "plum", admin.id)
    assert settings.get_setting("example.default_color") == "plum"
    settings.set_setting("core.test_secret", {"key": "sk-123"}, admin.id, is_secret=True)
    stored = core_db.one("SELECT value FROM core_settings WHERE key = 'core.test_secret'")["value"]
    assert stored.startswith("enc:v1:") and "sk-123" not in stored
    assert settings.get_setting("core.test_secret") == {"key": "sk-123"}
