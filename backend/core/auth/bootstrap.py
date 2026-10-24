"""First run: the first admin is created with a one-time setup token, never by "first visitor".

On boot with no human account (`role != 'system'`), `ensure_setup_token` makes a fresh token,
logs it once and writes it to `<data>/setup-token` (0600). `POST /api/auth/setup` must present
it; the admin is created under the write lock after re-checking that still no human account
exists, and the token is consumed. `python -m backend.cli create-admin EMAIL` is the other route.
"""

from __future__ import annotations

import logging
import os
import secrets

from backend.core import clock, db, settings
from backend.core.auth import service
from backend.core.errors import NotFound

logger = logging.getLogger(__name__)

TOKEN_FILE = "setup-token"


def setup_required() -> bool:
    return not service.human_users_exist(db.get_conn())


def ensure_setup_token() -> str | None:
    """A new setup token while no account exists (replacing any earlier one); None afterwards."""
    path = db.data_dir() / TOKEN_FILE
    token = secrets.token_urlsafe(32)
    with db.transaction() as conn:
        needed = not service.human_users_exist(conn)
        if needed:
            conn.execute("DELETE FROM core_login_tokens WHERE purpose = 'setup'")
            conn.execute(
                "INSERT INTO core_login_tokens (token_hash, purpose, created_at) VALUES (?, 'setup', ?)",
                (service.token_hash(token), clock.now_iso()),
            )
    if not needed:
        path.unlink(missing_ok=True)
        return None
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(token + "\n")
    os.chmod(path, 0o600)
    logger.warning("No account exists yet. Open %s/setup and enter this one-time setup token: %s", settings.public_url(), token)
    return token


def complete_setup(token: str, email: str, name: str, password: str) -> dict:
    """Create the first admin. NotFound when setup is over or the token is wrong."""
    service.validate_password(password)
    with db.transaction() as conn:
        if service.human_users_exist(conn):
            raise NotFound()
        found = conn.execute(
            "SELECT 1 FROM core_login_tokens WHERE token_hash = ? AND purpose = 'setup' AND used_at IS NULL",
            (service.token_hash(token),),
        ).fetchone()
        if not found:
            raise NotFound()
        user = service.create_user_in(conn, email, name, "admin", password)
        conn.execute(
            "UPDATE core_login_tokens SET used_at = ?, user_id = ? WHERE token_hash = ?",
            (clock.now_iso(), user["id"], service.token_hash(token)),
        )
    (db.data_dir() / TOKEN_FILE).unlink(missing_ok=True)
    logger.warning("Created the first admin account: %s", user["email"])
    return user


def create_admin(email: str, name: str, password: str) -> dict:
    """The operator's route (CLI): an admin at any time; also ends first-run setup."""
    with db.transaction() as conn:
        user = service.create_user_in(conn, email, name, "admin", password)
        conn.execute("UPDATE core_login_tokens SET used_at = ? WHERE purpose = 'setup' AND used_at IS NULL", (clock.now_iso(),))
    (db.data_dir() / TOKEN_FILE).unlink(missing_ok=True)
    return user
