"""Invites, forgotten passwords and password changes.

An admin adds a person: a user row with the `'!'` hash (it never authenticates) and a one-hour
invite link, `PUBLIC_URL/invite/<token>`. The link is always returned to the admin to copy and
is also mailed when mail is configured. The invitee sets a password there, or presses the
Google button, which links whichever Google account they pick (the token proved the mailbox).
Resending issues a new link; the old one stops working. Links are single use.

Forgot password mails a one-hour `PUBLIC_URL/reset-password/<token>` link when the account
exists and mail is configured, and answers the same 202 either way. An account never set up (no
password, no Google link) is mailed a fresh invite link worded "set up your account" instead: the
sign-in page's "First time here?" entry is this same request, so an expired invite needs no admin.
An address with no account at all that matches the sign-up allow list (`auth.signup_allow`) is
mailed the same setup email, but its link carries a signed one-hour JWT (purpose `signup`) rather
than a stored token: no account exists until the person sets a password there, which creates a
member with `self_signup` set. Without mail, an admin issues
the same link from the Users card and passes it on (it is also mailed when mail is configured). A reset or a password
change ends every other session and forgets trusted devices. Accepting an invite and resetting
a password both end like a password sign-in: a session, or the TOTP challenge when 2FA is on.
"""

from __future__ import annotations

from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from backend.core import db, ratelimit, settings
from backend.core.auth import google, jwt, mail, service, totp
from backend.core.auth.deps import User, current_user, require_admin, start_session
from backend.core.errors import Conflict, Invalid, NotFound
from backend.core.platform import keys

INVITE_PATH, RESET_PATH = "/invite/", "/reset-password/"
FORGOT_LIMITS = ((3, 3600), (20, 3600))  # per email, per address
CHANGE_LIMIT = (5, 300)  # per user

router = APIRouter(tags=["auth"])


def _host() -> str:
    return urlparse(settings.public_url()).hostname or "Springform"


def _expired_hint() -> str:
    return f'If the link has expired, go to {settings.public_url()}/login and choose "First time here?".'


def _send_invite(inviter: User, row: dict, url: str) -> bool:
    return mail.send(
        row["email"],
        f"You're invited to {_host()}",
        f"{inviter.name or inviter.email} invited you to {_host()}.\n\n"
        f"Open this link within an hour to set up your account:\n{url}\n\n"
        f"{_expired_hint()}\n\n"
        "If you weren't expecting this, you can ignore this message.",
    )


def _send_setup(address: str, url: str) -> bool:
    return mail.send(
        address,
        f"Set up your {_host()} account",
        f"A setup link was requested for {address} on {_host()}.\n\n"
        f"Open this link within an hour to set up your account:\n{url}\n\n"
        f"{_expired_hint()}\n\n"
        "If you weren't expecting this, you can ignore this message.",
    )


def _send_reset(address: str, url: str) -> bool:
    return mail.send(
        address,
        f"Reset your {_host()} password",
        f"A password reset was requested for {address} on {_host()}.\n\n"
        f"Open this link within an hour to choose a new one:\n{url}\n\n"
        "If you weren't expecting this, ignore this message; your password has not changed.",
    )


def invite(admin: User, email: str, name: str, role: str, send_email: bool = True) -> dict:
    with db.transaction() as conn:
        row = service.create_user_in(conn, email, name, role, None, invited_by=admin.id)
        token = service.issue_token_in(conn, row["id"], "invite", admin.id)
    url = settings.public_url() + INVITE_PATH + token
    mailed = send_email and _send_invite(admin, row, url)
    return {"user": service.admin_view(row), "invite_url": url, "mailed": mailed}


def resend(admin: User, user_id: int) -> dict:
    with db.transaction() as conn:
        row = service.human_in(conn, user_id)
        if not row["is_active"]:
            raise Conflict("user_inactive")
        if service.has_password(row["password_hash"]) or row["google_sub"]:
            raise Conflict("invite_accepted")
        token = service.issue_token_in(conn, user_id, "invite", admin.id)
    url = settings.public_url() + INVITE_PATH + token
    return {"invite_url": url, "mailed": _send_invite(admin, row, url)}


def reset_link(admin: User, user_id: int) -> dict:
    """A one-hour reset link for an active human account, issued by an admin (the forgot-password
    link when mail is off); the user's earlier unused reset link stops working."""
    with db.transaction() as conn:
        row = service.human_in(conn, user_id)
        if not row["is_active"]:
            raise NotFound()
        token = service.issue_token_in(conn, user_id, "reset", admin.id)
    url = settings.public_url() + RESET_PATH + token
    return {"reset_url": url, "mailed": _send_reset(row["email"], url)}


def signup_allowed(email: str) -> bool:
    """Whether an address may sign up on its own: it, or its whole domain (`@domain`, no
    subdomains), is on the `auth.signup_allow` list."""
    email = service.normalize_email(email)
    local, _, domain = email.partition("@")
    if not local or not domain or "@" in domain or any(c.isspace() for c in email):
        return False
    allow = keys.get("auth.signup_allow") or []
    return email in allow or "@" + domain in allow


def _signup_email(token: str) -> str | None:
    """The address a signup link was minted for, while it is still on the allow list."""
    try:
        email = jwt.decode_purpose(token, "signup").get("email")
    except jwt.InvalidToken:
        return None
    if not isinstance(email, str) or not email or not signup_allowed(email):
        return None
    return service.normalize_email(email)


