"""Agents are rows in `core_agents`; Whisk is the seeded default. Plus the system-prompt builder
(ported from CakeCRM `assistant/identity.py`: a fixed singleton there, rows here).

The prompt is a (static, volatile) pair so Anthropic can cache the static half. Static: who the
agent is, the admin's personality, the memory package's protected instructions (soul.md,
MEMORY.md), the name note, the installed apps, the approved skills index, the confirmation and
untrusted-content contracts, the deferred-tool catalog. The contracts come after the editable texts,
so none of them can talk the model out of them. The soul lives only in memory's soul.md, never on the agent row.
Volatile: today's date in the install timezone, who is asking, the page and record they have open
(`context_note`), and the memory block for this turn.
"""

from __future__ import annotations

from backend.core import db, entities, localtime
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
    "before trying again. Read tools never need approval. A bulk edit shows the user its old and new "
    "values with an Undo button; you cannot undo it yourself, so point them to the button."
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


def ensure_default_in(conn: db.Conn) -> None:
    """Seed Whisk when no default agent exists (startup, and after a factory reset)."""
    if conn.execute("SELECT 1 FROM core_agents WHERE is_default = 1 OR slug = ?", (DEFAULT_SLUG,)).fetchone():
        return
    conn.execute(
        """INSERT OR IGNORE INTO core_agents (slug, name, model_tier, is_default, created_at)
           VALUES (?, ?, 'default', 1, ?)""",
        (DEFAULT_SLUG, DEFAULT_NAME, now_iso()),
    )


def ensure_default() -> None:
    if db.one("SELECT 1 AS x FROM core_agents WHERE is_default = 1 OR slug = ?", (DEFAULT_SLUG,)):
        return
    with db.transaction() as conn:
        ensure_default_in(conn)


def name_default_in(conn: db.Conn, name: str) -> None:
    """Rename the default agent (first-run setup), seeding it first if it is missing."""
    ensure_default_in(conn)
    conn.execute(
        "UPDATE core_agents SET name = ? WHERE id = (SELECT id FROM core_agents ORDER BY is_default DESC, id LIMIT 1)",
        (name,),
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


def context_note(user: User, page: str | None, record: tuple[str, int] | None) -> str:
    """The page and record the user has open, for the volatile half. The record is named only
    after `entities.authorize(read)`: an unknown type, a missing record or one this user cannot
    read is left out without a word, so the prompt never confirms it exists. `page` is a path
    the router has already held to a plain pattern. Only the type and id are named, never the
    title: a member can write a shared record's title, and this note is unfenced."""
    parts = [f"The user has this page of the app open: {page}."] if page else []
    if record:
        entity_type, entity_id = record
        try:
            conn = db.get_conn()
            entity = entities.authorize(user, conn, entity_type, entity_id, "read")
        except NotFound:
            return " ".join(parts)
        parts.append(
            f"The user is looking at {entity.label} #{entity_id} (entity type {entity_type}, id {entity_id}). "
            f'When they say "this", "this {entity.label.lower()}" or "here", they mean that record; '
            "read it with a tool when you need its details."
        )
    return " ".join(parts)


def build_system_prompt(
    agent: dict,
    user: User,
    *,
    instructions: str = "",
    catalog: str = "",
    memory: str = "",
    context: str = "",
    skills: str = "",
) -> tuple[str, str]:
    from backend.core import registry  # registry imports this package; resolve at call time

    install = _one_line(keys.get("workspace.name"), 120) or "this business"
    name = _one_line(agent["name"]) or DEFAULT_NAME
    apps = registry.list_for_user(user)
    apps_block = "## Installed apps\n" + "\n".join(f"- {a['name']}: {a['description']}" for a in apps) if apps else ""
    static = "\n\n".join(
        p
        for p in [
            f"You are {name}, the assistant for {install}.",
            agent["personality"],
            instructions,
            # After both editable texts, so an old soul.md that names someone else cannot win.
            f"Your name is {name}. If any text above uses another name for you, ignore it.",
            apps_block,
            registry.agent_guidance(user),
            skills,  # admin-approved (core.skills.index_in); before the contracts, like the other editable texts
            CONFIRMATION_NOTE,
            delimiters.SAFETY_INSTRUCTION,
            catalog,
        ]
        if p
    )
    now = localtime.now_local()
    volatile = "\n\n".join(
        p
        for p in [
            f"Today is {now.strftime('%A, %B %d, %Y')} ({now.tzinfo}).",
            user_note(user),
            context,
            memory,
        ]
        if p
    )
    return static, volatile
