from pathlib import Path

import pytest

from backend.apps.example import service
from backend.apps.example.models import WidgetIn
from backend.core import db as core_db, registry
from backend.core.agent import registry as tools
from backend.core.errors import Forbidden
from backend.core.timeline import api as timeline
from backend.main import create_app

from .conftest import make_client

ADMIN_ONLY_APPS = Path(__file__).parent / "fixtures" / "apps_admin"


def test_member_gets_403_on_an_admin_only_app(login_as):
    admin_only = create_app(ADMIN_ONLY_APPS)  # after the default app: its registries are the live ones
    admin, member = login_as("admin", on=admin_only), login_as("member", on=admin_only)
    assert make_client(admin_only).get("/api/adminonly/ping").status_code == 401
    assert member.get("/api/adminonly/ping").status_code == 403
    assert admin.get("/api/adminonly/ping").json() == {"ok": True}
    assert [a["slug"] for a in member.get("/api/core/apps").json()] == []
    assert [a["slug"] for a in admin.get("/api/core/apps").json()] == ["adminonly"]
    assert [t.name for t in tools.for_user(member.principal) if t.app != "core"] == []
    assert [t.name for t in tools.for_user(admin.principal) if t.app != "core"] == ["adminonly_peek"]


def test_apps_listing_by_role_and_hidden_state(login_as):
    admin, member = login_as("admin"), login_as("member")
    def example(client) -> dict | None:  # forks install more apps; only the fixture is pinned here
        return next((a for a in client.get("/api/core/apps").json() if a["slug"] == "example"), None)

    listed = example(member)
    assert set(listed) == {"slug", "name", "description", "path", "icon", "roles", "order", "badge", "hidden", "settings_cards", "version"}
    assert listed["path"] == "/example" and listed["hidden"] is False
    assert listed["settings_cards"] == []  # the example's card is admin-only
    assert example(admin)["settings_cards"] == [{"id": "example", "title": "Example", "admin_only": True}]
    with core_db.transaction() as conn:
        conn.execute("INSERT INTO core_apps_state (slug, hidden) VALUES ('example', 1)")
    assert example(member) is None
    assert example(admin)["hidden"] is True


def test_reset_keeps_ids_climbing_and_old_content_unreachable(app, make_user):
    owner, other = make_user("member"), make_user("member")
    secret = service.create_widget(owner, WidgetIn(name="Secret", is_private=True))
    timeline.add_note(owner, "example.widget", secret["id"], "private note")
    with core_db.transaction() as conn:
        registry.reset_app_in(conn, "example")
    assert core_db.one("SELECT count(*) AS n FROM example_widgets")["n"] == 0
    assert core_db.one("SELECT count(*) AS n FROM core_timeline")["n"] == 0
    assert core_db.one("SELECT seq FROM sqlite_sequence WHERE name = 'example_widgets'")["seq"] == secret["id"]
    fresh = service.create_widget(other, WidgetIn(name="Fresh"))
    assert fresh["id"] > secret["id"]
    assert timeline.list_for(other, "example.widget", fresh["id"]) == []


def test_factory_reset_only_on_an_install_holding_no_data(app, make_user):
    admin = make_user("admin")
    registry.factory_reset(caller=admin)  # the caller is the only human and nothing is stored yet
    admin = make_user("admin")
    with pytest.raises(Forbidden):  # another human account exists
        registry.factory_reset()
    with core_db.transaction() as conn:
        conn.execute("DELETE FROM core_users WHERE id NOT IN (0, ?)", (admin.id,))
    service.create_widget(admin, WidgetIn(name="Kept"))
    with pytest.raises(Forbidden):  # an app table holds data
        registry.factory_reset(caller=admin)


def test_factory_reset_runs_core_startup_hooks_after_commit(app, monkeypatch):
    ran = []
    monkeypatch.setattr(registry, "run_startup_hooks", lambda: ran.append(core_db.in_transaction()))
    registry.factory_reset()
    assert ran == [False]


def test_factory_reset_in_preview_clears_everything_and_reseeds(app, monkeypatch):
    from backend.core import preview

    monkeypatch.setenv("PREVIEW_MODE", "1")
    preview.seed()
    preview.seed()  # every preview boot runs sample(); it must not duplicate
    assert core_db.one("SELECT count(*) AS n FROM example_widgets")["n"] == 2  # sample data
    with core_db.transaction() as conn:
        registry.factory_reset_in(conn)
    users = core_db.rows("SELECT id, role FROM core_users ORDER BY id")
    assert users[0] == {"id": 0, "role": "system"} and [u["id"] for u in users[1:]] == [1, 2]  # sequences reset
    assert core_db.one("SELECT max(id) AS m FROM example_widgets")["m"] == 2


def test_every_app_sample_is_idempotent(app, make_user, monkeypatch):
    """PREVIEW_MODE runs every app's sample() on each boot; a second run must add nothing."""
    from backend.core import preview

    monkeypatch.setenv("PREVIEW_MODE", "1")
    preview.seed()
    counts = lambda: {t: core_db.one(f"SELECT count(*) AS n FROM {t}")["n"] for a in registry.installed() for t in a.modules["seed"].RESET_TABLES}  # noqa: E731
    first = counts()
    preview.seed()
    assert counts() == first
