"""Agents are rows in `core_agents`; Whisk is the seeded default. Plus the system-prompt builder
(ported from CakeCRM `assistant/identity.py`: a fixed singleton there, rows here).

The prompt is a (static, volatile) pair so Anthropic can cache the static half. Static: who the
agent is, the admin's personality, the memory package's protected instructions (soul.md,
MEMORY.md), the installed apps, the confirmation and untrusted-content contracts, the
deferred-tool catalog. The contracts come after both editable texts, so neither can talk the
model out of them. The soul lives only in memory's soul.md, never on the agent row.
Volatile: today's date in the install timezone, who is asking, and the memory block for this turn.
"""

from __future__ import annotations

from backend.core import db, localtime
from backend.core.agent import delimiters
from backend.core.auth.deps import User
from backend.core.clock import now_iso
from backend.core.errors import NotFound
from backend.core.platform import keys

DEFAULT_SLUG = "whisk"
DEFAULT_NAME = "Whisk"
COLUMNS = "id, slug, name, personality, provider_override, model_override, model_tier, is_default, created_at"

CONFIRMATION_NOTE = (
    "## Changes and approvals\n"
    "Most tools that change records wait for the user's approval before they run. When a tool "
    'result is `{"status": "pending_user_approval"}` the change has NOT happened yet: say what you '
    "are about to do and that it is waiting for their approval. That is normal, not an error. "
    "`denied_by_user` means they said no. `stale` means the tool changed after you proposed it, so "
    "it was not run. `interrupted` or `uncertain` means it may or may not have taken effect: check "
    "before trying again. Read tools never need approval."
)
_ROLE_NOTES = {
    "admin": "They are an administrator of this install: settings, users and AI keys are theirs to change.",
    "member": (
        "They are a member of this install, not an administrator. Settings, users and AI keys are "
        "admin-only, so if they ask to change one, say it needs an administrator."
    ),
}


def _agent(row: dict) -> dict:
    return {**row, "is_default": bool(row["is_default"])}


def ensure_default() -> None:
    """Seed Whisk when no default agent exists (startup, and after a factory reset)."""
    if db.one("SELECT 1 AS x FROM core_agents WHERE is_default = 1 OR slug = ?", (DEFAULT_SLUG,)):
        return
    with db.transaction() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO core_agents (slug, name, model_tier, is_default, created_at)
               VALUES (?, ?, 'default', 1, ?)""",
            (DEFAULT_SLUG, DEFAULT_NAME, now_iso()),
        )


def list_agents() -> list[dict]:
    ensure_default()
    return [_agent(r) for r in db.rows(f"SELECT {COLUMNS} FROM core_agents ORDER BY is_default DESC, id")]


def get(slug: str | None = None) -> dict:
    """An agent by slug; the default agent when slug is None. NotFound for an unknown slug."""
    ensure_default()
    if slug is None:
        row = db.one(f"SELECT {COLUMNS} FROM core_agents ORDER BY is_default DESC, id LIMIT 1")
    else:
        row = db.one(f"SELECT {COLUMNS} FROM core_agents WHERE slug = ?", (slug,))
    if row is None:
        raise NotFound(f"no agent {slug!r}")
    return _agent(row)


def get_by_id(agent_id: int) -> dict:
    row = db.one(f"SELECT {COLUMNS} FROM core_agents WHERE id = ?", (agent_id,))
    if row is None:
        raise NotFound()
    return _agent(row)


UPDATABLE = ("name", "personality", "provider_override", "model_override", "model_tier")


def update_in(conn: db.Conn, slug: str, fields: dict) -> None:
    fields = {k: v for k, v in fields.items() if k in UPDATABLE}
    if not conn.execute("SELECT 1 FROM core_agents WHERE slug = ?", (slug,)).fetchone():
        raise NotFound(f"no agent {slug!r}")
    if fields:
        sets = ", ".join(f"{k} = ?" for k in fields)  # keys come from UPDATABLE
        conn.execute(f"UPDATE core_agents SET {sets} WHERE slug = ?", (*fields.values(), slug))


def update(slug: str, fields: dict) -> dict:
    with db.transaction() as conn:
        update_in(conn, slug, fields)
    return get(slug)


def _one_line(value, limit: int = 80) -> str:
    """A stored free-text field as one bounded line, so it cannot pose as a prompt section."""
    text = "".join(ch if ch.isprintable() else " " for ch in str(value or ""))
    return " ".join(text.split())[:limit].strip()


def user_note(user: User) -> str:
    name, email = _one_line(user.name), _one_line(user.email)
    who = f"{name} ({email})" if name and email else name or email
    parts = [f"You are talking with {who}."] if who else []
    return " ".join(parts + [_ROLE_NOTES.get(user.role, "")]).strip()


def build_system_prompt(
    agent: dict, user: User, *, instructions: str = "", catalog: str = "", memory: str = "",
) -> tuple[str, str]:
    from backend.core import registry  # registry imports this package; resolve at call time

    install = _one_line(keys.get("workspace.name"), 120) or "this business"
    apps = registry.list_for_user(user)
    apps_block = "## Installed apps\n" + "\n".join(f"- {a['name']}: {a['description']}" for a in apps) if apps else ""
    static = "\n\n".join(p for p in [
        f"You are {agent['name']}, the assistant for {install}.",
        agent["personality"],
        instructions,
        apps_block,
        CONFIRMATION_NOTE,
        delimiters.SAFETY_INSTRUCTION,
        catalog,
    ] if p)
    now = localtime.now_local()
    volatile = "\n\n".join(p for p in [
        f"Today is {now.strftime('%A, %B %d, %Y')} ({now.tzinfo}).",
        user_note(user),
        memory,
    ] if p)
    return static, volatile
