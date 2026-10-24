import pyotp

from backend.core import clock, db as core_db
from backend.core.auth import service, totp
from backend.core.auth.deps import COOKIE

from .conftest import PASSWORD, make_client

T0 = "2026-11-02T09:00:10Z"


def code(secret: str, steps: int = 0) -> str:
    """The code an authenticator shows `steps` 30-second steps from the frozen now."""
    return pyotp.TOTP(secret).at(clock.now(), steps)


def enrol(client) -> tuple[str, list[str]]:
    """Enable 2FA for the signed-in client; uses the current step's code."""
    secret = client.post("/api/auth/totp/enrol").json()["secret"]
    r = client.post("/api/auth/totp/confirm", json={"code": code(secret)})
    assert r.status_code == 200, r.text
    return secret, r.json()["backup_codes"]


def password_login(client, email):
    return client.post("/api/auth/login", json={"email": email, "password": PASSWORD})


def test_enrol_confirm_and_status(login_as, freeze):
    freeze(T0)
    member = login_as("member")
    assert member.get("/api/auth/totp").json() == {"enabled": False, "backup_codes_left": 0}
    r = member.post("/api/auth/totp/enrol").json()
    secret = r["secret"]
    assert r["otpauth_uri"].startswith("otpauth://totp/localhost:") and secret in r["otpauth_uri"]
    stored = core_db.one("SELECT secret_enc, enabled FROM core_totp WHERE user_id = ?", (member.user["id"],))
    assert stored["enabled"] == 0 and stored["secret_enc"].startswith("enc:v1:") and secret not in stored["secret_enc"]
    assert member.post("/api/auth/totp/confirm", json={"code": code(secret, 3)}).json() == {"detail": "invalid_code"}
    assert member.get("/api/auth/totp").json()["enabled"] is False
    r = member.post("/api/auth/totp/confirm", json={"code": code(secret)})
    assert r.status_code == 200 and r.json()["enabled"] is True
    backups = r.json()["backup_codes"]
    assert len(backups) == 10 and all(len(c) == 9 and c[4] == "-" for c in backups)
    assert member.get("/api/auth/totp").json() == {"enabled": True, "backup_codes_left": 10}
    assert member.post("/api/auth/totp/enrol").json() == {"detail": "totp_already_enabled"}
    assert member.post("/api/auth/totp/confirm", json={"code": code(secret)}).status_code == 409


def test_password_login_becomes_two_step_and_codes_never_replay(login_as, app, freeze):
    freeze(T0)
    member = login_as("member")
    secret, _ = enrol(member)  # spends the current step
    browser = make_client(app)
    r = password_login(browser, member.user["email"])
    assert r.status_code == 200 and r.json()["totp_required"] is True and set(r.json()) == {"totp_required", "challenge"}
    assert COOKIE not in browser.cookies and browser.get("/api/me").status_code == 401
    challenge = r.json()["challenge"]
    step = {"challenge": challenge}
    assert browser.post("/api/auth/login/totp", json={**step, "code": code(secret)}).json() == {"detail": "invalid_code"}
    r = browser.post("/api/auth/login/totp", json={**step, "code": code(secret, 1)})
    assert r.status_code == 200 and r.json()["user"]["email"] == member.user["email"]
    assert browser.get("/api/me").status_code == 200
    again = make_client(app)
    challenge2 = password_login(again, member.user["email"]).json()["challenge"]
    assert again.post("/api/auth/login/totp", json={"challenge": challenge2, "code": code(secret, 1)}).status_code == 401
    assert again.post("/api/auth/login/totp", json={"challenge": challenge2, "code": code(secret, -1)}).status_code == 401


def test_backup_code_works_once(login_as, app, freeze):
    freeze(T0)
    member = login_as("member")
    _, backups = enrol(member)
    browser = make_client(app)
    challenge = password_login(browser, member.user["email"]).json()["challenge"]
    r = browser.post("/api/auth/login/totp", json={"challenge": challenge, "backup_code": backups[0].lower().replace("-", "")})
    assert r.status_code == 200
    assert browser.get("/api/auth/totp").json() == {"enabled": True, "backup_codes_left": 9}
    assert browser.post("/api/auth/login/totp", json={"challenge": challenge, "backup_code": backups[0]}).status_code == 401
    assert browser.post("/api/auth/login/totp", json={"challenge": challenge, "code": backups[1]}).status_code == 401  # a code field takes TOTP only


