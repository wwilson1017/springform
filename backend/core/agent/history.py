"""Conversations, messages and tool runs (ported from CakeCRM `assistant/history.py` to SQLite).

Conversations are private to their user, with no admin override: every conversation read here
takes the caller's `user_id` and answers None/[] for someone else's thread, exactly as for a
missing one. Message and tool-run helpers are conversation-scoped and are reached only after
that check.

Messages: one row per user message and per model iteration; an assistant row carries its tool
calls. Tool results live in `core_agent_tool_runs`, joined by `message_id`, so a confirmation
updates one row and the next assembly sees the outcome.
"""

from __future__ import annotations

import json

from backend.core import db
from backend.core.clock import now_iso

TERMINAL = ("done", "denied", "error", "stale", "uncertain", "interrupted")
_TITLE_MAX = 60
_CONVERSATION = """SELECT c.id, c.user_id, c.agent_id, a.slug AS agent_slug, c.title, c.is_private,
                          c.created_at, c.updated_at, c.compacted_at
                     FROM core_agent_conversations c JOIN core_agents a ON a.id = c.agent_id"""


def _conversation(row: dict | None) -> dict | None:
    return {**row, "is_private": bool(row["is_private"])} if row else None


# ── Conversations ─────────────────────────────────────────────────────────────


def create_conversation_in(conn: db.Conn, user_id: int, agent_id: int) -> int:
    now = now_iso()
    return conn.execute(
        "INSERT INTO core_agent_conversations (user_id, agent_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (user_id, agent_id, now, now),
    ).lastrowid


def create_conversation(user_id: int, agent_id: int) -> dict:
    with db.transaction() as conn:
        conversation_id = create_conversation_in(conn, user_id, agent_id)
    return get_conversation(conversation_id, user_id)


def get_conversation(conversation_id: int, user_id: int) -> dict | None:
    return _conversation(db.one(f"{_CONVERSATION} WHERE c.id = ? AND c.user_id = ?", (conversation_id, user_id)))


def owner_of(conversation_id: int) -> int | None:
    row = db.one("SELECT user_id FROM core_agent_conversations WHERE id = ?", (conversation_id,))
    return row["user_id"] if row else None


def _fts_query(q: str) -> str:
    """User text as an FTS5 query of quoted terms (AND), so punctuation is never syntax."""
    return " ".join('"' + term.replace('"', '""') + '"' for term in q.split())


def list_conversations(user_id: int, q: str | None = None, limit: int = 50, offset: int = 0) -> list[dict]:
    """The user's conversations, newest first; with `q`, only those whose messages match."""
    limit, offset = max(1, min(int(limit), 200)), max(0, int(offset))
    if q and q.strip():
        sql = f"""{_CONVERSATION} WHERE c.user_id = ? AND c.id IN (
                      SELECT m.conversation_id FROM core_agent_messages_fts f
                        JOIN core_agent_messages m ON m.id = f.rowid
                       WHERE core_agent_messages_fts MATCH ?)
                  ORDER BY c.updated_at DESC, c.id DESC LIMIT ? OFFSET ?"""
        params: tuple = (user_id, _fts_query(q), limit, offset)
    else:
        sql = f"{_CONVERSATION} WHERE c.user_id = ? ORDER BY c.updated_at DESC, c.id DESC LIMIT ? OFFSET ?"
        params = (user_id, limit, offset)
    return [_conversation(r) for r in db.rows(sql, params)]


def update_conversation(conversation_id: int, user_id: int, *, title: str | None = None, is_private: bool | None = None) -> dict | None:
    fields: dict = {}
    if title is not None:
        fields["title"] = " ".join(title.split())[:200]
    if is_private is not None:
        fields["is_private"] = int(is_private)
    with db.transaction() as conn:
        if not conn.execute("SELECT 1 FROM core_agent_conversations WHERE id = ? AND user_id = ?", (conversation_id, user_id)).fetchone():
            return None
        if fields:
            sets = ", ".join(f"{k} = ?" for k in fields)  # keys are the literals above
            conn.execute(f"UPDATE core_agent_conversations SET {sets}, updated_at = ? WHERE id = ?", (*fields.values(), now_iso(), conversation_id))
    return get_conversation(conversation_id, user_id)


