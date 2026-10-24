"""Authenticator-app 2FA: per-user TOTP with an encrypted secret and bcrypt backup codes.

Enrolment is two steps: `enrol` stores a pending secret (enabled = 0) and returns it with its
`otpauth://` URI for the frontend to draw as a QR code; `confirm` proves the app holds it,
enables 2FA and returns ten backup codes, once. Turning 2FA on or off forgets trusted devices,
so every browser re-proves itself.

A code is accepted for the current 30-second step or one either side, and never twice: the
newest step used is kept in `core_totp.last_used_at` (a step number, despite the name), and a
code for that step or an earlier one is refused. A backup code works once. Every check counts
toward a per-user limit (TOTP_LIMIT). Time comes from `core.clock`, so tests can freeze it.

Sign-in becomes two steps for a user with 2FA on, unless the browser is trusted (`trusted.py`):
the first factor answers `{totp_required: true, challenge}` (a 5-minute signed token bound to
the user's token epoch) and `POST /api/auth/login/totp` completes it.
"""

from __future__ import annotations

import hmac
import json
import secrets
import string
from urllib.parse import urlparse

import bcrypt as _bcrypt
import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from backend.core import clock, db, settings
from backend.core.auth import jwt, service, trusted
from backend.core.auth.deps import User, current_user, start_session
from backend.core.errors import Conflict, Invalid
from backend.core.secrets import decrypt, encrypt

BACKUP_CODE_COUNT = 10
CHALLENGE_SECONDS = 300
TOTP_LIMIT = (5, 300)  # checks per window (seconds), per user, successes included

router = APIRouter(tags=["auth"])


# ── Service ──────────────────────────────────────────────────────────────────


def enabled(user_id: int) -> bool:
    return db.one("SELECT 1 AS ok FROM core_totp WHERE user_id = ? AND enabled = 1", (user_id,)) is not None


def enrol(user: User) -> dict:
    secret = pyotp.random_base32()
    secret_enc = encrypt(secret)
    now = clock.now_iso()
    with db.transaction() as conn:
        if conn.execute("SELECT 1 FROM core_totp WHERE user_id = ? AND enabled = 1", (user.id,)).fetchone():
            raise Conflict("totp_already_enabled")
        conn.execute(
            """INSERT INTO core_totp (user_id, enabled, secret_enc, backup_codes, last_used_at, created_at, updated_at)
               VALUES (?, 0, ?, '[]', '', ?, ?)
               ON CONFLICT (user_id) DO UPDATE SET secret_enc = excluded.secret_enc, backup_codes = '[]',
                                                  last_used_at = '', updated_at = excluded.updated_at""",
            (user.id, secret_enc, now, now),
        )
    issuer = urlparse(settings.public_url()).hostname or "Springform"
    return {"secret": secret, "otpauth_uri": pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=issuer)}


def _check_code_in(conn: db.Conn, user_id: int, code: str, is_enabled: bool) -> bool:
    row = conn.execute(
        "SELECT secret_enc, last_used_at FROM core_totp WHERE user_id = ? AND enabled = ?", (user_id, int(is_enabled))
    ).fetchone()
    secret = decrypt(row["secret_enc"]) if row else ""
    if not secret:
        return False
    totp, now, code = pyotp.TOTP(secret), clock.now(), (code or "").replace(" ", "")
    step = next((totp.timecode(now) + i for i in (-1, 0, 1) if hmac.compare_digest(totp.at(now, i), code)), None)
    if step is None or (row["last_used_at"] and int(row["last_used_at"]) >= step):
        return False
    conn.execute("UPDATE core_totp SET last_used_at = ?, updated_at = ? WHERE user_id = ?", (str(step), clock.now_iso(), user_id))
    return True


def _limited_in(conn: db.Conn, user_id: int) -> None:
    if service.over_limit_in(conn, f"totp:{user_id}", *TOTP_LIMIT):
        raise service.RateLimited()


def _new_backup_codes() -> tuple[list[str], list[str]]:
    """(codes shown once as XXXX-XXXX, their bcrypt hashes). Hash before any transaction: bcrypt is slow."""
    alphabet = string.ascii_uppercase + string.digits
    raw = ["".join(secrets.choice(alphabet) for _ in range(8)) for _ in range(BACKUP_CODE_COUNT)]
    hashes = [_bcrypt.hashpw(c.encode(), _bcrypt.gensalt(rounds=service.BCRYPT_ROUNDS)).decode() for c in raw]
    return [f"{c[:4]}-{c[4:]}" for c in raw], hashes


def _spend_backup_code(user_id: int, given: str) -> bool:
    code = given.strip().upper().replace("-", "").encode()
    row = db.one("SELECT backup_codes FROM core_totp WHERE user_id = ? AND enabled = 1", (user_id,))
    match = next((h for h in json.loads(row["backup_codes"]) if _bcrypt.checkpw(code, h.encode())), None) if row else None
    if match is None:
        return False
    with db.transaction() as conn:  # re-read under the lock: a code spent meanwhile is gone
        row = conn.execute("SELECT backup_codes FROM core_totp WHERE user_id = ? AND enabled = 1", (user_id,)).fetchone()
        hashes = json.loads(row["backup_codes"]) if row else []
        if match not in hashes:
            return False
        hashes.remove(match)
        conn.execute(
            "UPDATE core_totp SET backup_codes = ?, updated_at = ? WHERE user_id = ?", (json.dumps(hashes), clock.now_iso(), user_id)
        )
    return True


