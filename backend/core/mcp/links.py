"""Inbound MCP links: each one is an API key for its user (docs/agents/mcp.md §1).

The token is returned once, when the link is minted; only its sha256 is stored. A link works only
while it is unrevoked and its user is an active human account. Deactivating a user revokes every
link they have (registered on `auth.service.ON_DEACTIVATE` below), and the system principal can
never mint one.
"""

from __future__ import annotations

import hashlib
import secrets

from backend.core import clock, db, settings
from backend.core.auth import service as auth_service
from backend.core.auth.deps import User
from backend.core.errors import Forbidden, NotFound

TOUCH_SECONDS = 60  # last_used_at is written at most once a minute per link
_PUBLIC = "l.id, l.label, l.created_at, l.last_used_at"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def url_for(token: str) -> str:
    return f"{settings.public_url()}/mcp/{token}"


def mint(user: User, label: str) -> dict:
    """{id, label, created_at, last_used_at, url, token}: the only time the token is returned."""
    token = secrets.token_urlsafe(32)  # 256 bits, 43 URL-safe characters
    with db.transaction() as conn:
        live = conn.execute("SELECT role, is_active FROM core_users WHERE id = ?", (user.id,)).fetchone()
        if live is None or live["role"] == "system" or not live["is_active"]:
            raise Forbidden("cannot_mint_link")
        link_id = conn.execute(
            "INSERT INTO core_agent_mcp_links (user_id, token_hash, label, created_at) VALUES (?, ?, ?, ?)",
            (user.id, _hash(token), label.strip(), clock.now_iso()),
        ).lastrowid
        row = conn.execute(f"SELECT {_PUBLIC} FROM core_agent_mcp_links l WHERE l.id = ?", (link_id,)).fetchone()
    return {**dict(row), "url": url_for(token), "token": token}


def list_mine(user: User) -> list[dict]:
    return db.rows(
        f"SELECT {_PUBLIC} FROM core_agent_mcp_links l WHERE l.user_id = ? AND l.revoked_at IS NULL ORDER BY l.id",
        (user.id,),
    )


def list_all() -> list[dict]:
    """Every live link with its owner, for admins. Never a token or its hash."""
    return db.rows(
        f"""SELECT {_PUBLIC}, u.id AS user_id, u.name AS user_name, u.email AS user_email
              FROM core_agent_mcp_links l JOIN core_users u ON u.id = l.user_id
             WHERE l.revoked_at IS NULL ORDER BY u.name, l.id"""
    )


def revoke(user: User, link_id: int) -> None:
    """Revoke one of the caller's own links; anyone else's, or one already revoked, is not found."""
    with db.transaction() as conn:
        n = conn.execute(
            "UPDATE core_agent_mcp_links SET revoked_at = ? WHERE id = ? AND user_id = ? AND revoked_at IS NULL",
            (clock.now_iso(), link_id, user.id),
        ).rowcount
    if not n:
        raise NotFound("link not found")


def revoke_all_in(conn: db.Conn, user_id: int) -> None:
    conn.execute(
        "UPDATE core_agent_mcp_links SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
        (clock.now_iso(), user_id),
    )


def use(token: str) -> tuple[int, User] | None:
    """(link id, its user) for a live link, else None. Stamps last_used_at when it is due."""
    row = db.one(
        """SELECT l.id AS link_id, l.last_used_at, u.id, u.email, u.name, u.role, u.tz, u.is_active, u.token_epoch
             FROM core_agent_mcp_links l JOIN core_users u ON u.id = l.user_id
            WHERE l.token_hash = ? AND l.revoked_at IS NULL AND u.is_active = 1 AND u.role != 'system'""",
        (_hash(token),),
    )
    if row is None:
        return None
    if row["last_used_at"] is None or row["last_used_at"] <= clock.ago(TOUCH_SECONDS):
        with db.transaction() as conn:
            conn.execute("UPDATE core_agent_mcp_links SET last_used_at = ? WHERE id = ?", (clock.now_iso(), row["link_id"]))
    return row["link_id"], User.from_row(row)


if revoke_all_in not in auth_service.ON_DEACTIVATE:
    auth_service.ON_DEACTIVATE.append(revoke_all_in)
