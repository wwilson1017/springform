"""A person's always-allow rules (agent.md §6, "Always allow"): one live rule per user, agent and
tool lets that tool skip its Approve card in that user's chats with that agent. Which calls a rule
may cover is `engine.rule_eligible`. Rules are voided, never deleted.
"""

from __future__ import annotations

from backend.core import db
from backend.core.clock import now_iso


def live_in(conn: db.Conn, user_id: int, agent_id: int, tool: str) -> bool:
    return (
        conn.execute(
            """SELECT 1 FROM core_agent_approval_rules
                WHERE user_id = ? AND agent_id = ? AND tool = ? AND voided_at IS NULL""",
            (user_id, agent_id, tool),
        ).fetchone()
        is not None
    )


def live(user_id: int, agent_id: int, tool: str) -> bool:
    return live_in(db.get_conn(), user_id, agent_id, tool)


def create_in(conn: db.Conn, user_id: int, agent_id: int, tool: str) -> None:
    """Save a live rule; a second save of the same rule is a no-op (the partial unique index)."""
    conn.execute(
        "INSERT OR IGNORE INTO core_agent_approval_rules (user_id, agent_id, tool, created_at) VALUES (?, ?, ?, ?)",
        (user_id, agent_id, tool, now_iso()),
    )


def create(user_id: int, agent_id: int, tool: str) -> None:
    with db.transaction() as conn:
        create_in(conn, user_id, agent_id, tool)


def list_for(user_id: int) -> list[dict]:
    """The user's live rules, newest first."""
    return db.rows(
        """SELECT r.id, r.tool, a.slug AS agent_slug, a.name AS agent_name, r.created_at
             FROM core_agent_approval_rules r JOIN core_agents a ON a.id = r.agent_id
            WHERE r.user_id = ? AND r.voided_at IS NULL ORDER BY r.id DESC""",
        (user_id,),
    )


def void_in(conn: db.Conn, rule_id: int, user_id: int, reason: str) -> bool:
    """Void the user's own live rule; False when it is not theirs or already void."""
    return (
        conn.execute(
            """UPDATE core_agent_approval_rules SET voided_at = ?, void_reason = ?
                WHERE id = ? AND user_id = ? AND voided_at IS NULL""",
            (now_iso(), reason, rule_id, user_id),
        ).rowcount
        > 0
    )


def void(rule_id: int, user_id: int, reason: str) -> bool:
    with db.transaction() as conn:
        return void_in(conn, rule_id, user_id, reason)
