"""Google sign-in against a mocked Google: the token endpoint and the certs URL are served by an
httpx.MockTransport, and ID tokens are signed with a test RSA key, so google-auth's real
signature check runs."""

import base64
import hashlib
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import jwt as pyjwt
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from backend.core import db as core_db, preview, settings
from backend.core.auth import google, service
from backend.core.auth.deps import COOKIE

from .conftest import PASSWORD, make_client
from .test_auth_totp import T0, code, enrol

CLIENT_ID = "1234567890-abc123.apps.googleusercontent.com"
CERTS_URL = "https://www.googleapis.com/oauth2/v1/certs"
KID = "test-key"


def _key_and_cert():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(1).not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()), (
        cert.public_bytes(serialization.Encoding.PEM).decode()
    )


PRIVATE_PEM, CERT_PEM = _key_and_cert()


class FakeGoogle:
    def __init__(self):
        self.id_token = ""
        self.exchanges: list[dict] = []
        self.token_status = 200

    def handler(self, request: httpx.Request) -> httpx.Response:
        if str(request.url) == CERTS_URL:
            return httpx.Response(200, json={KID: CERT_PEM})
        if str(request.url) == google.TOKEN_URL:
            self.exchanges.append({k: v[0] for k, v in parse_qs(request.content.decode()).items()})
            return httpx.Response(self.token_status, json={"id_token": self.id_token})
        return httpx.Response(404)

    def sign_in(self, client, *, query="", **claims):
        """Run start → (Google) → callback with an ID token carrying `claims`; returns the callback response."""
        r = client.get("/api/auth/google/start" + query, follow_redirects=False)
        assert r.status_code == 302, r.text
        params = self.start = parse_qs(urlparse(r.headers["location"]).query)
        if "nonce" not in params:  # start refused; hand back its redirect
            return r
        now = int(time.time())
        body = {
            "iss": "https://accounts.google.com", "aud": CLIENT_ID, "sub": "g-1", "email": "pat@gmail.com",
            "email_verified": True, "nonce": params["nonce"][0], "iat": now - 1, "exp": now + 600, **claims,
        }
        body = {k: v for k, v in body.items() if v is not None}
        self.id_token = pyjwt.encode(body, PRIVATE_PEM, algorithm="RS256", headers={"kid": KID})
        query = urlencode({"state": params["state"][0], "code": "auth-code"})
        return client.get(f"/api/auth/google/callback?{query}", follow_redirects=False)


@pytest.fixture
def fake_google(db, monkeypatch):
    monkeypatch.setenv("PUBLIC_URL", "https://crm.example.com")
    fake = FakeGoogle()
    monkeypatch.setattr(google, "TRANSPORT", httpx.MockTransport(fake.handler))
    settings.set_setting(google.CLIENT_ID, CLIENT_ID, None, is_secret=True)
    settings.set_setting(google.CLIENT_SECRET, "shh", None, is_secret=True)
    return fake


def _browser(app):
    return make_client(app)


def _sub(email):
    return service.get_user_by_email(email)["google_sub"]


def test_start_redirects_to_google_with_pkce_and_the_public_url(fake_google, app):
    browser = _browser(app)
    r = browser.get("/api/auth/google/start", headers={"Host": "evil.example"}, follow_redirects=False)
    target = urlparse(r.headers["location"])
    params = {k: v[0] for k, v in parse_qs(target.query).items()}
    assert f"{target.scheme}://{target.netloc}{target.path}" == google.AUTH_URL
    assert params["redirect_uri"] == "https://crm.example.com/api/auth/google/callback"
    assert params["client_id"] == CLIENT_ID and params["prompt"] == "select_account" and params["scope"] == "openid email profile"
    assert params["code_challenge_method"] == "S256"
    cookie = r.headers["set-cookie"]
    assert "sf_google=" in cookie and "HttpOnly" in cookie and "Path=/api/auth/google" in cookie
    fake_google.sign_in(browser)  # a full round trip, to see what the code exchange sent
    sent = fake_google.exchanges[-1]
    assert sent["redirect_uri"] == params["redirect_uri"] and sent["client_secret"] == "shh" and sent["code"] == "auth-code"
    challenge = base64.urlsafe_b64encode(hashlib.sha256(sent["code_verifier"].encode()).digest()).rstrip(b"=").decode()
    assert challenge == fake_google.start["code_challenge"][0] != params["code_challenge"]  # fresh per start


