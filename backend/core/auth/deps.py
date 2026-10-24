"""Request authentication: who is calling, and may they.

`current_user` reads the session from the `sf_session` cookie (the browser) or an
`Authorization: Bearer` header (tests, CLI), then loads the live user row, so a deactivation,
a role change or an epoch bump takes effect on the very next request. The system principal
can never authenticate over HTTP.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status

from backend.core.auth import jwt, service

COOKIE = "sf_session"


@dataclass(frozen=True)
class User:
    id: int
    email: str
    name: str
    role: str  # admin | member | system
    tz: str | None
    is_active: bool
    token_epoch: int

    @classmethod
    def from_row(cls, row: dict) -> User:
        return cls(
            id=int(row["id"]), email=row["email"], name=row["name"], role=row["role"], tz=row["tz"],
            is_active=bool(row["is_active"]), token_epoch=int(row["token_epoch"]),
        )

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def public(self) -> dict:
        return {"id": self.id, "email": self.email, "name": self.name, "role": self.role, "tz": self.tz}


def system_user() -> User:
    """The system principal (id 0) for unattended work: jobs and their tool runs."""
    return User.from_row(service.get_user(0))


def _unauthorized(detail: str = "not_authenticated") -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail, headers={"WWW-Authenticate": "Bearer"})


def request_token(request: Request) -> str | None:
    """The session token: the cookie wins when a request carries both."""
    token = request.cookies.get(COOKIE)
    if token:
        return token
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    return header[7:].strip() or None


def current_user(request: Request) -> User:
    token = request_token(request)
    if not token:
        raise _unauthorized()
    try:
        claims = jwt.decode(token)
        user_id = int(claims["sub"])
    except (jwt.InvalidToken, KeyError, TypeError, ValueError):
        raise _unauthorized("invalid_session") from None
    row = service.get_user(user_id)
    if (
        not row
        or row["role"] == "system"
        or not row["is_active"]
        or int(claims.get("pwd_epoch", -1)) != int(row["token_epoch"])
    ):
        raise _unauthorized("invalid_session")
    return User.from_row(row)


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="admin_only")
    return user


def require_roles(roles: Iterable[str]) -> Callable[..., User]:
    """Dependency: the caller holds one of `roles` (an app manifest's roles)."""
    allowed = frozenset(roles)

    def check(user: User = Depends(current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="forbidden")
        return user

    return check


def has_role(user: User, roles: Iterable[str], action: str = "read") -> bool:
    """Role check for entities, reports and tools an app registers. The system principal
    (only ever present in jobs) gets member-level reads and nothing else."""
    roles = frozenset(roles)
    if user.role == "system":
        return action == "read" and "member" in roles
    return user.is_active and user.role in roles
