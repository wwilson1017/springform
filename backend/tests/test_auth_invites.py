import json

import httpx
import pytest

from backend.core import db as core_db
from backend.core.auth import mail
from backend.core.auth.deps import COOKIE

from .conftest import PASSWORD, make_client
from .test_auth_totp import T0, enrol

NEW_PASSWORD = "a-brand-new-passphrase"


@pytest.fixture
def outbox(monkeypatch):
    """Mail on, delivered to a list instead of Resend."""
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == mail.RESEND_URL and request.headers["authorization"] == "Bearer re_test"
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "m1"})

    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("MAIL_FROM", "Springform <noreply@example.com>")
    monkeypatch.setattr(mail, "TRANSPORT", httpx.MockTransport(handler))
    return sent


def _token(url: str) -> str:
    return url.rsplit("/", 1)[1]


def _invite(admin, email="new@example.com", role="member"):
    r = admin.post("/api/auth/users", json={"email": email, "name": "New Person", "role": role})
    assert r.status_code == 200, r.text
    return r.json()


def test_invite_with_a_copyable_link_end_to_end(login_as, app):
    admin = login_as("admin")
    body = _invite(admin)
    assert body["mailed"] is False and body["invite_url"].startswith("http://localhost:8000/invite/")
    assert body["user"]["email"] == "new@example.com" and body["user"]["invite_pending"] is True
    assert body["user"]["invited_by"] == admin.user["id"] and "password_hash" not in body["user"]
    token = _token(body["invite_url"])
    stored = core_db.one("SELECT token_hash, purpose, expires_at FROM core_login_tokens WHERE purpose = 'invite'")
    assert stored["token_hash"] != token and len(stored["token_hash"]) == 64
    guest = make_client(app)
    for guess in ("!", "", PASSWORD):  # the '!' hash never authenticates
        assert guest.post("/api/auth/login", json={"email": "new@example.com", "password": guess}).status_code == 401
    assert guest.get(f"/api/auth/invite/{token}").json() == {"email": "new@example.com", "name": "New Person", "google": False}
    assert guest.post(f"/api/auth/invite/{token}", json={"password": "short"}).status_code == 422
    r = guest.post(f"/api/auth/invite/{token}", json={"password": NEW_PASSWORD})
    assert r.status_code == 200 and r.json()["user"]["email"] == "new@example.com" and COOKIE in guest.cookies
    assert guest.get("/api/me").status_code == 200
    assert guest.get(f"/api/auth/invite/{token}").status_code == 404  # single use
    assert guest.post(f"/api/auth/invite/{token}", json={"password": "another-password"}).status_code == 404
    assert make_client(app).post("/api/auth/login", json={"email": "new@example.com", "password": NEW_PASSWORD}).status_code == 200
    assert admin.post(f"/api/auth/users/{r.json()['user']['id']}/resend-invite").json() == {"detail": "invite_accepted"}


def test_invite_link_expires_after_an_hour(login_as, app, freeze):
    freeze(T0)
    token = _token(_invite(login_as("admin"))["invite_url"])
    freeze("2026-11-02T10:00:09Z")
    assert make_client(app).get(f"/api/auth/invite/{token}").status_code == 200
    freeze("2026-11-02T10:00:10Z")
    assert make_client(app).get(f"/api/auth/invite/{token}").status_code == 404


def test_resend_invalidates_the_old_link(login_as, app):
    admin = login_as("admin")
    body = _invite(admin)
    old = _token(body["invite_url"])
    r = admin.post(f"/api/auth/users/{body['user']['id']}/resend-invite")
    new = _token(r.json()["invite_url"])
    assert new != old and r.json()["mailed"] is False
    guest = make_client(app)
    assert guest.get(f"/api/auth/invite/{old}").status_code == 404
    assert guest.get(f"/api/auth/invite/{new}").status_code == 200
    assert admin.post("/api/auth/users/0/resend-invite").status_code == 404  # the system principal


def test_invites_are_admin_only_and_never_duplicate(login_as):
    admin, member = login_as("admin"), login_as("member")
    assert member.post("/api/auth/users", json={"email": "x@example.com"}).status_code == 403
    _invite(admin, "dup@example.com")
    assert admin.post("/api/auth/users", json={"email": " DUP@example.com"}).status_code == 409
    assert admin.post("/api/auth/users", json={"email": "system@springform.local"}).status_code == 409
    assert admin.post("/api/auth/users", json={"email": "x@example.com", "role": "system"}).status_code == 422