def verify(user_id: int, code: str | None = None, backup_code: str | None = None) -> bool:
    """A current TOTP code, or else an unused backup code; either is spent. Raises RateLimited."""
    with db.transaction() as conn:
        _limited_in(conn, user_id)
        if code:
            return _check_code_in(conn, user_id, code, is_enabled=True)
    return bool(backup_code) and _spend_backup_code(user_id, backup_code)


def confirm(user_id: int, code: str) -> list[str] | None:
    """Enable the pending secret when `code` matches it; the backup codes, or None for a wrong code."""
    codes, hashes = _new_backup_codes()
    with db.transaction() as conn:
        if not conn.execute("SELECT 1 FROM core_totp WHERE user_id = ? AND enabled = 0", (user_id,)).fetchone():
            raise Conflict("totp_not_pending")
        _limited_in(conn, user_id)
        if not _check_code_in(conn, user_id, code, is_enabled=False):
            return None
        conn.execute(
            "UPDATE core_totp SET enabled = 1, backup_codes = ?, updated_at = ? WHERE user_id = ?",
            (json.dumps(hashes), clock.now_iso(), user_id),
        )
        conn.execute("DELETE FROM core_trusted_devices WHERE user_id = ?", (user_id,))
    return codes


def disable_in(conn: db.Conn, user_id: int) -> None:
    conn.execute("DELETE FROM core_totp WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM core_trusted_devices WHERE user_id = ?", (user_id,))


def challenge(row: dict) -> str:
    return jwt.mint_purpose("totp", {"sub": str(row["id"]), "pwd_epoch": int(row["token_epoch"])}, CHALLENGE_SECONDS)


def needs_step(request: Request, row: dict) -> bool:
    return enabled(row["id"]) and not trusted.is_trusted(request, row["id"])


def complete(request: Request, response: Response, row: dict) -> dict:
    """The end of a first factor: a session, or a challenge when 2FA is on and the browser is not trusted."""
    if needs_step(request, row):
        return {"totp_required": True, "challenge": challenge(row)}
    return start_session(request, response, row)


# ── Routes ───────────────────────────────────────────────────────────────────


class CodeIn(BaseModel):
    code: str


class SecondFactorIn(BaseModel):
    code: str | None = None
    backup_code: str | None = None


class StepIn(SecondFactorIn):
    challenge: str
    trust_device: bool = False


def _rate_limited() -> HTTPException:
    return HTTPException(429, detail="rate_limited")


@router.get("/api/auth/totp")
def totp_status(user: User = Depends(current_user)) -> dict:
    row = db.one("SELECT backup_codes FROM core_totp WHERE user_id = ? AND enabled = 1", (user.id,))
    return {"enabled": row is not None, "backup_codes_left": len(json.loads(row["backup_codes"])) if row else 0}


@router.post("/api/auth/totp/enrol")
def totp_enrol(user: User = Depends(current_user)) -> dict:
    return enrol(user)


@router.post("/api/auth/totp/confirm")
def totp_confirm(body: CodeIn, user: User = Depends(current_user)) -> dict:
    try:
        codes = confirm(user.id, body.code)
    except service.RateLimited:
        raise _rate_limited() from None
    if codes is None:
        raise Invalid("invalid_code")
    return {"enabled": True, "backup_codes": codes}


@router.post("/api/auth/totp/disable")
def totp_disable(body: SecondFactorIn, user: User = Depends(current_user)) -> dict:
    if not enabled(user.id):
        raise Conflict("totp_not_enabled")
    try:
        ok = verify(user.id, body.code, body.backup_code)
    except service.RateLimited:
        raise _rate_limited() from None
    if not ok:
        raise Invalid("invalid_code")
    with db.transaction() as conn:
        disable_in(conn, user.id)
    return {"enabled": False}


@router.post("/api/auth/login/totp")
def login_totp(body: StepIn, request: Request, response: Response) -> dict:
    try:
        claims = jwt.decode_purpose(body.challenge, "totp")
        row = service.get_user(int(claims["sub"]))
    except (jwt.InvalidToken, KeyError, TypeError, ValueError):
        row = None
    if not row or not row["is_active"] or row["role"] == "system" or int(claims.get("pwd_epoch", -1)) != int(row["token_epoch"]):
        raise HTTPException(401, detail="challenge_expired")
    try:
        ok = verify(row["id"], body.code, body.backup_code)
    except service.RateLimited:
        raise _rate_limited() from None
    if not ok:
        raise HTTPException(401, detail="invalid_code")
    if body.trust_device:
        trusted.trust(request, response, row["id"])
    return start_session(request, response, row)
