import io
import statistics
import time

import pytest
from fastapi import HTTPException

from backend import cli
from backend.core import db as core_db, preview
from backend.core.auth import bootstrap, jwt, service
from backend.core.auth.deps import COOKIE, require_admin

from .conftest import PASSWORD, make_client


def _login(client, email, password=PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def test_setup_requires_the_token_consumes_it_and_then_404s(client, db, tmp_path):
    assert client.get("/api/auth/status").json() == {"setup_required": True, "google": False, "preview": False}
    token = bootstrap.ensure_setup_token()
    token_file = tmp_path / "data" / "setup-token"
    assert token_file.read_text().strip() == token and oct(token_file.stat().st_mode & 0o777) == "0o600"
    body = {"email": "Owner@Example.com ", "name": "Owner", "password": PASSWORD}
    assert client.post("/api/auth/setup", json={**body, "token": "wrong"}).status_code == 404
    r = client.post("/api/auth/setup", json={**body, "token": token})
    assert r.status_code == 200
    assert r.json() == {"user": {"id": 1, "email": "owner@example.com", "name": "Owner", "role": "admin", "tz": None}}
    assert "httponly" in r.headers["set-cookie"].lower() and "samesite=lax" in r.headers["set-cookie"].lower()
    assert client.get("/api/me").json()["email"] == "owner@example.com"
    assert not token_file.exists()
    assert client.post("/api/auth/setup", json={**body, "email": "x@example.com", "token": token}).status_code == 404
    assert client.get("/api/auth/status").json()["setup_required"] is False
    assert bootstrap.ensure_setup_token() is None


def test_setup_ignores_the_system_principal(db):
    assert core_db.one("SELECT count(*) AS n FROM core_users")["n"] == 1  # the seeded system row
    assert bootstrap.setup_required()


def test_short_password_is_invalid(client, db):
    token = bootstrap.ensure_setup_token()
    r = client.post("/api/auth/setup", json={"token": token, "email": "a@example.com", "password": "short"})
    assert r.status_code == 422


def test_unset_password_and_system_principal_never_sign_in(client, make_user):
    make_user("member", email="invited@example.com", password=None)
    assert _login(client, "invited@example.com", "!").status_code == 401
    assert _login(client, "system@springform.local", "!").json() == {"detail": "invalid_credentials"}
    forged = make_client(client.app, Authorization=f"Bearer {jwt.mint(0, 0)}")
    assert forged.get("/api/me").status_code == 401


def test_wrong_password_costs_about_what_an_unknown_email_costs(client, make_user, monkeypatch):
    monkeypatch.setattr(service, "BCRYPT_ROUNDS", 10)
    make_user("member", email="real@example.com")  # hashed at 10 rounds
    service.spend_dummy_verify()  # build the equalizer hash outside the timing

    def timed(email):
        samples = []
        for _ in range(3):
            start = time.perf_counter()
            assert _login(client, email, "wrong-password").status_code == 401
            samples.append(time.perf_counter() - start)
        return statistics.median(samples)

    known, unknown = timed("real@example.com"), timed("nobody@example.com")
    assert 0.5 < known / unknown < 2.0, (known, unknown)


def test_account_rate_limit(client, make_user, freeze):
    freeze("2026-11-02T09:00:00Z")
    make_user("member", email="target@example.com")
    for _ in range(10):
        assert _login(client, "target@example.com", "guess").status_code == 401
    assert _login(client, "target@example.com").status_code == 429  # even the right password
    freeze("2026-11-02T09:05:01Z")
    assert _login(client, "target@example.com").status_code == 200


def test_address_rate_limit(client, db, freeze):
    freeze("2026-11-02T09:00:00Z")
    for n in range(50):
        assert _login(client, f"spray{n}@example.com", "guess").status_code == 401
    assert _login(client, "spray-last@example.com", "guess").status_code == 429


def test_logout_clears_the_cookie(login_as):
    member = login_as("member")
    assert member.get("/api/me").status_code == 200
    r = member.post("/api/auth/logout")
    assert r.status_code == 204 and COOKIE not in member.cookies
    assert member.get("/api/me").status_code == 401


def test_epoch_bump_ends_the_session(login_as):
    member = login_as("member")
    with core_db.transaction() as conn:
        service.bump_token_epoch_in(conn, member.user["id"])
    assert member.get("/api/me").json() == {"detail": "invalid_session"}


def test_deactivated_user_is_out_on_the_next_request(login_as):
    member = login_as("member")
    with core_db.transaction() as conn:
        conn.execute("UPDATE core_users SET is_active = 0 WHERE id = ?", (member.user["id"],))
    assert member.get("/api/me").status_code == 401


def test_csrf_rules_for_cookie_sessions(login_as, monkeypatch):
    member = login_as("member")
    cookie = member.cookies[COOKIE]
    body = {"name": "Gear"}
    cross = make_client(member.app, **{"Sec-Fetch-Site": "cross-site"})
    cross.cookies.set(COOKIE, cookie)
    assert cross.post("/api/example/widgets", json=body).json() == {"detail": "csrf_refused"}
    bare = make_client(member.app)
    del bare.headers["Sec-Fetch-Site"]
    bare.cookies.set(COOKIE, cookie)
    assert bare.post("/api/example/widgets", json=body).status_code == 403  # no fetch metadata, no Origin
    assert bare.get("/api/example/widgets").status_code == 200  # reads are not state-changing
    monkeypatch.setenv("PUBLIC_URL", "https://crm.example.com/")
    assert bare.post("/api/example/widgets", json=body, headers={"Origin": "https://crm.example.com"}).status_code == 200
    assert bare.post("/api/example/widgets", json=body, headers={"Origin": "https://evil.example"}).status_code == 403
    bearer = make_client(member.app, Authorization=f"Bearer {cookie}")
    del bearer.headers["Sec-Fetch-Site"]
    assert bearer.post("/api/example/widgets", json=body).status_code == 200  # bearer-only is exempt
    bearer.cookies.set(COOKIE, cookie)
    assert bearer.post("/api/example/widgets", json=body).status_code == 403  # both: cookie rules


def test_require_admin(login_as):
    member = login_as("member")
    with pytest.raises(HTTPException) as e:
        require_admin(member.principal)
    assert e.value.status_code == 403


def test_preview_role_picker(client, db, monkeypatch):
    assert client.post("/api/auth/preview", json={"role": "admin"}).status_code == 404
    monkeypatch.setenv("PREVIEW_MODE", "1")
    preview.seed()
    r = client.post("/api/auth/preview", json={"role": "member"})
    assert r.json()["user"]["email"] == "preview-member@example.com"
    assert client.get("/api/me").json()["role"] == "member"
    assert client.get("/api/auth/status").json() == {"setup_required": False, "google": True, "preview": True}  # the stub
    assert _login(client, "preview-admin@example.com", "!").status_code == 401  # no password to guess


def test_preview_refuses_real_secrets(monkeypatch):
    monkeypatch.setenv("PREVIEW_MODE", "1")
    preview.check_startup()
    monkeypatch.setenv("ENCRYPTION_KEY", "anything")
    with pytest.raises(RuntimeError, match="ENCRYPTION_KEY"):
        preview.check_startup()


def test_cli_create_admin(db, client, monkeypatch, capsys):
    bootstrap.ensure_setup_token()
    monkeypatch.setattr("sys.stdin", io.StringIO(PASSWORD + "\n"))
    cli.main(["create-admin", "ops@example.com", "--name", "Ops"])
    assert "Created admin ops@example.com" in capsys.readouterr().out
    assert not bootstrap.setup_required()
    assert _login(client, "ops@example.com").json()["user"]["role"] == "admin"
