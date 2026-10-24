"""Google sign-in (OpenID Connect): server-side authorization code + PKCE.

`start` sets the signed `sf_google` state cookie (state, nonce, PKCE verifier, plus `link` when
started from Settings or `invite` when started from an invite page) and redirects to Google
with prompt=select_account. `callback` matches the state to the cookie, exchanges the code
with httpx (never inside a transaction), verifies the ID token with google-auth, then checks
aud, iss, exp, nonce and email_verified itself.

Who that is:
- `sub` matches a user: that user. Once linked, `sub` is the identity; the email is not.
- Otherwise the email matches an active user with no `google_sub`, and Google is authoritative
  for the address (gmail.com / googlemail.com, or the `hd` claim equals the email's domain):
  link `sub` and sign in. Any other address links from a session instead: Settings → Link
  Google, or the invite page, whose token proves the mailbox.
- Otherwise refused with a redirect to `/login?error=...`. A user is never created here.
A Google sign-in skips local TOTP unless the setting `auth.require_totp_for_google` is on.

The client id and secret live in core_settings (encrypted). The redirect URI is PUBLIC_URL +
/api/auth/google/callback, never derived from the Host header. In PREVIEW_MODE `start` sends
the browser to a local stub page instead of Google, so end-to-end tests cover this path.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import logging
import re
import secrets
import time
from urllib.parse import quote, urlencode, urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from google.auth import transport as google_transport
from google.auth.exceptions import GoogleAuthError
from google.oauth2 import id_token
from pydantic import BaseModel

from backend.core import clock, db, preview, settings
from backend.core.auth import jwt, service, totp
from backend.core.auth.deps import User, current_user, require_admin, start_session
from backend.core.errors import Conflict

logger = logging.getLogger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ISSUERS = ("accounts.google.com", "https://accounts.google.com")
AUTHORITATIVE_DOMAINS = ("gmail.com", "googlemail.com")
CLIENT_ID, CLIENT_SECRET, REQUIRE_TOTP = "auth.google_client_id", "auth.google_client_secret", "auth.require_totp_for_google"
CLIENT_ID_SHAPE = re.compile(r"^\d+-[0-9a-z]+\.apps\.googleusercontent\.com$")
COOKIE, COOKIE_PATH, STATE_SECONDS = "sf_google", "/api/auth/google", 600
TRANSPORT: httpx.BaseTransport | None = None  # tests swap in an httpx.MockTransport

router = APIRouter(tags=["auth"])


class GoogleError(Exception):
    """The callback cannot trust this sign-in (exchange, signature or claim check failed)."""


def redirect_uri() -> str:
    return f"{settings.public_url()}/api/auth/google/callback"


def client() -> tuple[str, str]:
    return settings.get_setting(CLIENT_ID, "") or "", settings.get_setting(CLIENT_SECRET, "") or ""


def available() -> bool:
    return all(client()) or settings.preview_mode()


def authoritative(email: str, hd: str | None) -> bool:
    """Google vouches for this address: its own consumer domains, or the Workspace domain it hosts."""
    domain = email.rpartition("@")[2]
    return domain in AUTHORITATIVE_DOMAINS or (bool(hd) and str(hd).lower() == domain)


class _Response(google_transport.Response):
    def __init__(self, r: httpx.Response):
        self._r = r

    status = property(lambda self: self._r.status_code)
    headers = property(lambda self: self._r.headers)
    data = property(lambda self: self._r.content)


class _Request(google_transport.Request):
    """google-auth's HTTP seam over httpx (its bundled transports need requests or urllib3)."""

    # simplification: Google's certs are fetched on every sign-in; cache them per Cache-Control if volume grows.
    def __call__(self, url, method="GET", body=None, headers=None, timeout=None, **kwargs):
        with httpx.Client(transport=TRANSPORT, timeout=timeout or 15) as c:
            return _Response(c.request(method, url, content=body, headers=headers))


def check_claims(claims: dict, client_id: str, nonce: str) -> None:
    """Our own checks on top of google-auth's. Any failure raises GoogleError."""
    exp = claims.get("exp")
    for ok, what in (
        (claims.get("aud") == client_id, "aud"),
        (claims.get("iss") in ISSUERS, "iss"),
        (isinstance(exp, int | float) and exp > time.time(), "exp"),
        (hmac.compare_digest(str(claims.get("nonce", "")), nonce), "nonce"),
        (claims.get("email_verified") is True, "email_verified"),
        (bool(claims.get("sub")), "sub"),
    ):
        if not ok:
            raise GoogleError(f"ID token failed the {what} check")