def delete_conversation(conversation_id: int, user_id: int) -> bool:
    """Delete a thread and its messages. Its tool runs stay as the audit log; any still pending
    are recorded as denied, since nobody can approve them any more."""
    now = now_iso()
    with db.transaction() as conn:
        if not conn.execute("SELECT 1 FROM core_agent_conversations WHERE id = ? AND user_id = ?", (conversation_id, user_id)).fetchone():
            return False
        conn.execute(
            """UPDATE core_agent_tool_runs SET status = 'denied', resolved_at = ?, resolved_by = ?
                WHERE conversation_id = ? AND status = 'pending'""",
            (now, user_id, conversation_id),
        )
        conn.execute("DELETE FROM core_agent_messages WHERE conversation_id = ?", (conversation_id,))
        conn.execute("DELETE FROM core_agent_conversations WHERE id = ?", (conversation_id,))
    return True


def auto_title_in(conn: db.Conn, conversation_id: int, text: str) -> str | None:
    """Title an untitled conversation from its first message; None when it already has one."""
    title = " ".join((text or "").split())
    if len(title) > _TITLE_MAX:
        title = title[: _TITLE_MAX - 3].rstrip() + "..."
    title = title or "New conversation"
    cur = conn.execute("UPDATE core_agent_conversations SET title = ? WHERE id = ? AND title = ''", (title, conversation_id))
    return title if cur.rowcount else None


# ── Messages ──────────────────────────────────────────────────────────────────


def messages(conversation_id: int) -> list[dict]:
    rows = db.rows(
        "SELECT id, role, content, tokens_in, tokens_out, created_at FROM core_agent_messages WHERE conversation_id = ? ORDER BY id",
        (conversation_id,),
    )
    return [{**r, "content": json.loads(r["content"])} for r in rows]


def save_message_in(
    conn: db.Conn, conversation_id: int, role: str, content: dict, *,
    tokens_in: int | None = None, tokens_out: int | None = None,
) -> int:
    """Insert one message and bump the thread. `tokens_in` (the cache-inclusive input the model
    read) also becomes the thread's fullness reading for compaction."""
    now = now_iso()
    message_id = conn.execute(
        "INSERT INTO core_agent_messages (conversation_id, role, content, tokens_in, tokens_out, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (conversation_id, role, json.dumps(content, default=str), tokens_in, tokens_out, now),
    ).lastrowid
    # simplification: the latest reading wins; two turns racing on one thread can leave a stale
    # one until the next turn. CakeCRM versions readings by compaction boundary if this bites.
    conn.execute(
        "UPDATE core_agent_conversations SET updated_at = ?, last_context_tokens = coalesce(?, last_context_tokens) WHERE id = ?",
        (now, tokens_in, conversation_id),
    )
    return message_id


def save_message(conversation_id: int, role: str, content: dict, **kw) -> int:
    with db.transaction() as conn:
        return save_message_in(conn, conversation_id, role, content, **kw)


# ── Compaction state ──────────────────────────────────────────────────────────


def compaction_state(conversation_id: int) -> dict | None:
    return db.one(
        "SELECT summary, summary_first_kept_id, last_context_tokens, tainted FROM core_agent_conversations WHERE id = ?",
        (conversation_id,),
    )


def set_compaction(conversation_id: int, summary: str, first_kept_id: int) -> bool:
    """Store a gist + boundary; only ever moves the boundary forward (a racing turn loses).
    Clears the fullness reading, which described the context this just made smaller."""
    with db.transaction() as conn:
        return conn.execute(
            """UPDATE core_agent_conversations
                  SET summary = ?, summary_first_kept_id = ?, last_context_tokens = NULL, compacted_at = ?
                WHERE id = ? AND (summary_first_kept_id IS NULL OR summary_first_kept_id < ?)""",
            (summary, first_kept_id, now_iso(), conversation_id, first_kept_id),
        ).rowcount > 0