def test_invited_gmail_user_is_linked_and_then_known_by_sub_only(fake_google, app, make_user):
    make_user("member", email="pat@gmail.com", password=None)
    browser = _browser(app)
    r = fake_google.sign_in(browser, sub="g-pat")
    assert r.status_code == 302 and r.headers["location"] == "/"
    assert browser.get("/api/me").json()["email"] == "pat@gmail.com" and _sub("pat@gmail.com") == "g-pat"
    assert service.get_user_by_email("pat@gmail.com")["last_login_at"] is not None
    other = _browser(app)
    assert fake_google.sign_in(other, sub="g-pat", email="pat.renamed@gmail.com").headers["location"] == "/"
    assert other.get("/api/me").json()["email"] == "pat@gmail.com"


def test_uninvited_is_refused_and_nobody_is_created(fake_google, app):
    before = core_db.one("SELECT count(*) AS n FROM core_users")["n"]
    browser = _browser(app)
    r = fake_google.sign_in(browser, sub="g-stranger", email="stranger@gmail.com")
    assert r.headers["location"] == "/login?error=not_invited" and COOKIE not in browser.cookies
    assert core_db.one("SELECT count(*) AS n FROM core_users")["n"] == before


def test_non_google_address_links_only_from_a_session(fake_google, app, make_user):
    make_user("member", email="sam@acme.test")
    browser = _browser(app)
    assert fake_google.sign_in(browser, sub="g-sam", email="sam@acme.test").headers["location"] == "/login?error=link_required"
    assert _sub("sam@acme.test") is None
    assert browser.post("/api/auth/login", json={"email": "sam@acme.test", "password": PASSWORD}).status_code == 200
    assert browser.get("/api/auth/google").json() == {"available": True, "linked": False, "has_password": True}
    r = fake_google.sign_in(browser, query="?link=1", sub="g-sam", email="someone-else@gmail.com")
    assert r.headers["location"] == "/settings?google=linked" and _sub("sam@acme.test") == "g-sam"
    fresh = _browser(app)
    assert fake_google.sign_in(fresh, sub="g-sam", email="sam@acme.test").headers["location"] == "/"
    assert browser.post("/api/auth/google/unlink").json() == {"linked": False} and _sub("sam@acme.test") is None


def test_link_needs_a_session_and_a_free_sub(fake_google, app, make_user):
    make_user("member", email="a@acme.test")
    make_user("member", email="b@acme.test")
    with core_db.transaction() as conn:
        conn.execute("UPDATE core_users SET google_sub = 'g-taken' WHERE email = 'a@acme.test'")
    anonymous = _browser(app)
    assert anonymous.get("/api/auth/google/start?link=1", follow_redirects=False).headers["location"] == "/login"
    browser = _browser(app)
    browser.post("/api/auth/login", json={"email": "b@acme.test", "password": PASSWORD})
    r = fake_google.sign_in(browser, query="?link=1", sub="g-taken")
    assert r.headers["location"] == "/settings?google_error=google_in_use" and _sub("b@acme.test") is None


def test_workspace_hd_claim_is_authoritative_for_its_own_domain(fake_google, app, make_user):
    make_user("member", email="kim@acme.test", password=None)
    make_user("member", email="lee@acme.test", password=None)
    assert fake_google.sign_in(_browser(app), sub="g-kim", email="kim@acme.test", hd="acme.test").headers["location"] == "/"
    assert _sub("kim@acme.test") == "g-kim"
    r = fake_google.sign_in(_browser(app), sub="g-lee", email="lee@acme.test", hd="other.test")
    assert r.headers["location"] == "/login?error=link_required" and _sub("lee@acme.test") is None


def test_a_linked_account_refuses_a_different_google_account(fake_google, app, make_user):
    make_user("member", email="pat@gmail.com")
    fake_google.sign_in(_browser(app), sub="g-1")
    r = fake_google.sign_in(_browser(app), sub="g-2", email="pat@gmail.com")
    assert r.headers["location"] == "/login?error=google_mismatch" and _sub("pat@gmail.com") == "g-1"


@pytest.mark.parametrize(
    "claims",
    [
        {"aud": "someone-else.apps.googleusercontent.com"},
        {"iss": "https://evil.example"},
        {"nonce": "not-the-cookie-nonce"},
        {"email_verified": False},
        {"email_verified": None},
        {"exp": int(time.time()) - 60},
    ],
    ids=["aud", "iss", "nonce", "unverified", "no-email_verified", "expired"],
)
def test_bad_id_tokens_are_refused(fake_google, app, make_user, claims):
    make_user("member", email="pat@gmail.com")
    browser = _browser(app)
    r = fake_google.sign_in(browser, **claims)
    assert r.headers["location"] == "/login?error=google_failed" and COOKIE not in browser.cookies
    assert _sub("pat@gmail.com") is None