def identity(code: str, saved: dict) -> dict:
    """The verified ID-token claims for an authorization code. Network: never inside transaction()."""
    if settings.preview_mode() and code.startswith("stub:"):
        role = code.removeprefix("stub:")
        if role not in preview.EMAILS:
            raise GoogleError("unknown preview account")
        return {"sub": f"preview-{role}", "email": preview.EMAILS[role], "email_verified": True, "hd": "example.com"}
    client_id, client_secret = client()
    if not (client_id and client_secret):
        raise GoogleError("Google sign-in is not configured")
    try:
        with httpx.Client(transport=TRANSPORT, timeout=15) as c:
            r = c.post(TOKEN_URL, data={
                "code": code, "client_id": client_id, "client_secret": client_secret, "redirect_uri": redirect_uri(),
                "grant_type": "authorization_code", "code_verifier": saved["verifier"],
            })
        r.raise_for_status()
        claims = id_token.verify_oauth2_token(r.json()["id_token"], _Request(), audience=client_id)
    except (httpx.HTTPError, KeyError, ValueError, GoogleAuthError) as e:
        raise GoogleError(f"{type(e).__name__}: {e}") from e
    check_claims(claims, client_id, saved["nonce"])
    return claims


def _usable(row: dict | None) -> bool:
    return bool(row) and bool(row["is_active"]) and row["role"] != "system"


def match(claims: dict) -> tuple[dict | None, str | None]:
    """(user row, None) to sign in, or (None, error code) per the linking rule."""
    hit = db.one("SELECT id FROM core_users WHERE google_sub = ?", (claims["sub"],))
    if hit:
        row = service.get_user(hit["id"])
        return (row, None) if _usable(row) else (None, "not_invited")
    email = service.normalize_email(claims.get("email", ""))
    row = service.get_user_by_email(email) if email else None
    if not _usable(row):
        return None, "not_invited"
    if row["google_sub"]:
        return None, "google_mismatch"
    if not authoritative(email, claims.get("hd")):
        return None, "link_required"
    try:
        with db.transaction() as conn:
            linked = conn.execute(
                "UPDATE core_users SET google_sub = ?, updated_at = ? WHERE id = ? AND google_sub IS NULL",
                (claims["sub"], clock.now_iso(), row["id"]),
            ).rowcount
    except db.sqlite3.IntegrityError:
        linked = 0
    return (service.get_user(row["id"]), None) if linked else (None, "google_mismatch")


def _set_sub_in(conn: db.Conn, user_id: int, sub: str) -> None:
    conn.execute("UPDATE core_users SET google_sub = ?, updated_at = ? WHERE id = ?", (sub, clock.now_iso(), user_id))


def link(user_id: int, sub: str) -> str | None:
    """Settings → Link Google, from a live session: any address. An error code, or None."""
    try:
        with db.transaction() as conn:
            _set_sub_in(conn, user_id, sub)
    except db.sqlite3.IntegrityError:
        return "google_in_use"
    return None


def accept_invite(token: str, sub: str) -> tuple[dict | None, str | None]:
    """The invite page's Google button: the token proved the mailbox, so link any address and spend it."""
    try:
        with db.transaction() as conn:
            row = service.spend_token_in(conn, token, "invite")
            if row:
                _set_sub_in(conn, row["id"], sub)
    except db.sqlite3.IntegrityError:
        return None, "google_in_use"
    return (service.get_user(row["id"]), None) if row else (None, "invite_invalid")


def _session_user(request: Request) -> User | None:
    try:
        return current_user(request)
    except HTTPException:
        return None


def _go(url: str) -> RedirectResponse:
    response = RedirectResponse(url, status_code=302)
    response.delete_cookie(COOKIE, path=COOKIE_PATH)
    return response


# ── Routes ───────────────────────────────────────────────────────────────────


@router.get("/api/auth/google/start")
def google_start(request: Request, link: bool = False, invite: str | None = None) -> RedirectResponse:
    if not available():
        return _go("/login?error=google_not_configured")
    extra: dict = {}
    if link:
        user = _session_user(request)
        if not user:
            return _go("/login")
        extra["link"] = user.id
    elif invite:
        if not service.token_user_in(db.get_conn(), invite, "invite"):
            return _go(f"/invite/{quote(invite, safe='')}?error=invite_invalid")
        extra["invite"] = invite
    state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    if settings.preview_mode():
        target = f"/api/auth/google/stub?{urlencode({'state': state})}"
    else:
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        target = AUTH_URL + "?" + urlencode({
            "client_id": client()[0], "redirect_uri": redirect_uri(), "response_type": "code", "scope": "openid email profile",
            "state": state, "nonce": nonce, "code_challenge": challenge, "code_challenge_method": "S256",
            "prompt": "select_account",
        })
    response = RedirectResponse(target, status_code=302)
    response.set_cookie(
        COOKIE, jwt.mint_purpose("google", {"state": state, "nonce": nonce, "verifier": verifier, **extra}, STATE_SECONDS),
        max_age=STATE_SECONDS, httponly=True, samesite="lax", secure=request.url.scheme == "https", path=COOKIE_PATH,
    )
    return response