def mark_tainted(conversation_id: int) -> None:
    """Untrusted content entered this thread; every later write confirms (survives compaction)."""
    with db.transaction() as conn:
        conn.execute("UPDATE core_agent_conversations SET tainted = 1 WHERE id = ?", (conversation_id,))


# ── Tool runs ─────────────────────────────────────────────────────────────────


def insert_tool_run_in(
    conn: db.Conn, *, tool: str, args: dict, status: str, user_id: int, source: str = "chat",
    conversation_id: int | None = None, message_id: int | None = None, tool_use_id: str | None = None,
    tool_def_sha256: str = "", result: str | None = None, error: str | None = None,
) -> int:
    """`result` is already serialized (JSON text)."""
    now = now_iso()
    terminal = status in TERMINAL
    return conn.execute(
        """INSERT INTO core_agent_tool_runs (conversation_id, message_id, tool_use_id, tool, tool_def_sha256, args,
                                             status, result, error, user_id, source, requested_at, resolved_at, resolved_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (conversation_id, message_id, tool_use_id, tool, tool_def_sha256, json.dumps(args, default=str), status,
         result, error, user_id, source, now, now if terminal else None, user_id if terminal else None),
    ).lastrowid


def insert_tool_run(**kw) -> int:
    with db.transaction() as conn:
        return insert_tool_run_in(conn, **kw)


def get_tool_run(run_id: int) -> dict | None:
    return db.one("SELECT * FROM core_agent_tool_runs WHERE id = ?", (run_id,))


def tool_runs_for(conversation_id: int) -> list[dict]:
    return db.rows("SELECT * FROM core_agent_tool_runs WHERE conversation_id = ? ORDER BY id", (conversation_id,))


def claim_in(conn: db.Conn, run_id: int) -> bool:
    """pending -> executing; False when someone else resolved or claimed it first."""
    return conn.execute(
        "UPDATE core_agent_tool_runs SET status = 'executing' WHERE id = ? AND status = 'pending'", (run_id,)
    ).rowcount > 0


def resolve_in(
    conn: db.Conn, run_id: int, status: str, *, result: str | None = None, error: str | None = None,
    resolved_by: int | None = None, expect: str = "pending",
) -> bool:
    """Move a run from `expect` to a final status; False when it was not in `expect`."""
    return conn.execute(
        """UPDATE core_agent_tool_runs SET status = ?, result = ?, error = ?, resolved_at = ?, resolved_by = ?
            WHERE id = ? AND status = ?""",
        (status, result, error, now_iso(), resolved_by, run_id, expect),
    ).rowcount > 0


def resolve(run_id: int, status: str, **kw) -> bool:
    with db.transaction() as conn:
        return resolve_in(conn, run_id, status, **kw)


def mark_interrupted() -> int:
    """Runs left `executing` belong to a process that is gone (startup)."""
    with db.transaction() as conn:
        return conn.execute(
            """UPDATE core_agent_tool_runs SET status = 'interrupted', resolved_at = ?,
                      error = 'The server restarted while this was running.'
                WHERE status = 'executing'""",
            (now_iso(),),
        ).rowcount


_STATUS_FOR_MODEL = {
    "pending": {"status": "pending_user_approval"},
    "executing": {"status": "executing"},
    "denied": {"status": "denied_by_user"},
    "stale": {"status": "stale", "error": "The tool changed after it was proposed, so it was not run."},
    "interrupted": {"status": "interrupted", "error": "The server restarted while this ran; it may or may not have taken effect."},
}


def model_content(run: dict) -> str:
    """What the model is shown as this run's tool result."""
    if run["status"] == "done":
        stored = run["result"] or "null"
        value = json.loads(stored)
        return value if isinstance(value, str) else stored  # a fenced result is stored as a JSON string
    if run["status"] in ("error", "uncertain"):
        return json.dumps({"status": run["status"], "error": run["error"]})
    return json.dumps(_STATUS_FOR_MODEL[run["status"]])