def test_token_signed_by_another_key_is_refused(fake_google, app, make_user):
    make_user("member", email="pat@gmail.com")
    other_pem, _ = _key_and_cert()
    browser = _browser(app)
    start = parse_qs(urlparse(browser.get("/api/auth/google/start", follow_redirects=False).headers["location"]).query)
    now = int(time.time())
    fake_google.id_token = pyjwt.encode(
        {"iss": "accounts.google.com", "aud": CLIENT_ID, "sub": "g-1", "email": "pat@gmail.com", "email_verified": True,
         "nonce": start["nonce"][0], "iat": now, "exp": now + 600},
        other_pem, algorithm="RS256", headers={"kid": KID},
    )
    r = browser.get(f"/api/auth/google/callback?{urlencode({'state': start['state'][0], 'code': 'c'})}", follow_redirects=False)
    assert r.headers["location"] == "/login?error=google_failed"


@pytest.mark.parametrize("bad", ["aud", "iss", "exp", "nonce", "email_verified", "sub"])
def test_explicit_claim_checks(bad):
    good = {"aud": CLIENT_ID, "iss": "accounts.google.com", "exp": time.time() + 60, "nonce": "n", "email_verified": True, "sub": "s"}
    google.check_claims(good, CLIENT_ID, "n")
    broken = {**good, bad: {"aud": "x", "iss": "google.com", "exp": time.time() - 1, "nonce": "m", "email_verified": "true", "sub": ""}[bad]}
    with pytest.raises(google.GoogleError, match=bad):
        google.check_claims(broken, CLIENT_ID, "n")


def test_state_must_match_the_cookie_and_failures_redirect(fake_google, app, make_user):
    make_user("member", email="pat@gmail.com")
    browser = _browser(app)
    start = parse_qs(urlparse(browser.get("/api/auth/google/start", follow_redirects=False).headers["location"]).query)
    assert browser.get("/api/auth/google/callback?state=forged&code=c", follow_redirects=False).headers["location"] == (
        "/login?error=google_failed"
    )
    stranger = _browser(app)  # no state cookie at all
    r = stranger.get(f"/api/auth/google/callback?{urlencode({'state': start['state'][0], 'code': 'c'})}", follow_redirects=False)
    assert r.headers["location"] == "/login?error=google_failed"
    fake_google.token_status = 400
    assert fake_google.sign_in(_browser(app)).headers["location"] == "/login?error=google_failed"
    fake_google.token_status = 200
    cancelled = _browser(app)
    start = parse_qs(urlparse(cancelled.get("/api/auth/google/start", follow_redirects=False).headers["location"]).query)
    r = cancelled.get(f"/api/auth/google/callback?{urlencode({'state': start['state'][0], 'error': 'access_denied'})}", follow_redirects=False)
    assert r.headers["location"] == "/login?error=google_failed"


def test_deactivated_and_system_accounts_are_refused(fake_google, app, make_user):
    user = make_user("member", email="pat@gmail.com")
    fake_google.sign_in(_browser(app), sub="g-pat")
    with core_db.transaction() as conn:
        service.deactivate_in(conn, user.id)
    assert fake_google.sign_in(_browser(app), sub="g-pat").headers["location"] == "/login?error=not_invited"
    r = fake_google.sign_in(_browser(app), sub="g-sys", email="system@springform.local", hd="springform.local")
    assert r.headers["location"] == "/login?error=not_invited" and service.get_user(0)["google_sub"] is None


def test_google_skips_totp_unless_the_setting_requires_it(fake_google, app, login_as, freeze):
    freeze(T0)
    member = login_as("member", email="pat@gmail.com")
    secret, _ = enrol(member)
    browser = _browser(app)
    assert fake_google.sign_in(browser, sub="g-pat").headers["location"] == "/"
    settings.set_setting(google.REQUIRE_TOTP, True, None)
    browser = _browser(app)
    r = fake_google.sign_in(browser, sub="g-pat")
    location = r.headers["location"]
    assert location.startswith("/login#totp_challenge=") and COOKIE not in browser.cookies
    challenge = parse_qs(urlparse(location).fragment)["totp_challenge"][0]
    r = browser.post("/api/auth/login/totp", json={"challenge": challenge, "code": code(secret, 1)})
    assert r.status_code == 200 and browser.get("/api/me").json()["email"] == "pat@gmail.com"