@router.get("/api/auth/google/callback")
def google_callback(request: Request, state: str = "", code: str = "", error: str = "") -> RedirectResponse:
    try:
        saved = jwt.decode_purpose(request.cookies.get(COOKIE, ""), "google")
    except jwt.InvalidToken:
        saved = None
    if not saved or not hmac.compare_digest(str(saved.get("state", "")), state):
        return _go("/login?error=google_failed")
    invite = saved.get("invite")
    fail = "/settings?google_error=" if saved.get("link") else (f"/invite/{quote(invite, safe='')}?error=" if invite else "/login?error=")
    try:
        if error or not code:
            raise GoogleError(error or "no authorization code")
        claims = identity(code, saved)
    except GoogleError as e:
        logger.info("Google sign-in refused: %s", e)
        return _go(fail + "google_failed")
    if saved.get("link"):
        user = _session_user(request)
        if not user or user.id != saved["link"]:
            return _go("/login")
        err = link(user.id, claims["sub"])
        return _go((fail + err) if err else "/settings?google=linked")
    row, err = accept_invite(invite, claims["sub"]) if invite else match(claims)
    if err:
        return _go(fail + err)
    if settings.get_setting(REQUIRE_TOTP, False) and totp.needs_step(request, row):
        return _go("/login#" + urlencode({"totp_challenge": totp.challenge(row)}))
    response = _go("/")
    start_session(request, response, row)
    return response


@router.get("/api/auth/google/stub", response_class=HTMLResponse, include_in_schema=False)
def google_stub(state: str = "") -> str:
    """PREVIEW_MODE only: stands in for Google's account chooser."""
    if not settings.preview_mode():
        raise HTTPException(404, detail="not_found")
    items = "".join(
        f'<li><a href="/api/auth/google/callback?{html.escape(urlencode({"state": state, "code": f"stub:{role}"}))}">'
        f"{html.escape(email)}</a></li>"
        for role, email in preview.EMAILS.items()
    )
    return (
        "<!doctype html><meta charset=utf-8><title>Choose an account</title>"
        f"<h1>Choose an account</h1><p>Preview mode: this page stands in for Google.</p><ul>{items}</ul>"
    )


@router.get("/api/auth/google")
def google_status(user: User = Depends(current_user)) -> dict:
    row = service.get_user(user.id)
    return {"available": available(), "linked": bool(row["google_sub"]), "has_password": service.has_password(row["password_hash"])}


@router.post("/api/auth/google/unlink")
def google_unlink(user: User = Depends(current_user)) -> dict:
    if not service.has_password(service.get_user(user.id)["password_hash"]):
        raise Conflict("password_required")
    with db.transaction() as conn:
        conn.execute("UPDATE core_users SET google_sub = NULL, updated_at = ? WHERE id = ?", (clock.now_iso(), user.id))
    return {"linked": False}


class ConfigIn(BaseModel):
    client_id: str | None = None
    client_secret: str | None = None
    require_totp_for_google: bool | None = None


def _config() -> dict:
    client_id, client_secret = client()
    return {
        "client_id": client_id, "has_secret": bool(client_secret), "redirect_uri": redirect_uri(),
        "require_totp_for_google": bool(settings.get_setting(REQUIRE_TOTP, False)),
    }


@router.get("/api/auth/google/config")
def google_config(admin: User = Depends(require_admin)) -> dict:
    return _config()


@router.put("/api/auth/google/config")
def google_set_config(body: ConfigIn, admin: User = Depends(require_admin)) -> dict:
    with db.transaction() as conn:
        for key, value in ((CLIENT_ID, body.client_id), (CLIENT_SECRET, body.client_secret)):
            if value is not None:
                settings.set_setting_in(conn, key, value.strip(), admin.id, is_secret=True)
        if body.require_totp_for_google is not None:
            settings.set_setting_in(conn, REQUIRE_TOTP, body.require_totp_for_google, admin.id)
    return _config()


@router.post("/api/auth/google/test")
def google_test(admin: User = Depends(require_admin)) -> dict:
    """What an admin can verify without leaving Settings; Google itself is not contacted."""
    client_id, client_secret = client()
    uri = redirect_uri()
    problems = []
    if not CLIENT_ID_SHAPE.match(client_id):
        problems.append("The client ID should look like 1234567890-abc123.apps.googleusercontent.com.")
    if not client_secret:
        problems.append("No client secret is saved.")
    if not uri.startswith("https://") and urlparse(uri).hostname not in ("localhost", "127.0.0.1"):
        problems.append("Google only accepts an https redirect URI (except on localhost): set PUBLIC_URL to the https address.")
    return {
        "redirect_uri": uri, "client_id_valid": bool(CLIENT_ID_SHAPE.match(client_id)), "has_secret": bool(client_secret),
        "ok": not problems, "problems": problems,
    }
