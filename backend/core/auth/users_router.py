"""User administration (admins) and self-service profile edits.

There is no delete: a departed person's name keeps rendering on the records they touched, so
accounts are deactivated. Deactivation ends every session, forgets trusted devices and unused
links, and runs `service.ON_DEACTIVATE` in the same transaction. The install always keeps one
active admin who can sign in. The system principal is never listed, edited or invited.
Inviting lives in invites.py (`POST /api/auth/users`).
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.core import db
from backend.core.auth import service, totp
from backend.core.auth.deps import User, current_user, require_admin

router = APIRouter(tags=["auth"])


class UserPatch(BaseModel):
    name: str | None = None
    role: str | None = None
    tz: str | None = None


class MePatch(BaseModel):
    name: str | None = None
    tz: str | None = None


def _view(row: dict) -> dict:
    return service.admin_view(row, totp.enabled(row["id"]))


@router.get("/api/auth/users")
def list_users(status: Literal["active", "inactive"] | None = None, admin: User = Depends(require_admin)) -> list[dict]:
    return service.list_users(None if status is None else status == "active")


@router.patch("/api/auth/users/{user_id}")
def patch_user(user_id: int, body: UserPatch, admin: User = Depends(require_admin)) -> dict:
    with db.transaction() as conn:
        row = service.update_user_in(conn, user_id, body.model_dump(exclude_unset=True))
    return _view(row)


@router.post("/api/auth/users/{user_id}/deactivate")
def deactivate_user(user_id: int, admin: User = Depends(require_admin)) -> dict:
    with db.transaction() as conn:
        row = service.deactivate_in(conn, user_id)
    return _view(row)


@router.post("/api/auth/users/{user_id}/reactivate")
def reactivate_user(user_id: int, admin: User = Depends(require_admin)) -> dict:
    with db.transaction() as conn:
        row = service.reactivate_in(conn, user_id)
    return _view(row)


@router.patch("/api/me")
def patch_me(body: MePatch, user: User = Depends(current_user)) -> dict:
    with db.transaction() as conn:
        row = service.update_user_in(conn, user.id, body.model_dump(exclude_unset=True))
    return User.from_row(row).public()
