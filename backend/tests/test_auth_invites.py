import json
import logging

import httpx
import pytest

from backend.core import db as core_db, logscrub
from backend.core.auth import invites, jwt, mail
from backend.core.auth.deps import COOKIE
from backend.core.platform import keys
from backend.testing.fixtures import PASSWORD, make_client

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
    assert guest.get(f"/api/auth/invite/{token}").json() == {
        "email": "new@example.com",
        "name": "New Person",
        "google": False,
    }
    assert guest.post(f"/api/auth/invite/{token}", json={"password": "short"}).status_code == 422
    r = guest.post(f"/api/auth/invite/{token}", json={"password": NEW_PASSWORD})
    assert r.status_code == 200 and r.json()["user"]["email"] == "new@example.com" and COOKIE in guest.cookies
    assert guest.get("/api/me").status_code == 200
    assert guest.get(f"/api/auth/invite/{token}").status_code == 404  # single use
    assert guest.post(f"/api/auth/invite/{token}", json={"password": "another-password"}).status_code == 404
    assert (
        make_client(app)
        .post("/api/auth/login", json={"email": "new@example.com", "password": NEW_PASSWORD})
        .status_code
        == 200
    )
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
    assert (
        r.status_code == 200 and r.json()["user"]["id"] == member.user["id"] and guest.get("/api/me").status_code == 200
    )
    assert member.get("/api/me").status_code == 401  # every older session ended
    assert other_session.get("/api/me").status_code == 200
    assert guest.post("/api/auth/reset", json={"token": token, "password": "yet-another-one"}).status_code == 404
    login = make_client(app).post
    assert login("/api/auth/login", json={"email": member.user["email"], "password": PASSWORD}).status_code == 401
    assert login("/api/auth/login", json={"email": member.user["email"], "password": NEW_PASSWORD}).status_code == 200


def test_an_admin_issues_a_reset_link(login_as, app, outbox, monkeypatch):
    admin, member = login_as("admin"), login_as("member")
    monkeypatch.delenv("RESEND_API_KEY")  # no mail: the copyable link is the way out
    r = admin.post(f"/api/auth/users/{member.user['id']}/reset-link")
    assert r.status_code == 200 and r.json()["mailed"] is False and outbox == []
    first = r.json()["reset_url"]
    assert first.startswith("http://localhost:8000/reset-password/")
    assert (
        core_db.one("SELECT created_by FROM core_login_tokens WHERE purpose = 'reset'")["created_by"]
        == admin.user["id"]
    )
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    r = admin.post(f"/api/auth/users/{member.user['id']}/reset-link").json()
    assert r["mailed"] is True and outbox[0]["to"] == [member.user["email"]] and r["reset_url"] in outbox[0]["text"]
    guest = make_client(app)
    assert (
        guest.post("/api/auth/reset", json={"token": _token(first), "password": NEW_PASSWORD}).status_code == 404
    )  # replaced
    assert (
        guest.post("/api/auth/reset", json={"token": _token(r["reset_url"]), "password": NEW_PASSWORD}).status_code
        == 200
    )
    assert member.get("/api/me").status_code == 401 and guest.get("/api/me").json()["id"] == member.user["id"]
    assert login_as("member").post(f"/api/auth/users/{admin.user['id']}/reset-link").status_code == 403
    admin.post(f"/api/auth/users/{member.user['id']}/deactivate")
    for uid in (member.user["id"], 0, 999):  # deactivated, the system principal, unknown
        assert admin.post(f"/api/auth/users/{uid}/reset-link").status_code == 404


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
    assert (
        make_client(app)
        .post("/api/auth/login", json={"email": member.user["email"], "password": NEW_PASSWORD})
        .status_code
        == 200
    )


