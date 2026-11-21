"""Whisk's skills: short named methods an admin approved (docs/agents/agent.md, "Skills").

A row reaches the model only while it is `active`, and a row becomes active only when an admin
writes it by hand or approves a proposal (from the review job, `review.py`). The active ones are
listed by name and description in the static half of the system prompt (`index_in`, placed by
`agents.build_system_prompt`); `core_skill_load` returns one body and counts the use (`load`).
The curator archives active, unpinned skills unused for 60 days. Nothing deletes a row.

Imports only `backend.core` basics: `agent/assembly.py` imports this package at module level.
"""

from __future__ import annotations

import re

from backend.core import clock, db
from backend.core.errors import Conflict, Invalid, NotFound
from backend.core.memory.redact import blank_secrets

# simplification: one set of skills for every agent; upgrade path: an agent_slug column.
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
MAX_DESCRIPTION = 60
MAX_BODY = 12_000  # under result_cap.CAP_CHARS, so a loaded skill is never capped
INDEX_LIMIT = 30
STALE_DAYS = 60
AGENT = "agent"  # `author` of a proposal from the review
STATUSES = ("proposed", "active", "archived", "rejected")
INDEX_HEADER = (
    "## Skills\nMethods an admin approved for this business. Before a task one of them covers, "
    "load it with core_skill_load and follow it."
)
# action -> (from status, to status)
MOVES = {
    "approve": ("proposed", "active"),
    "reject": ("proposed", "rejected"),
    "archive": ("active", "archived"),
    "restore": ("archived", "active"),
}
_VIEW = """SELECT s.*, u.name AS author_name, r.name AS revises_name
           FROM core_agent_skills s
           LEFT JOIN core_users u ON s.author != 'agent' AND CAST(u.id AS TEXT) = s.author
           LEFT JOIN core_agent_skills r ON r.id = s.revises_id"""


def _line(value) -> str:
    text = "".join(ch if ch.isprintable() else " " for ch in str(value or ""))
    return " ".join(text.split())


def clean(name, description, body) -> tuple[str, str, str]:
    """The one validator (routes and the review): a lowercase slug name, a one-line description of
    1-60 characters, a body of 1-MAX_BODY characters, secrets blanked as memory blanks them
    (`memory/redact.py`). Invalid names the field."""
    name = str(name or "").strip().lower()
    if not NAME_RE.match(name):
        raise Invalid("name: 1-48 lowercase letters, digits and hyphens, starting with a letter or digit")
    description = _line(blank_secrets(str(description or ""))[0])
    if not 1 <= len(description) <= MAX_DESCRIPTION:
        raise Invalid(f"description: 1-{MAX_DESCRIPTION} characters on one line")
    body = blank_secrets(str(body or ""))[0].strip()
    if not 1 <= len(body) <= MAX_BODY:
        raise Invalid(f"body: 1-{MAX_BODY:,} characters")
    return name, description, body


def _public(row: dict) -> dict:
    return {**row, "pinned": bool(row["pinned"])}


def get_in(conn: db.Conn, skill_id: int) -> dict:
    row = conn.execute(f"{_VIEW} WHERE s.id = ?", (skill_id,)).fetchone()
    if row is None:
        raise NotFound("skill_not_found")
    return _public(dict(row))


def get(skill_id: int) -> dict:
    return get_in(db.get_conn(), skill_id)


def list_skills_in(conn: db.Conn, status: str, limit: int = 100, offset: int = 0) -> tuple[list[dict], int]:
    """One status's skills by name, a page at a time, and how many there are."""
    if status not in STATUSES:
        raise Invalid(f"status: one of {', '.join(STATUSES)}")
    rows = conn.execute(f"{_VIEW} WHERE s.status = ? ORDER BY s.name, s.id LIMIT ? OFFSET ?", (status, limit, offset))
    total = conn.execute("SELECT count(*) FROM core_agent_skills WHERE status = ?", (status,)).fetchone()[0]
    return [_public(dict(r)) for r in rows], total


def list_skills(status: str, limit: int = 100, offset: int = 0) -> tuple[list[dict], int]:
    return list_skills_in(db.get_conn(), status, limit, offset)


