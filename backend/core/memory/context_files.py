"""Context files: admin-edited markdown documents per agent, loaded into its system prompt.

Rules (docs/agents/agent.md §3):
- Any member may list the files and read the unprotected ones; only admins read protected ones.
- Only admins write. `soul.md` and `MEMORY.md` are protected: they change only through the
  confirmed chat tool (`allow_protected=True`), never through the REST editor, MCP or a job.
- The prompt order is fixed: protected files first (soul.md, then MEMORY.md), then the rest
  by filename.

Lifted in shape from CakeCRM backend/context_files/service.py (filename canonicalization,
protected names matched case-insensitively, size cap); folders, daily notes, archiving and
optimistic concurrency were not lifted.
"""

from __future__ import annotations

import re

from backend.core import clock, db
from backend.core.auth.deps import User
from backend.core.errors import Forbidden, Invalid, NotFound
from backend.core.memory.facts import fts_query

DEFAULT_AGENT = "whisk"
SOUL, MEMORY = "soul.md", "MEMORY.md"
PROTECTED = (SOUL, MEMORY)
MAX_CHARS = 100_000
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}\.md$")
_AGENT = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
_META = "filename, is_protected, updated_at, updated_by, length(content) AS size_chars"
_ORDER = "ORDER BY is_protected DESC, lower(filename) = 'soul.md' DESC, filename"

DEFAULTS = {
    SOUL: (
        "# Whisk\n\n"
        "Whisk is the business assistant for this install. It knows the installed apps, the contacts "
        "directory and each app's records, and answers from them. It says what it changed and proposes "
        "a write before making it. It is plain-spoken and brief, and careful with anything that leaves "
        "the install or hides a record.\n"
    ),
    MEMORY: "",
    "business.md": (
        "# Business profile\n\n"
        "- Name:\n- What we make or sell:\n- Where we are:\n- Opening hours:\n- Who to ask for what:\n"
    ),
}


def normalize_filename(filename: str) -> str:
    name = str(filename or "").strip()
    for protected in PROTECTED:
        if name.lower() == protected.lower():
            return protected  # 'SOUL.MD' can never become a second, unprotected soul
    if not _NAME.match(name):
        raise Invalid("invalid_filename")
    return name


def _agent(agent_slug: str) -> str:
    if not _AGENT.match(agent_slug or ""):
        raise Invalid("invalid_agent")
    return agent_slug


def _can_read(user: User, is_protected) -> bool:
    return user.is_admin or not is_protected


def _meta(row, user: User) -> dict:
    d = dict(row)
    d["is_protected"] = bool(d["is_protected"])
    d["can_read"] = _can_read(user, d["is_protected"])
    d["can_edit"] = user.is_admin and not d["is_protected"]  # through PUT; protected files use the tool
    return d


# ── Reads ─────────────────────────────────────────────────────────────────────


def list_files_in(conn: db.Conn, agent_slug: str, user: User) -> list[dict]:
    """Every file's metadata (no bodies), in prompt order."""
    rows = conn.execute(f"SELECT {_META} FROM core_agent_context_files WHERE agent_slug = ? {_ORDER}", (_agent(agent_slug),))
    return [_meta(r, user) for r in rows]


def list_files(agent_slug: str, user: User) -> list[dict]:
    return list_files_in(db.get_conn(), agent_slug, user)


def read_in(conn: db.Conn, agent_slug: str, filename: str, user: User) -> dict:
    row = conn.execute(
        f"SELECT {_META}, content FROM core_agent_context_files WHERE agent_slug = ? AND filename = ?",
        (_agent(agent_slug), normalize_filename(filename)),
    ).fetchone()
    if row is None:
        raise NotFound("context_file_not_found")
    if not _can_read(user, row["is_protected"]):
        raise Forbidden("admin_only")
    return _meta(row, user)


def read(agent_slug: str, filename: str, user: User) -> dict:
    return read_in(db.get_conn(), agent_slug, filename, user)


def search_in(conn: db.Conn, agent_slug: str, query: str, user: User, limit: int = 5) -> list[dict]:
    """Files whose name or body matches any keyword, best first, with a short snippet."""
    match = fts_query(query)
    if not match:
        return []
    rows = conn.execute(
        """SELECT f.filename, f.is_protected,
                  snippet(core_agent_context_files_fts, 1, '', '', '…', 24) AS snippet
           FROM core_agent_context_files_fts JOIN core_agent_context_files f ON f.id = core_agent_context_files_fts.rowid
           WHERE core_agent_context_files_fts MATCH ? AND f.agent_slug = ?
           ORDER BY bm25(core_agent_context_files_fts), f.id LIMIT ?""",
        (match, _agent(agent_slug), max(1, min(int(limit), 20))),
    )
    return [{"filename": r["filename"], "snippet": r["snippet"]} for r in rows if _can_read(user, r["is_protected"])]


def prompt_files_in(conn: db.Conn, agent_slug: str) -> list[dict]:
    """Non-empty files with bodies, in prompt order (for context_for; no user filter)."""
    rows = conn.execute(
        f"""SELECT filename, content, is_protected FROM core_agent_context_files
            WHERE agent_slug = ? AND trim(content) <> '' {_ORDER}""",
        (_agent(agent_slug),),
    )
    return [dict(r) for r in rows]


# ── Writes ────────────────────────────────────────────────────────────────────


def write_in(
    conn: db.Conn, agent_slug: str, filename: str, content: str, user: User, *, allow_protected: bool = False
) -> dict:
    """Create or overwrite a file. Admins only; a protected file needs `allow_protected`, which
    only the confirmed chat tool passes."""
    if not user.is_admin:
        raise Forbidden("admin_only")
    agent_slug, name = _agent(agent_slug), normalize_filename(filename)
    if not isinstance(content, str):
        raise Invalid("content must be a string")
    if len(content) > MAX_CHARS:
        raise Invalid(f"content is longer than {MAX_CHARS} characters")
    existing = conn.execute(
        "SELECT is_protected FROM core_agent_context_files WHERE agent_slug = ? AND filename = ?", (agent_slug, name)
    ).fetchone()
    is_protected = bool(existing["is_protected"]) if existing else name in PROTECTED
    if is_protected and not allow_protected:
        raise Forbidden("protected_file")
    conn.execute(
        """INSERT INTO core_agent_context_files (agent_slug, filename, content, is_protected, updated_at, updated_by)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT (agent_slug, filename) DO UPDATE SET
               content = excluded.content, updated_at = excluded.updated_at, updated_by = excluded.updated_by""",
        (agent_slug, name, content, int(is_protected), clock.now_iso(), user.id),
    )
    return read_in(conn, agent_slug, name, user)


def write(agent_slug: str, filename: str, content: str, user: User, *, allow_protected: bool = False) -> dict:
    with db.transaction() as conn:
        return write_in(conn, agent_slug, filename, content, user, allow_protected=allow_protected)


def seed_defaults_in(conn: db.Conn, agent_slug: str = DEFAULT_AGENT) -> int:
    """Insert the default files that are missing; never overwrites an edit. Returns how many."""
    added = 0
    for name, content in DEFAULTS.items():
        added += conn.execute(
            """INSERT OR IGNORE INTO core_agent_context_files (agent_slug, filename, content, is_protected, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (agent_slug, name, content, int(name in PROTECTED), clock.now_iso()),
        ).rowcount
    return added