def test_first_time_setup_link_for_an_invite_added_without_mail(login_as, app, outbox):
    admin = login_as("admin")
    r = admin.post("/api/auth/users", json={"email": "late@example.com", "name": "Late", "send_email": False})
    assert r.status_code == 200 and r.json()["mailed"] is False and r.json()["invite_url"] and outbox == []
    member = login_as("member")
    guest = make_client(app)
    answers = [
        guest.post("/api/auth/forgot", json={"email": email})
        for email in ("nobody@example.com", member.user["email"], "LATE@example.com")
    ]
    assert {(a.status_code, a.text) for a in answers} == {(202, '{"mail":true}')}  # identical either way
    reset, setup = outbox
    assert reset["subject"].startswith("Reset your") and "/reset-password/" in reset["text"]
    assert setup["to"] == ["late@example.com"] and setup["subject"].startswith("Set up your")
    assert "set up your account" in setup["text"] and "password" not in setup["text"]
    url = next(word for word in setup["text"].split() if "/invite/" in word)
    assert guest.get(f"/api/auth/invite/{_token(url)}").json()["email"] == "late@example.com"
    r = guest.post(f"/api/auth/invite/{_token(url)}", json={"password": NEW_PASSWORD})
    assert r.status_code == 200 and guest.get("/api/me").json()["email"] == "late@example.com"
    make_client(app).post("/api/auth/forgot", json={"email": "late@example.com"})
    assert outbox[-1]["subject"].startswith("Reset your")  # set up now: back to the reset wording


def test_invite_mail_points_at_first_time_here(login_as, outbox):
    _invite(login_as("admin"))
    assert 'go to http://localhost:8000/login and choose "First time here?"' in outbox[0]["text"]


# ── Sign-up allow list ───────────────────────────────────────────────────────

ALLOW = ["@example.com", "pat@example.org"]


def _allow(admin, entries=ALLOW):
    r = admin.put("/api/core/settings", json={"values": {"auth.signup_allow": entries}})
    assert r.status_code == 200, r.text
    return r.json()["values"]["auth.signup_allow"]


def _users(email):
    return core_db.rows("SELECT * FROM core_users WHERE email = ?", (email,))


def _signup_link(app, outbox, email="someone@example.com"):
    assert make_client(app).post("/api/auth/forgot", json={"email": email}).status_code == 202
    return _token(next(w for w in outbox[-1]["text"].split() if "/invite/" in w))


def test_matching_is_the_whole_domain_or_the_exact_address(login_as):
    admin = login_as("admin")
    assert not invites.signup_allowed("someone@example.com")  # empty list: nobody
    _allow(admin)
    for email, allowed in (
        ("X@Example.COM", True),
        (" someone@example.com ", True),
        ("x@sub.example.com", False),
        ("x@badexample.com", False),
        ("x@example.com.evil.test", False),
        ("pat@example.org", True),
        ("PAT@example.org", True),
        ("sam@example.org", False),
        ("@example.com", False),
        ("a@b@example.com", False),
        ("a b@example.com", False),
        ("", False),
    ):
        assert invites.signup_allowed(email) is allowed, email


def test_the_setting_accepts_only_domains_and_addresses_and_cleans_them(login_as):
    admin = login_as("admin")
    assert _allow(admin, [" @Example.COM", "Pat@Example.org", "@example.com", ""]) == [
        "@example.com",
        "pat@example.org",
    ]
    for bad in (["example.com"], ["@"], ["a@b@c.com"], ["@nodot"], ["@.example.com"], ["@example.com-"], "@x.com", [5]):
        r = admin.put("/api/core/settings", json={"values": {"auth.signup_allow": bad}})
        assert r.status_code == 422, bad
    assert keys.get("auth.signup_allow") == ["@example.com", "pat@example.org"]
    assert login_as("member").put("/api/core/settings", json={"values": {"auth.signup_allow": []}}).status_code == 403


def test_a_listed_and_an_unlisted_address_get_the_same_answer(login_as, app, outbox):
    _allow(login_as("admin"))
    listed = make_client(app).post("/api/auth/forgot", json={"email": "someone@example.com"})
    assert len(outbox) == 1 and outbox[0]["to"] == ["someone@example.com"]
    assert outbox[0]["subject"].startswith("Set up your") and "/invite/" in outbox[0]["text"]
    unlisted = make_client(app).post("/api/auth/forgot", json={"email": "someone@other.com"})
    assert (listed.status_code, listed.json()) == (unlisted.status_code, unlisted.json()) == (202, {"mail": True})
    assert len(outbox) == 1
    assert _users("someone@example.com") == [] and _users("someone@other.com") == []


