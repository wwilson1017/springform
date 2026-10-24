"""Session tokens: HS256 JWTs carrying `sub` (user id) and `pwd_epoch` (the user's token_epoch).

The role is deliberately not in the token: `current_user` reads the live row on every request,
so a demotion or deactivation bites on the next request rather than at expiry. Bumping
`core_users.token_epoch` ends every session that user holds.
"""

from datetime import UTC, datetime, timedelta

import jwt as pyjwt

from backend.core import settings

ALGORITHM = "HS256"
SESSION_HOURS = 12

InvalidToken = pyjwt.PyJWTError


def mint(user_id: int, token_epoch: int, hours: float = SESSION_HOURS) -> str:
    now = datetime.now(UTC)  # real time, not core.clock: expiry is a security property, not test data
    claims = {"sub": str(user_id), "pwd_epoch": int(token_epoch), "iat": now, "exp": now + timedelta(hours=hours)}
    return pyjwt.encode(claims, settings.secret_key(), algorithm=ALGORITHM)


def decode(token: str) -> dict:
    """The claims of a valid token; raises InvalidToken otherwise."""
    return pyjwt.decode(token, settings.secret_key(), algorithms=[ALGORITHM], options={"require": ["sub", "exp"]})
