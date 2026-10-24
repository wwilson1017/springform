"""The `core_agent_mcp_servers` table: admin CRUD and what discovery records. The token is
encrypted with the install key and never leaves this module except to the MCP client."""

from __future__ import annotations

import json
from contextlib import contextmanager

from backend.core import db, secrets
from backend.core.clock import now_iso
from backend.core.errors import Conflict, NotFound


def row(server_id: int) -> dict | None:
    return db.one("SELECT * FROM core_agent_mcp_servers WHERE id = ?", (server_id,))


def rows() -> list[dict]:
    return db.rows("SELECT * FROM core_agent_mcp_servers ORDER BY name, id")


def token(r: dict) -> str:
    return secrets.decrypt(r["token_enc"])


def view(r: dict) -> dict:
    return {
        "id": r["id"], "name": r["name"], "url": r["url"], "prefix": r["prefix"], "enabled": bool(r["enabled"]),
        "has_token": bool(r["token_enc"]), "tools": json.loads(r["tools_json"]),
        "last_discovered_at": r["last_discovered_at"], "last_error": r["last_error"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
    }


def get(server_id: int) -> dict:
    r = row(server_id)
    if r is None:
        raise NotFound("mcp_server_not_found")
    return view(r)


@contextmanager
def _unique_prefix():
    try:
        yield
    except db.sqlite3.IntegrityError:  # prefix is the table's only UNIQUE column
        raise Conflict("prefix_taken") from None


def create_in(conn: db.Conn, *, name: str, url: str, prefix: str, token: str = "") -> int:
    now = now_iso()
    with _unique_prefix():
        return conn.execute(
            """INSERT INTO core_agent_mcp_servers (name, url, token_enc, prefix, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (name, url, secrets.encrypt(token), prefix, now, now),
        ).lastrowid


def create(**fields) -> int:
    with db.transaction() as conn:
        return create_in(conn, **fields)


def update_in(conn: db.Conn, server_id: int, **fields) -> None:
    """Set the given fields (name, url, prefix, enabled, token; token "" clears it)."""
    if "token" in fields:
        fields["token_enc"] = secrets.encrypt(fields.pop("token"))
    if "enabled" in fields:
        fields["enabled"] = int(fields["enabled"])
    sets = "".join(f"{k} = ?, " for k in fields)  # keys are the router's model fields
    with _unique_prefix():
        changed = conn.execute(
            f"UPDATE core_agent_mcp_servers SET {sets}updated_at = ? WHERE id = ?", (*fields.values(), now_iso(), server_id)
        ).rowcount
    if not changed:
        raise NotFound("mcp_server_not_found")


def update(server_id: int, **fields) -> None:
    with db.transaction() as conn:
        update_in(conn, server_id, **fields)


def delete(server_id: int) -> None:
    with db.transaction() as conn:
        if not conn.execute("DELETE FROM core_agent_mcp_servers WHERE id = ?", (server_id,)).rowcount:
            raise NotFound("mcp_server_not_found")


def record_discovery(server_id: int, tools: list[dict], error: str | None, *, discovered: bool) -> None:
    """What the registry now holds for this server. `discovered` stamps last_discovered_at."""
    with db.transaction() as conn:
        conn.execute(
            """UPDATE core_agent_mcp_servers
                  SET tools_json = ?, last_error = ?, last_discovered_at = CASE WHEN ? THEN ? ELSE last_discovered_at END
                WHERE id = ?""",
            (json.dumps(tools), error, discovered, now_iso(), server_id),
        )
