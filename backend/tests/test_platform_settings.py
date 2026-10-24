from backend.core import db as core_db, memory, settings
from backend.core.platform import keys

from .conftest import make_client


def test_get_shows_values_and_defaults_and_masks_secrets(login_as):
    admin = login_as("admin")
    body = admin.get("/api/core/settings").json()
    assert body["values"]["workspace.name"] == "Springform"
    assert body["values"]["timezone"] == "UTC"
    assert body["values"]["example.default_color"] == "teal"  # app keys come from the app's DEFAULTS
    assert body["defaults"]["files.max_bytes"] == 25 * 1024 * 1024
    assert body["secrets"] == {"github.token": False}
    assert "github.token" not in body["values"] and "github.token" not in body["defaults"]

    r = admin.put("/api/core/settings", json={"values": {"github.token": "github_pat_s3cret"}})
    assert r.status_code == 200, r.text
    assert r.json()["secrets"] == {"github.token": True}
    assert "s3cret" not in r.text and "s3cret" not in admin.get("/api/core/settings").text
    stored = core_db.one("SELECT value, is_secret, updated_by FROM core_settings WHERE key = 'github.token'")
    assert stored["is_secret"] == 1 and stored["value"].startswith("enc:v1:") and "s3cret" not in stored["value"]
    assert stored["updated_by"] == admin.user["id"]
    assert settings.get_setting("github.token") == "github_pat_s3cret"


def test_put_validates_every_key_before_writing_any(login_as):
    admin = login_as("admin")
    bad = [
        ({"nope": 1}, "unknown setting 'nope'"),
        ({"timezone": "Mars/Olympus_Mons"}, "timezone"),
        ({"timezone": "../../etc/passwd"}, "timezone"),
        ({"github.repo": "not a repo"}, "github.repo"),
        ({"files.max_bytes": True}, "files.max_bytes"),
        ({"files.max_bytes": -1}, "files.max_bytes"),
        ({"agent.nightly_enabled": "yes"}, "agent.nightly_enabled"),
        ({"workspace.name": "   "}, "workspace.name"),
        ({"github.token": ""}, "github.token"),
    ]
    for values, detail in bad:
        r = admin.put("/api/core/settings", json={"values": {"workspace.name": "Never written", **values}})
        assert r.status_code == 422, (values, r.text)
        assert detail in r.json()["detail"]
    assert core_db.rows("SELECT key FROM core_settings") == []

    r = admin.put(
        "/api/core/settings",
        json={"values": {
            "workspace.name": "  Acme Bakery ", "timezone": "America/Chicago", "github.repo": "acme/ops",
            "files.max_bytes": 1000, "auth.require_totp_for_google": True, "example.default_color": "plum",
        }},
    )  # fmt: skip
    assert r.status_code == 200, r.text
    values = r.json()["values"]
    assert values["workspace.name"] == "Acme Bakery"
    assert values["timezone"] == "America/Chicago" and values["github.repo"] == "acme/ops"
    assert values["files.max_bytes"] == 1000 and values["auth.require_totp_for_google"] is True
    assert values["example.default_color"] == "plum"
    assert keys.get("timezone") == "America/Chicago"


def test_delete_resets_to_the_default(login_as):
    admin = login_as("admin")
    admin.put("/api/core/settings", json={"values": {"workspace.name": "Acme", "github.token": "t0ken"}})
    r = admin.delete("/api/core/settings/workspace.name")
    assert r.status_code == 200 and r.json()["values"]["workspace.name"] == "Springform"
    assert admin.delete("/api/core/settings/github.token").json()["secrets"] == {"github.token": False}
    assert admin.delete("/api/core/settings/workspace.name").status_code == 200  # already default: still fine
    assert admin.delete("/api/core/settings/nope").status_code == 422


def test_settings_are_admin_only_and_workspace_is_for_every_member(login_as, app):
    admin, member = login_as("admin"), login_as("member")
    assert member.get("/api/core/settings").status_code == 403
    assert member.put("/api/core/settings", json={"values": {"workspace.name": "x"}}).status_code == 403
    assert member.delete("/api/core/settings/workspace.name").status_code == 403
    assert make_client(app).get("/api/core/workspace").status_code == 401

    admin.put("/api/core/settings", json={"values": {"workspace.name": "Acme Bakery", "timezone": "Europe/Paris"}})
    workspace = member.get("/api/core/workspace").json()
    assert workspace == {
        "name": "Acme Bakery",
        "timezone": "Europe/Paris",
        "version": workspace["version"],
        "preview": False,
        "public_url": "http://localhost:8000",
    }
    assert workspace["version"]


def test_workspace_shows_public_url_from_the_env_auth_uses(login_as, monkeypatch):
    from backend.core.auth import google

    monkeypatch.setenv("PUBLIC_URL", "https://crm.example.com/")
    workspace = login_as("member").get("/api/core/workspace").json()
    assert workspace["public_url"] == "https://crm.example.com"
    assert google.redirect_uri() == workspace["public_url"] + "/api/auth/google/callback"


def test_get_lists_only_settable_keys_so_a_round_trip_put_succeeds(login_as):
    admin = login_as("admin")
    settings.set_setting("backups.key_shown_at", "2026-11-02T09:00:00Z", None)  # internal core rows
    settings.set_setting("notifications.vapid_public_key", "BPub", None)
    settings.set_setting("auth.google_client_secret", "gsecret", None, is_secret=True)
    settings.set_setting("gone.colour", "red", None)  # an app that is no longer installed
    body = admin.get("/api/core/settings").json()
    listed = set(body["values"]) | set(body["secrets"]) | set(body["defaults"])
    assert listed == set(keys.known())
    assert body["values"]["agent.context_budget_chars"] == memory.DEFAULT_BUDGET
    assert admin.put("/api/core/settings", json={"values": body["values"]}).status_code == 200

    assert admin.put("/api/core/settings", json={"values": {"agent.context_budget_chars": 0}}).status_code == 422
    r = admin.put("/api/core/settings", json={"values": {"agent.context_budget_chars": 4000}})
    assert r.json()["values"]["agent.context_budget_chars"] == 4000
    assert settings.get_setting(memory.BUDGET_SETTING) == 4000  # what memory.context_for reads