def test_self_sign_up_end_to_end(login_as, app, outbox):
    admin = login_as("admin")
    _allow(admin)
    token = _signup_link(app, outbox, "Someone@Example.com")
    guest = make_client(app)
    assert guest.get(f"/api/auth/invite/{token}").json() == {
        "email": "someone@example.com",
        "name": "",
        "google": False,
    }
    assert _users("someone@example.com") == []
    assert guest.post(f"/api/auth/invite/{token}", json={"password": "short"}).status_code == 422
    r = guest.post(f"/api/auth/invite/{token}", json={"password": NEW_PASSWORD})
    assert r.status_code == 200 and COOKIE in guest.cookies
    me = guest.get("/api/me")
    assert me.status_code == 200 and me.json()["role"] == "member"
    row = next(u for u in admin.get("/api/auth/users").json() if u["email"] == "someone@example.com")
    assert row["self_signup"] is True and row["invited_by"] is None and row["role"] == "member"
    # single use: the account exists now
    assert guest.get(f"/api/auth/invite/{token}").status_code == 404
    assert make_client(app).post(f"/api/auth/invite/{token}", json={"password": "another-password"}).status_code == 404
    assert len(_users("someone@example.com")) == 1


def _mint(claims, purpose="signup", seconds=3600):
    return jwt.mint_purpose(purpose, claims, seconds)


def test_bad_signup_links_create_nothing(login_as, app):
    _allow(login_as("admin"))
    good = _mint({"email": "someone@example.com"})
    for token in (
        _mint({"email": "someone@example.com"}, seconds=-1),  # expired
        good[:-2] + ("AA" if not good.endswith("AA") else "BB"),  # tampered
        _mint({"email": "someone@example.com"}, purpose="challenge"),
        _mint({}),
        _mint({"email": 5}),
        _mint({"email": ""}),
        _mint({"email": "someone@other.com"}),  # never on the list
    ):
        guest = make_client(app)
        assert guest.get(f"/api/auth/invite/{token}").status_code == 404
        assert guest.post(f"/api/auth/invite/{token}", json={"password": NEW_PASSWORD}).status_code == 404
    # a signup link is not a reset link
    r = make_client(app).post("/api/auth/reset", json={"token": good, "password": NEW_PASSWORD})
    assert r.status_code == 404
    assert core_db.one("SELECT count(*) AS n FROM core_users WHERE email LIKE 'someone@%'")["n"] == 0


def test_an_invite_sent_after_the_link_wins(login_as, app, outbox):
    admin = login_as("admin")
    _allow(admin)
    token = _signup_link(app, outbox)
    invited = _invite(admin, "someone@example.com")["user"]
    guest = make_client(app)
    assert guest.get(f"/api/auth/invite/{token}").status_code == 404
    assert guest.post(f"/api/auth/invite/{token}", json={"password": NEW_PASSWORD}).status_code == 404
    (row,) = _users("someone@example.com")
    assert row["id"] == invited["id"] and row["password_hash"] == "!" and row["self_signup"] == 0


def test_removing_the_entry_stops_an_outstanding_link(login_as, app, outbox):
    admin = login_as("admin")
    _allow(admin)
    token = _signup_link(app, outbox)
    _allow(admin, ["pat@example.org"])
    guest = make_client(app)
    assert guest.get(f"/api/auth/invite/{token}").status_code == 404
    assert guest.post(f"/api/auth/invite/{token}", json={"password": NEW_PASSWORD}).status_code == 404
    assert _users("someone@example.com") == []


def test_a_deactivated_account_does_not_come_back_by_signing_up(login_as, app, outbox):
    admin = login_as("admin")
    _allow(admin)
    gone = _invite(admin, "gone@example.com")["user"]
    assert admin.post(f"/api/auth/users/{gone['id']}/deactivate").status_code == 200
    outbox.clear()
    assert make_client(app).post("/api/auth/forgot", json={"email": "gone@example.com"}).status_code == 202
    assert outbox == []


def test_an_ordinary_invite_still_works_with_a_list_set(login_as, app):
    admin = login_as("admin")
    _allow(admin)
    token = _token(_invite(admin, "pat@example.org")["invite_url"])
    guest = make_client(app)
    assert guest.get(f"/api/auth/invite/{token}").json()["name"] == "New Person"
    r = guest.post(f"/api/auth/invite/{token}", json={"password": NEW_PASSWORD})
    assert r.status_code == 200
    (row,) = _users("pat@example.org")
    assert row["self_signup"] == 0 and row["invited_by"] == admin.user["id"]


def test_logs_mask_a_signup_link(app):
    token = _mint({"email": "someone@example.com"})
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, "GET /api/auth/invite/%s", (token,), None)
    logscrub.ScrubTokens().filter(record)
    assert record.getMessage() == "GET /api/auth/invite/***" and "eyJ" not in record.getMessage()