def test_invite_mail_goes_out_through_resend(login_as, outbox, monkeypatch):
    admin = login_as("admin")
    body = _invite(admin)
    assert body["mailed"] is True and len(outbox) == 1
    assert outbox[0]["to"] == ["new@example.com"] and outbox[0]["from"] == "Springform <noreply@example.com>"
    assert body["invite_url"] in outbox[0]["text"]
    monkeypatch.setattr(mail, "TRANSPORT", httpx.MockTransport(lambda r: httpx.Response(500)))
    body = _invite(admin, "second@example.com")
    assert body["mailed"] is False and body["invite_url"]  # the admin still has the link


def test_forgot_and_reset(login_as, app, outbox):
    member = login_as("member")
    other_session = login_as("member", email="other@example.com")
    assert make_client(app).post("/api/auth/forgot", json={"email": "nobody@example.com"}).json() == {"mail": True}
    assert outbox == []
    guest = make_client(app)
    r = guest.post("/api/auth/forgot", json={"email": member.user["email"].upper()})
    assert r.status_code == 202 and len(outbox) == 1 and outbox[0]["to"] == [member.user["email"]]
    url = next(word for word in outbox[0]["text"].split() if "/reset-password/" in word)
    assert url.startswith("http://localhost:8000/reset-password/")
    token = _token(url)
    assert guest.post("/api/auth/reset", json={"token": token, "password": "short"}).status_code == 422
    r = guest.post("/api/auth/reset", json={"token": token, "password": NEW_PASSWORD})
    assert r.status_code == 200 and r.json()["user"]["id"] == member.user["id"] and guest.get("/api/me").status_code == 200
    assert member.get("/api/me").status_code == 401  # every older session ended
    assert other_session.get("/api/me").status_code == 200
    assert guest.post("/api/auth/reset", json={"token": token, "password": "yet-another-one"}).status_code == 404
    login = make_client(app).post
    assert login("/api/auth/login", json={"email": member.user["email"], "password": PASSWORD}).status_code == 401
    assert login("/api/auth/login", json={"email": member.user["email"], "password": NEW_PASSWORD}).status_code == 200


def test_forgot_without_mail_issues_nothing_and_is_rate_limited(login_as, app):
    member = login_as("member")
    guest = make_client(app)
    assert guest.post("/api/auth/forgot", json={"email": member.user["email"]}).json() == {"mail": False}
    assert core_db.one("SELECT count(*) AS n FROM core_login_tokens WHERE purpose = 'reset'")["n"] == 0
    for _ in range(2):
        assert guest.post("/api/auth/forgot", json={"email": member.user["email"]}).status_code == 202
    assert guest.post("/api/auth/forgot", json={"email": member.user["email"]}).status_code == 429


def test_reset_with_2fa_on_still_needs_the_second_step(login_as, app, outbox, freeze):
    freeze(T0)
    member = login_as("member")
    enrol(member)
    guest = make_client(app)
    guest.post("/api/auth/forgot", json={"email": member.user["email"]})
    token = _token(next(w for w in outbox[0]["text"].split() if "/reset-password/" in w))
    r = guest.post("/api/auth/reset", json={"token": token, "password": NEW_PASSWORD})
    assert r.json()["totp_required"] is True and COOKIE not in guest.cookies


def test_password_change_ends_other_sessions_and_keeps_this_one(login_as, app):
    member = login_as("member")
    elsewhere = make_client(app)
    elsewhere.post("/api/auth/login", json={"email": member.user["email"], "password": PASSWORD})
    with core_db.transaction() as conn:
        conn.execute(
            "INSERT INTO core_trusted_devices (token_hash, user_id, expires_at, created_at) VALUES ('t', ?, '2099-01-01T00:00:00Z', ?)",
            (member.user["id"], "2026-01-01T00:00:00Z"),
        )
    assert member.post("/api/auth/password", json={"current": "wrong-password", "new": NEW_PASSWORD}).json() == {
        "detail": "wrong_password"
    }
    assert member.post("/api/auth/password", json={"current": PASSWORD, "new": "short"}).status_code == 422
    r = member.post("/api/auth/password", json={"current": PASSWORD, "new": NEW_PASSWORD})
    assert r.status_code == 200 and r.json()["user"]["id"] == member.user["id"]
    assert member.get("/api/me").status_code == 200 and elsewhere.get("/api/me").status_code == 401
    assert core_db.one("SELECT count(*) AS n FROM core_trusted_devices")["n"] == 0
    assert make_client(app).post("/api/auth/login", json={"email": member.user["email"], "password": NEW_PASSWORD}).status_code == 200
