"""Sign-in routes. The session is an httpOnly `sf_session` cookie (SameSite=Lax, 12 h).

This is the auth package's one discovered router; the TOTP, trusted-device, Google, invite and
user-admin routers are included into it below.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from backend.core import db, preview, settings
from backend.core.auth import bootstrap, google, invites, service, totp, trusted, users_router
from backend.core.auth.deps import COOKIE, User, current_user, start_session

router = APIRouter(tags=["auth"])
for _sub in (totp.router, trusted.router, google.router, invites.router, users_router.router):
    router.include_router(_sub)


class SetupIn(BaseModel):
    token: str
    email: str
    name: str = ""
    password: str


class LoginIn(BaseModel):
    email: str
    password: str


class PreviewIn(BaseModel):
    role: Literal["admin", "member"]


@router.get("/api/auth/status")
def get_status() -> dict:
    return {
        "setup_required": not service.human_users_exist(db.get_conn()),
        "google": google.available(),
        "preview": settings.preview_mode(),
    }


@router.post("/api/auth/setup")
def setup(body: SetupIn, request: Request, response: Response) -> dict:
    user = bootstrap.complete_setup(body.token, body.email, body.name, body.password)
    return start_session(request, response, user)


@router.post("/api/auth/login")
def login(body: LoginIn, request: Request, response: Response) -> dict:
    ip = request.client.host if request.client else "unknown"
    try:
        user = service.authenticate(body.email, body.password, ip)
    except service.RateLimited:
        raise HTTPException(429, detail="rate_limited") from None
    except service.InvalidCredentials:
        raise HTTPException(401, detail="invalid_credentials") from None
    return totp.complete(request, response, user)


@router.post("/api/auth/logout", status_code=204)
def logout(request: Request) -> Response:
    response = Response(status_code=204)
    response.delete_cookie(COOKIE, path="/", httponly=True, samesite="lax", secure=request.url.scheme == "https")
    return response


@router.post("/api/auth/preview")
def preview_login(body: PreviewIn, request: Request, response: Response) -> dict:
    user = service.get_user_by_email(preview.EMAILS[body.role]) if settings.preview_mode() else None
    if not user:
        raise HTTPException(404, detail="not_found")
    return start_session(request, response, user)


@router.get("/api/me")
def me(user: User = Depends(current_user)) -> dict:
    return user.public()