def test_invite_page_google_button_links_any_address_and_spends_the_token(fake_google, app, login_as):
    admin = login_as("admin")
    url = admin.post("/api/auth/users", json={"email": "new@acme.test", "name": "New", "role": "member"}).json()["invite_url"]
    token = url.rsplit("/", 1)[1]
    browser = _browser(app)
    r = fake_google.sign_in(browser, query=f"?invite={token}", sub="g-new", email="personal@gmail.com")
    assert r.headers["location"] == "/" and browser.get("/api/me").json()["email"] == "new@acme.test"
    assert _sub("new@acme.test") == "g-new"
    assert browser.get(f"/api/auth/invite/{token}").status_code == 404
    again = _browser(app).get(f"/api/auth/google/start?invite={token}", follow_redirects=False)
    assert again.headers["location"] == f"/invite/{token}?error=invite_invalid"


def test_invite_google_refuses_a_sub_linked_elsewhere(fake_google, app, login_as, make_user):
    make_user("member", email="old@gmail.com")
    fake_google.sign_in(_browser(app), sub="g-old", email="old@gmail.com")
    admin = login_as("admin")
    token = admin.post("/api/auth/users", json={"email": "x@acme.test"}).json()["invite_url"].rsplit("/", 1)[1]
    r = fake_google.sign_in(_browser(app), query=f"?invite={token}", sub="g-old")
    assert r.headers["location"] == f"/invite/{token}?error=google_in_use"
    assert _browser(app).get(f"/api/auth/invite/{token}").status_code == 200  # still usable with a password


def test_unlink_needs_a_password(fake_google, app, make_user):
    make_user("member", email="pat@gmail.com", password=None)
    browser = _browser(app)
    fake_google.sign_in(browser, sub="g-pat")
    assert browser.post("/api/auth/google/unlink").json() == {"detail": "password_required"}


def test_status_config_and_test_routes(db, app, login_as, monkeypatch):
    admin, member = login_as("admin"), login_as("member")
    assert admin.get("/api/auth/status").json()["google"] is False
    assert admin.get("/api/auth/google/start", follow_redirects=False).headers["location"] == "/login?error=google_not_configured"
    assert member.get("/api/auth/google/config").status_code == 403
    assert member.put("/api/auth/google/config", json={"client_id": "x"}).status_code == 403
    r = admin.put("/api/auth/google/config", json={"client_id": f" {CLIENT_ID} ", "client_secret": "s3cret"})
    assert r.json() == {
        "client_id": CLIENT_ID, "has_secret": True, "redirect_uri": "http://localhost:8000/api/auth/google/callback",
        "require_totp_for_google": False,
    }
    stored = core_db.rows("SELECT value, is_secret FROM core_settings WHERE key LIKE 'auth.google_%'")
    assert all(row["is_secret"] and "s3cret" not in row["value"] for row in stored)
    assert "s3cret" not in admin.get("/api/auth/google/config").text
    assert admin.get("/api/auth/status").json()["google"] is True
    assert admin.post("/api/auth/google/test").json() == {
        "redirect_uri": "http://localhost:8000/api/auth/google/callback", "client_id_valid": True, "has_secret": True,
        "ok": True, "problems": [],
    }
    monkeypatch.setenv("PUBLIC_URL", "http://crm.example.com")
    admin.put("/api/auth/google/config", json={"client_id": "nonsense", "require_totp_for_google": True})
    r = admin.post("/api/auth/google/test").json()
    assert r["ok"] is False and r["client_id_valid"] is False and len(r["problems"]) == 2
    assert settings.get_setting(google.REQUIRE_TOTP) is True
    admin.put("/api/auth/google/config", json={"client_secret": ""})
    assert admin.get("/api/auth/status").json()["google"] is False


def test_preview_stub_completes_the_callback_path(db, app, monkeypatch):
    browser = make_client(app)
    assert browser.get("/api/auth/google/stub?state=x").status_code == 404
    monkeypatch.setenv("PREVIEW_MODE", "1")
    preview.seed()
    r = browser.get("/api/auth/google/start", follow_redirects=False)
    assert r.headers["location"].startswith("/api/auth/google/stub?state=")
    page = browser.get(r.headers["location"])
    assert page.status_code == 200 and "preview-admin@example.com" in page.text
    link = next(a for a in page.text.split('href="')[1:] if "stub%3Aadmin" in a).split('"')[0].replace("&amp;", "&")
    r = browser.get(link, follow_redirects=False)
    assert r.headers["location"] == "/" and browser.get("/api/me").json()["email"] == "preview-admin@example.com"
    assert browser.get("/api/auth/google/callback?state=x&code=stub:admin", follow_redirects=False).headers["location"] == (
        "/login?error=google_failed"  # the stub still needs the state cookie
    )
