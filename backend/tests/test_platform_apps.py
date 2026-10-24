import pytest

from backend.core import db as core_db, registry


@pytest.fixture
def two_apps(app, monkeypatch):
    """The example app plus a manifest-only twin, `zeta`, whose manifest order puts it first."""
    example = registry.get_app("example")
    zeta = registry.App(
        example.manifest.model_copy(update={"slug": "zeta", "path": "/zeta", "order": 1}), example.path, example.modules
    )
    monkeypatch.setattr(registry, "_APPS", [example, zeta])


def _slugs(client) -> list[str]:
    return [a["slug"] for a in client.get("/api/core/apps").json()]


def test_hide_is_persisted_and_hides_the_tile_from_members_only(login_as):
    admin, member = login_as("admin"), login_as("member")
    r = admin.patch("/api/core/apps/example", json={"hidden": True})
    assert r.status_code == 200, r.text
    assert next(a for a in r.json() if a["slug"] == "example")["hidden"] is True
    assert core_db.one("SELECT hidden FROM core_apps_state WHERE slug = 'example'")["hidden"] == 1
    assert "example" not in _slugs(member)
    assert next(a for a in admin.get("/api/core/apps").json() if a["slug"] == "example")["hidden"] is True

    admin.patch("/api/core/apps/example", json={"hidden": False})
    assert "example" in _slugs(member)
    assert admin.patch("/api/core/apps/example", json={}).status_code == 200  # nothing to change
    assert admin.patch("/api/core/apps/nope", json={"hidden": True}).status_code == 404
    assert member.patch("/api/core/apps/example", json={"hidden": True}).status_code == 403


def test_order_is_persisted_and_applies_to_everyone(login_as, two_apps):
    admin, member = login_as("admin"), login_as("member")
    assert _slugs(member) == ["zeta", "example"]  # manifest order

    r = admin.put("/api/core/apps/order", json={"slugs": ["example"]})
    assert r.status_code == 200, r.text
    assert [a["slug"] for a in r.json()] == ["example", "zeta"]  # placed apps first, the rest by manifest order
    assert _slugs(member) == ["example", "zeta"]
    assert core_db.rows("SELECT slug, position FROM core_apps_state ORDER BY slug") == [
        {"slug": "example", "position": 0}
    ]

    admin.patch("/api/core/apps/zeta", json={"hidden": True})
    admin.put("/api/core/apps/order", json={"slugs": ["zeta", "example"]})
    assert _slugs(admin) == ["zeta", "example"] and _slugs(member) == ["example"]
    assert core_db.one("SELECT hidden FROM core_apps_state WHERE slug = 'zeta'")["hidden"] == 1  # order kept hide

    assert admin.put("/api/core/apps/order", json={"slugs": ["nope"]}).status_code == 422
    assert admin.put("/api/core/apps/order", json={"slugs": ["zeta", "zeta"]}).status_code == 422
    assert member.put("/api/core/apps/order", json={"slugs": []}).status_code == 403
    assert _slugs(admin) == ["zeta", "example"]