def test_trusted_device_skips_the_step_for_that_user_only(login_as, app, freeze):
    freeze(T0)
    member = login_as("member")
    secret, _ = enrol(member)
    browser = make_client(app, **{"User-Agent": "Test Browser"})
    challenge = password_login(browser, member.user["email"]).json()["challenge"]
    r = browser.post("/api/auth/login/totp", json={"challenge": challenge, "code": code(secret, 1), "trust_device": True})
    assert "sf_trusted=" in r.headers["set-cookie"] and "Path=/api/auth" in r.headers["set-cookie"]
    assert browser.get("/api/auth/trusted-devices").json() == [
        {"label": "Test Browser", "created_at": T0, "expires_at": clock.later(30 * 86400), "current": True}
    ]
    browser.post("/api/auth/logout")
    assert password_login(browser, member.user["email"]).json()["user"]["id"] == member.user["id"]  # no step
    assert "totp_required" in password_login(make_client(app), member.user["email"]).json()  # another browser
    other = login_as("member")
    enrol(other)
    assert "totp_required" in password_login(browser, other.user["email"]).json()  # the trust is per user
    password_login(browser, member.user["email"])
    assert browser.delete("/api/auth/trusted-devices").status_code == 204
    assert browser.get("/api/auth/trusted-devices").json() == []
    assert "totp_required" in password_login(browser, member.user["email"]).json()


def test_trusted_device_expires(login_as, app, freeze):
    freeze(T0)
    member = login_as("member")
    secret, _ = enrol(member)
    browser = make_client(app)
    challenge = password_login(browser, member.user["email"]).json()["challenge"]
    browser.post("/api/auth/login/totp", json={"challenge": challenge, "code": code(secret, 1), "trust_device": True})
    browser.post("/api/auth/logout")
    assert "user" in password_login(browser, member.user["email"]).json()
    freeze("2026-12-02T09:00:11Z")
    assert "totp_required" in password_login(browser, member.user["email"]).json()


def test_disable_needs_a_code_and_forgets_devices(login_as, app, freeze):
    freeze(T0)
    member = login_as("member")
    secret, backups = enrol(member)
    with core_db.transaction() as conn:
        conn.execute(
            "INSERT INTO core_trusted_devices (token_hash, user_id, expires_at, created_at) VALUES ('x', ?, ?, ?)",
            (member.user["id"], clock.later(3600), T0),
        )
    assert member.post("/api/auth/totp/disable", json={"code": "000000"}).json() == {"detail": "invalid_code"}
    assert member.post("/api/auth/totp/disable", json={"backup_code": backups[2]}).json() == {"enabled": False}
    assert core_db.one("SELECT count(*) AS n FROM core_trusted_devices")["n"] == 0
    assert member.get("/api/auth/totp").json() == {"enabled": False, "backup_codes_left": 0}
    assert member.post("/api/auth/totp/disable", json={"code": code(secret, 1)}).json() == {"detail": "totp_not_enabled"}
    assert "user" in password_login(make_client(app), member.user["email"]).json()


def test_challenge_expires_and_never_stands_in_for_a_session(login_as, app, freeze, monkeypatch):
    freeze(T0)
    member = login_as("member")
    secret, _ = enrol(member)
    challenge = password_login(make_client(app), member.user["email"]).json()["challenge"]
    assert make_client(app, Authorization=f"Bearer {challenge}").get("/api/me").status_code == 401
    session = member.cookies[COOKIE]
    browser = make_client(app)
    r = browser.post("/api/auth/login/totp", json={"challenge": session, "code": code(secret, 1)})
    assert r.json() == {"detail": "challenge_expired"}
    with core_db.transaction() as conn:  # a password change between the steps voids the challenge
        service.bump_token_epoch_in(conn, member.user["id"])
    assert browser.post("/api/auth/login/totp", json={"challenge": challenge, "code": code(secret, 1)}).status_code == 401
    monkeypatch.setattr(totp, "CHALLENGE_SECONDS", -1)
    expired = password_login(browser, member.user["email"]).json()["challenge"]
    assert browser.post("/api/auth/login/totp", json={"challenge": expired, "code": code(secret, 1)}).json() == {
        "detail": "challenge_expired"
    }


def test_second_factor_rate_limit(login_as, app, freeze):
    freeze(T0)
    member = login_as("member")
    secret, _ = enrol(member)  # 1 check
    browser = make_client(app)
    challenge = password_login(browser, member.user["email"]).json()["challenge"]
    for _ in range(4):
        assert browser.post("/api/auth/login/totp", json={"challenge": challenge, "code": "123456"}).status_code == 401
    assert browser.post("/api/auth/login/totp", json={"challenge": challenge, "code": code(secret, 1)}).status_code == 429
    freeze("2026-11-02T09:05:11Z")
    challenge = password_login(browser, member.user["email"]).json()["challenge"]
    assert browser.post("/api/auth/login/totp", json={"challenge": challenge, "code": code(secret)}).status_code == 200
