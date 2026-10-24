import pytest

from backend.core import db as core_db
from backend.core.auth import service
from backend.core.auth.deps import COOKIE

from .conftest import PASSWORD, make_client


def test_list_excludes_the_system_principal_and_filters(login_as):
    admin, member = login_as("admin"), login_as("member")
    rows = admin.get("/api/auth/users").json()
    assert {r["id"] for r in rows} == {admin.user["id"], member.user["id"]}
    assert set(rows[0]) == {
        "id", "email", "name", "role", "tz", "is_active", "invite_pending", "has_password", "google_linked",
        "totp_enabled", "invited_by", "last_login_at", "deactivated_at", "created_at",
    }
    admin.post(f"/api/auth/users/{member.user['id']}/deactivate")
    assert [r["id"] for r in admin.get("/api/auth/users?status=active").json()] == [admin.user["id"]]
    assert [r["id"] for r in admin.get("/api/auth/users?status=inactive").json()] == [member.user["id"]]
    assert admin.get("/api/auth/users?status=bogus").status_code == 422
    assert member.get("/api/auth/users").status_code == 401  # deactivated: out everywhere
    assert login_as("member").get("/api/auth/users").status_code == 403


def test_patch_user(login_as):
    admin, member = login_as("admin"), login_as("member")
    uid = member.user["id"]
    r = admin.patch(f"/api/auth/users/{uid}", json={"name": " Renamed ", "role": "admin", "tz": "America/Chicago"})
    assert (r.json()["name"], r.json()["role"], r.json()["tz"]) == ("Renamed", "admin", "America/Chicago")
    assert member.get("/api/me").json()["role"] == "admin"  # the live row, next request
    assert admin.patch(f"/api/auth/users/{uid}", json={"tz": None}).json()["tz"] is None
    assert admin.patch(f"/api/auth/users/{uid}", json={"tz": "Mars/Base"}).status_code == 422
    assert admin.patch(f"/api/auth/users/{uid}", json={"role": "system"}).status_code == 422
    assert admin.patch("/api/auth/users/0", json={"name": "x"}).status_code == 404
    assert admin.patch("/api/auth/users/999", json={"name": "x"}).status_code == 404


def test_the_last_admin_who_can_sign_in_stays(login_as):
    admin = login_as("admin")
    uid = admin.user["id"]
    assert admin.patch(f"/api/auth/users/{uid}", json={"role": "member"}).json() == {"detail": "last_admin"}
    assert admin.post(f"/api/auth/users/{uid}/deactivate").json() == {"detail": "last_admin"}
    admin.post("/api/auth/users", json={"email": "pending@example.com", "role": "admin"})  # cannot sign in yet
    assert admin.patch(f"/api/auth/users/{uid}", json={"role": "member"}).status_code == 409
    second = login_as("admin")
    assert admin.patch(f"/api/auth/users/{uid}", json={"role": "member"}).json()["role"] == "member"
    assert second.patch(f"/api/auth/users/{second.user['id']}", json={"role": "member"}).status_code == 409
    assert second.patch(f"/api/auth/users/{second.user['id']}", json={"name": "Still admin"}).status_code == 200


def test_deactivation_ends_sessions_and_runs_the_hooks(login_as, app, monkeypatch):
    admin, member = login_as("admin"), login_as("member")
    uid = member.user["id"]
    seen = []

    def hook(conn, user_id):
        row = conn.execute("SELECT is_active, deactivated_at FROM core_users WHERE id = ?", (user_id,)).fetchone()
        seen.append((user_id, row["is_active"], row["deactivated_at"] is not None, core_db.in_transaction()))

    monkeypatch.setattr(service, "ON_DEACTIVATE", [hook])
    with core_db.transaction() as conn:
        conn.execute(
            "INSERT INTO core_trusted_devices (token_hash, user_id, expires_at, created_at) VALUES ('t', ?, '2099-01-01T00:00:00Z', ?)",
            (uid, "2026-01-01T00:00:00Z"),
        )
        service.issue_token_in(conn, uid, "reset")
    r = admin.post(f"/api/auth/users/{uid}/deactivate")
    assert r.json()["is_active"] is False and r.json()["deactivated_at"]
    assert seen == [(uid, 0, True, True)]
    assert member.get("/api/me").json() == {"detail": "invalid_session"}
    assert core_db.one("SELECT count(*) AS n FROM core_trusted_devices")["n"] == 0
    assert core_db.one("SELECT count(*) AS n FROM core_login_tokens WHERE user_id = ?", (uid,))["n"] == 0
    login = {"email": member.user["email"], "password": PASSWORD}
    assert make_client(app).post("/api/auth/login", json=login).status_code == 401
    assert admin.post(f"/api/auth/users/{uid}/reactivate").json()["is_active"] is True
    assert make_client(app).post("/api/auth/login", json=login).status_code == 200


def test_a_failing_deactivate_hook_rolls_everything_back(login_as, monkeypatch):
    admin, member = login_as("admin"), login_as("member")

    def broken(conn, user_id):
        raise RuntimeError("subscriber failed")

    monkeypatch.setattr(service, "ON_DEACTIVATE", [broken])
    with pytest.raises(RuntimeError):
        admin.post(f"/api/auth/users/{member.user['id']}/deactivate")
    assert member.get("/api/me").status_code == 200
    assert service.get_user(member.user["id"])["is_active"] == 1


def test_patch_me(login_as):
    member = login_as("member")
    r = member.patch("/api/me", json={"name": "Me Myself", "tz": "Europe/London", "role": "admin"})
    assert r.json() == {**member.user, "name": "Me Myself", "tz": "Europe/London"}
    assert member.patch("/api/me", json={"tz": "Nowhere/Land"}).status_code == 422


NEW_WRITES = [
    ("post", "/api/auth/login/totp"), ("post", "/api/auth/totp/enrol"), ("post", "/api/auth/totp/confirm"),
    ("post", "/api/auth/totp/disable"), ("delete", "/api/auth/trusted-devices"), ("post", "/api/auth/google/unlink"),
    ("put", "/api/auth/google/config"), ("post", "/api/auth/google/test"), ("post", "/api/auth/users"),
    ("post", "/api/auth/users/1/resend-invite"), ("post", "/api/auth/users/1/reset-link"), ("post", "/api/auth/invite/x"), ("post", "/api/auth/forgot"),
    ("post", "/api/auth/reset"), ("post", "/api/auth/password"), ("patch", "/api/auth/users/1"),
    ("post", "/api/auth/users/1/deactivate"), ("post", "/api/auth/users/1/reactivate"), ("patch", "/api/me"),
]


@pytest.mark.parametrize(("method", "path"), NEW_WRITES)
def test_csrf_guards_every_new_write(login_as, method, path):
    admin = login_as("admin")
    cross = make_client(admin.app, **{"Sec-Fetch-Site": "cross-site"})
    cross.cookies.set(COOKIE, admin.cookies[COOKIE])
    assert cross.request(method, path, json={}).json() == {"detail": "csrf_refused"}
    assert core_db.one("SELECT is_active FROM core_users WHERE id = ?", (admin.user["id"],))["is_active"] == 1