def _set_password_by_token(token: str, purpose: str, password: str) -> dict:
    service.validate_password(password)
    hashed = service.hash_password(password)
    with db.transaction() as conn:
        row = service.spend_token_in(conn, token, purpose)
        if not row and purpose == "invite" and (email := _signup_email(token)):
            try:
                row = service.create_user_in(conn, email, "", "member", None, self_signup=True)
            except Conflict:  # the account exists already: the link was used, or an admin added them
                raise NotFound() from None
        if not row:
            raise NotFound()
        service.set_password_in(conn, row["id"], hashed)
    return db.must(service.get_user(row["id"]))


def forgot(email: str, ip: str) -> tuple[str, str, bool] | None:
    """(address, url, setup) to mail when the account exists and mail is on; None otherwise.
    `setup` is true for an account never set up: its link is a fresh invite (the one the admin
    sent stops working, as on a resend), mailed only to the account's own address. An address
    with no account that the allow list admits gets a signup link, also with `setup` true."""
    email = service.normalize_email(email)
    per_email, per_ip = FORGOT_LIMITS
    with db.transaction() as conn:
        if service.over_limit_in(conn, f"forgot:{email}", *per_email) or service.over_limit_in(
            conn, f"forgot-ip:{ip}", *per_ip
        ):
            raise service.RateLimited()
        row = conn.execute(
            """SELECT id, email, password_hash, google_sub FROM core_users
                WHERE lower(trim(email)) = ? AND is_active = 1 AND role != 'system'""",
            (email,),
        ).fetchone()
        if not mail.configured():
            return None
        if not row:
            taken = conn.execute("SELECT 1 FROM core_users WHERE lower(trim(email)) = ?", (email,)).fetchone()
            if taken or not signup_allowed(email):  # a deactivated account does not come back this way
                return None
            signup = jwt.mint_purpose("signup", {"email": email}, service.TOKEN_SECONDS)
            return email, settings.public_url() + INVITE_PATH + signup, True
        setup = not service.has_password(row["password_hash"]) and not row["google_sub"]
        token = service.issue_token_in(conn, row["id"], "invite" if setup else "reset")
    return row["email"], settings.public_url() + (INVITE_PATH if setup else RESET_PATH) + token, setup


def change_password(user_id: int, current: str, new: str) -> dict:
    service.validate_password(new)
    with db.transaction() as conn:
        if service.over_limit_in(conn, f"pwchange:{user_id}", *CHANGE_LIMIT):
            raise service.RateLimited()
    stored = db.must(service.get_user(user_id))["password_hash"]
    if not service.verify_password(current, stored):
        raise Invalid("wrong_password")
    hashed = service.hash_password(new)
    with db.transaction() as conn:
        now = conn.execute("SELECT password_hash FROM core_users WHERE id = ?", (user_id,)).fetchone()[0]
        if now != stored:  # changed by a concurrent request since the check above
            raise Invalid("wrong_password")
        service.set_password_in(conn, user_id, hashed)
    return db.must(service.get_user(user_id))


# ── Routes ───────────────────────────────────────────────────────────────────


class InviteIn(BaseModel):
    email: str
    name: str = ""
    role: str = "member"
    send_email: bool = True


class AcceptIn(BaseModel):
    password: str


class ForgotIn(BaseModel):
    email: str


class ResetIn(BaseModel):
    token: str
    password: str


class PasswordIn(BaseModel):
    current: str
    new: str


class ResetLink(BaseModel):
    reset_url: str
    mailed: bool


@router.post("/api/auth/users")
def invite_user(body: InviteIn, admin: User = Depends(require_admin)) -> dict:
    return invite(admin, body.email, body.name, body.role, body.send_email)


@router.post("/api/auth/users/{user_id}/resend-invite")
def resend_invite(user_id: int, admin: User = Depends(require_admin)) -> dict:
    return resend(admin, user_id)


@router.post("/api/auth/users/{user_id}/reset-link", response_model=ResetLink)
def issue_reset_link(user_id: int, admin: User = Depends(require_admin)) -> dict:
    return reset_link(admin, user_id)


@router.get("/api/auth/invite/{token}")
def invite_details(token: str) -> dict:
    row = service.token_user_in(db.get_conn(), token, "invite")
    if row:
        return {"email": row["email"], "name": row["name"], "google": google.available()}
    email = _signup_email(token)
    if not email or service.get_user_by_email(email):
        raise NotFound()
    return {"email": email, "name": "", "google": False}  # no account to link Google to yet


@router.post("/api/auth/invite/{token}")
def accept_invite(token: str, body: AcceptIn, request: Request, response: Response) -> dict:
    return totp.complete(request, response, _set_password_by_token(token, "invite", body.password))


@router.post("/api/auth/forgot", status_code=202)
def forgot_password(body: ForgotIn, request: Request, background: BackgroundTasks) -> dict:
    try:
        found = forgot(body.email, ratelimit.client_key(request))
    except service.RateLimited:
        raise HTTPException(429, detail="rate_limited") from None
    if found:  # after the response, so its timing does not say whether the account exists
        address, url, setup = found
        background.add_task(_send_setup if setup else _send_reset, address, url)
    return {"mail": mail.configured()}


@router.post("/api/auth/reset")
def reset_password(body: ResetIn, request: Request, response: Response) -> dict:
    return totp.complete(request, response, _set_password_by_token(body.token, "reset", body.password))


@router.post("/api/auth/password")
def password_change(body: PasswordIn, request: Request, response: Response, user: User = Depends(current_user)) -> dict:
    try:
        row = change_password(user.id, body.current, body.new)
    except service.RateLimited:
        raise HTTPException(429, detail="rate_limited") from None
    return start_session(request, response, row)
