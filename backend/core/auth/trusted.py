"""Trusted devices: a browser that passed the TOTP step may skip it for 30 days.

The `sf_trusted` cookie holds a random token; only its sha256 is stored, keyed to one user, so
two people sharing a browser never inherit each other's trust. Enabling or disabling TOTP, a
password change or reset, and deactivation all forget the user's devices.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Request, Response

from backend.core import clock, db
from backend.core.auth import service
from backend.core.auth.deps import User, current_user

COOKIE = "sf_trusted"
DAYS = 30
PATH = "/api/auth"  # only the sign-in routes need to see it

router = APIRouter(tags=["auth"])


def is_trusted(request: Request, user_id: int) -> bool:
    token = request.cookies.get(COOKIE)
    return bool(token) and db.one(
        "SELECT 1 AS ok FROM core_trusted_devices WHERE token_hash = ? AND user_id = ? AND expires_at > ?",
        (service.token_hash(token), user_id, clock.now_iso()),
    ) is not None


def trust(request: Request, response: Response, user_id: int) -> None:
    token = secrets.token_urlsafe(32)
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO core_trusted_devices (token_hash, user_id, label, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
            (service.token_hash(token), user_id, request.headers.get("user-agent", "")[:100],
             clock.later(DAYS * 86400), clock.now_iso()),
        )
    response.set_cookie(
        COOKIE, token, max_age=DAYS * 86400, httponly=True, samesite="lax", secure=request.url.scheme == "https", path=PATH
    )


@router.get("/api/auth/trusted-devices")
def trusted_devices(request: Request, user: User = Depends(current_user)) -> list[dict]:
    mine = service.token_hash(request.cookies.get(COOKIE, ""))
    rows = db.rows(
        """SELECT token_hash, label, created_at, expires_at FROM core_trusted_devices
            WHERE user_id = ? AND expires_at > ? ORDER BY created_at DESC""",
        (user.id, clock.now_iso()),
    )
    return [
        {"label": r["label"], "created_at": r["created_at"], "expires_at": r["expires_at"], "current": r["token_hash"] == mine}
        for r in rows
    ]


@router.delete("/api/auth/trusted-devices", status_code=204)
def forget_trusted_devices(request: Request, user: User = Depends(current_user)) -> Response:
    with db.transaction() as conn:
        conn.execute("DELETE FROM core_trusted_devices WHERE user_id = ?", (user.id,))
    response = Response(status_code=204)
    response.delete_cookie(COOKIE, path=PATH, httponly=True, samesite="lax", secure=request.url.scheme == "https")
    return response