def create_in(
    conn: db.Conn,
    name: str,
    description: str,
    body: str,
    *,
    author: str,
    status: str,
    source_conversation_id: int | None = None,
    revises_id: int | None = None,
    approved_by: int | None = None,
) -> int:
    name, description, body = clean(name, description, body)
    now = clock.now_iso()
    approved_at = now if status == "active" else None
    try:
        return db.insert_in(
            conn,
            """INSERT INTO core_agent_skills (name, description, body, status, author, source_conversation_id,
                   revises_id, created_at, updated_at, approved_at, approved_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                name,
                description,
                body,
                status,
                author,
                source_conversation_id,
                revises_id,
                now,
                now,
                approved_at,
                approved_by,
            ),
        )
    except db.sqlite3.IntegrityError:  # clean() checked the rest: only the one-active-name index is left
        raise Conflict("skill_name_taken") from None


def create(name: str, description: str, body: str, user) -> dict:
    """A skill an admin writes by hand: active at once."""
    with db.transaction() as conn:
        skill_id = create_in(conn, name, description, body, author=str(user.id), status="active", approved_by=user.id)
        return get_in(conn, skill_id)


def update_in(conn: db.Conn, skill_id: int, fields: dict) -> None:
    """Edit name, description, body or pinned. `updated_at` moves only when the text changes, so
    pinning never makes a waiting edit proposal stale."""
    row = get_in(conn, skill_id)
    if row["status"] == "rejected":
        raise Conflict("skill_rejected")
    name, description, body = clean(
        fields.get("name", row["name"]), fields.get("description", row["description"]), fields.get("body", row["body"])
    )
    pinned = bool(fields.get("pinned", row["pinned"]))
    changed = (name, description, body) != (row["name"], row["description"], row["body"])
    try:
        conn.execute(
            """UPDATE core_agent_skills SET name = ?, description = ?, body = ?, pinned = ?,
                   updated_at = CASE WHEN ? THEN ? ELSE updated_at END
               WHERE id = ?""",
            (name, description, body, int(pinned), int(changed), clock.now_iso(), skill_id),
        )
    except db.sqlite3.IntegrityError:  # clean() checked the rest: only the one-active-name index is left
        raise Conflict("skill_name_taken") from None


def update(skill_id: int, fields: dict) -> dict:
    with db.transaction() as conn:
        update_in(conn, skill_id, fields)
        return get_in(conn, skill_id)


def move_in(conn: db.Conn, skill_id: int, action: str, user_id: int) -> None:
    """approve, reject, archive or restore. Approving an edit proposal archives the skill it revises
    and carries its pin and use over; it is refused when that skill is no longer active or its
    text changed after the proposal was made (two proposals for one skill, or an admin's edit)."""
    if action not in MOVES:
        raise Invalid(f"action: one of {', '.join(MOVES)}")
    start, end = MOVES[action]
    row = get_in(conn, skill_id)
    if row["status"] != start:
        raise Conflict(f"skill_not_{start}")
    now = clock.now_iso()
    carry = {"pinned": row["pinned"], "use_count": row["use_count"], "last_used_at": row["last_used_at"]}
    if action == "approve" and row["revises_id"] is not None:
        old = get_in(conn, row["revises_id"])
        if old["status"] != "active" or old["updated_at"] > row["created_at"]:
            raise Conflict("skill_revision_stale")
        conn.execute("UPDATE core_agent_skills SET status = 'archived' WHERE id = ?", (old["id"],))
        carry = {"pinned": old["pinned"], "use_count": old["use_count"], "last_used_at": old["last_used_at"]}
    approval = action in ("approve", "restore")
    try:
        conn.execute(
            """UPDATE core_agent_skills SET status = ?, pinned = ?, use_count = ?, last_used_at = ?,
                   approved_at = CASE WHEN ? THEN ? ELSE approved_at END,
                   approved_by = CASE WHEN ? THEN ? ELSE approved_by END
               WHERE id = ?""",
            (
                end,
                int(carry["pinned"]),
                carry["use_count"],
                carry["last_used_at"],
                approval,
                now,
                approval,
                user_id,
                skill_id,
            ),
        )
    except db.sqlite3.IntegrityError:  # clean() checked the rest: only the one-active-name index is left
        raise Conflict("skill_name_taken") from None


def move(skill_id: int, action: str, user) -> dict:
    with db.transaction() as conn:
        move_in(conn, skill_id, action, user.id)
        return get_in(conn, skill_id)


def active_names_in(conn: db.Conn) -> list[str]:
    return [r[0] for r in conn.execute("SELECT name FROM core_agent_skills WHERE status = 'active' ORDER BY name")]


def index_in(conn: db.Conn) -> str:
    """The static prompt's list of active skills, '' when there are none. Recency picks which
    INDEX_LIMIT are listed; they print by name, so a load does not change the cached prompt."""
    rows = conn.execute(
        """SELECT name, description FROM core_agent_skills WHERE status = 'active'
           ORDER BY pinned DESC, coalesce(last_used_at, approved_at, created_at) DESC, id DESC LIMIT ?""",
        (INDEX_LIMIT,),
    ).fetchall()
    if not rows:
        return ""
    return INDEX_HEADER + "\n" + "\n".join(f"- {n}: {d}" for n, d in sorted(tuple(r) for r in rows))


def load_in(conn: db.Conn, name: str) -> dict:
    """An active skill's body, counting the use. Any other name (proposed, archived, rejected or
    unknown) is NotFound, naming only the active skills."""
    row = conn.execute(
        """UPDATE core_agent_skills SET use_count = use_count + 1, last_used_at = ?
           WHERE name = ? AND status = 'active' RETURNING name, description, body""",
        (clock.now_iso(), str(name).strip().lower()),
    ).fetchone()
    if row is None:
        names = active_names_in(conn)
        raise NotFound(f"No active skill named {_line(name)[:48]!r}. Active skills: {', '.join(names) or 'none'}.")
    return dict(row)


def load(name: str) -> dict:
    with db.transaction() as conn:
        return load_in(conn, name)


def curate_in(conn: db.Conn) -> int:
    """Archive active, unpinned skills with no use or approval in STALE_DAYS. Returns the count."""
    cur = conn.execute(
        """UPDATE core_agent_skills SET status = 'archived'
           WHERE status = 'active' AND pinned = 0
             AND max(coalesce(last_used_at, ''), coalesce(approved_at, created_at)) < ?""",
        (clock.ago(STALE_DAYS * 86400),),
    )
    return cur.rowcount


def curate() -> int:
    with db.transaction() as conn:
        return curate_in(conn)
