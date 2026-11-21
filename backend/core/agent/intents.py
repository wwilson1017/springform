"""Topic reminders (agent.md §5, "Topic reminders"): "when X comes up, remind me of Y".

`core_remind_on_topic` stores an intent for the acting user. On a turn that carries newly typed
text, the `before_model_call` hook matches that text against the user's own active intents with
FTS5 (no model call) and adds each hit, fenced, to the volatile half of the system prompt. An
intent fires at most once per `cooldown_hours`, `max_fires` times in all, and never from
`expires_at`. Only the owner's messages are matched against it.

The message is what gets indexed, not the intents: FTS answers "does the text contain this
phrase", which is the question here. A throwaway in-memory database holds it, so matching takes
no writer lock and leaves nothing behind.
"""

from __future__ import annotations

import json
import re

from backend.core import clock, db
from backend.core.agent import delimiters, turn_hooks
from backend.core.agent.aio import in_thread
from backend.core.auth.deps import User
from backend.core.errors import Invalid, NotFound

TERMS_MAX, TERM_CHARS, NOTE_CHARS = 5, 60, 500
ACTIVE_MAX = 50  # per user; matching runs every one of them each turn
FIRES_PER_TURN = 3
LIFETIME_DAYS = 90
_WORD = re.compile(r"\w+")
_SCRATCH = __name__

PROMPT_HEAD = (
    "## Topic reminder\n"
    "The user's message touches a topic they asked to be reminded about. Mention the reminder below "
    "to them once, briefly, alongside your answer."
)


def _one_line(text: str, limit: int) -> str:
    return " ".join(str(text or "").split())[:limit].strip()


_ACTIVE = "fires < max_fires AND expires_at > ?"


def public(row: dict) -> dict:
    now = clock.now_iso()
    status = "used_up" if row["fires"] >= row["max_fires"] else "expired" if row["expires_at"] <= now else "active"
    keep = ("id", "note", "fires", "max_fires", "cooldown_hours", "last_fired_at", "expires_at", "created_at")
    return {**{k: row[k] for k in keep}, "terms": json.loads(row["trigger_terms"]), "status": status}


def create_in(conn: db.Conn, user: User, terms: object, note: str) -> dict:
    clean: list[str] = []
    for t in terms if isinstance(terms, list) else []:
        t = _one_line(t, TERM_CHARS + 1)
        if t and t.lower() not in (c.lower() for c in clean):
            clean.append(t)
    if not clean or len(clean) > TERMS_MAX or any(len(t) > TERM_CHARS or not _WORD.search(t) for t in clean):
        raise Invalid(f"terms: 1 to {TERMS_MAX} words or short phrases of up to {TERM_CHARS} characters")
    note = _one_line(note, NOTE_CHARS + 1)  # one line: it reaches the system prompt
    if not note or len(note) > NOTE_CHARS:
        raise Invalid(f"note: 1 to {NOTE_CHARS} characters")
    now = clock.now_iso()
    (active,) = conn.execute(
        f"SELECT count(*) FROM core_agent_intents WHERE user_id = ? AND {_ACTIVE}", (user.id, now)
    ).fetchone()
    if active >= ACTIVE_MAX:
        raise Invalid(f"You already have {ACTIVE_MAX} topic reminders; delete one on the Reminders page first.")
    new_id = db.insert_in(
        conn,
        "INSERT INTO core_agent_intents (user_id, trigger_terms, note, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
        (user.id, json.dumps(clean), note, clock.later(LIFETIME_DAYS * 86400), now),
    )
    return public(dict(conn.execute("SELECT * FROM core_agent_intents WHERE id = ?", (new_id,)).fetchone()))


def list_mine(user: User) -> list[dict]:
    rows = db.rows("SELECT * FROM core_agent_intents WHERE user_id = ? ORDER BY id DESC", (user.id,))
    return [public(r) for r in rows]


def delete(user: User, intent_id: int) -> None:
    """Another user's intent answers NotFound, exactly as a missing one does."""
    with db.transaction() as conn:
        if not conn.execute(
            "DELETE FROM core_agent_intents WHERE id = ? AND user_id = ?", (intent_id, user.id)
        ).rowcount:
            raise NotFound("intent_not_found")


def _phrase(term: str) -> str:
    return '"' + " ".join(_WORD.findall(term)) + '"'  # words only, quoted: never FTS syntax


def matching(text: str, candidates: list[dict]) -> list[dict]:
    """The candidates one of whose terms appears in `text` as a phrase (stemmed, case and accents ignored)."""
    if not text.strip() or not candidates:
        return []
    mem = db.sqlite3.connect(":memory:")
    try:
        mem.execute("CREATE VIRTUAL TABLE m USING fts5 (body, tokenize = 'porter unicode61 remove_diacritics 2')")
        mem.execute("INSERT INTO m (body) VALUES (?)", (text,))

        def hit(term: str) -> bool:
            return (
                bool(_WORD.search(term))
                and mem.execute("SELECT 1 FROM m WHERE m MATCH ?", (_phrase(term),)).fetchone() is not None
            )

        return [c for c in candidates if any(hit(t) for t in json.loads(c["trigger_terms"]))]
    finally:
        mem.close()


def fire(user_id: int, text: str) -> list[dict]:
    """Match `text` against the user's active intents off cooldown and record each fire (at most
    `FIRES_PER_TURN`). The UPDATE re-checks what was read, so two turns at once fire an intent once."""
    now = clock.now_iso()
    rows = db.rows(f"SELECT * FROM core_agent_intents WHERE user_id = ? AND {_ACTIVE} ORDER BY id", (user_id, now))
    ready = [r for r in rows if not r["last_fired_at"] or r["last_fired_at"] <= clock.ago(r["cooldown_hours"] * 3600)]
    hits = matching(text, ready)[:FIRES_PER_TURN]
    if not hits:
        return []
    fired = []
    with db.transaction() as conn:
        for r in hits:
            n = conn.execute(
                "UPDATE core_agent_intents SET fires = fires + 1, last_fired_at = ? "
                "WHERE id = ? AND fires = ? AND last_fired_at IS ?",
                (now, r["id"], r["fires"], r["last_fired_at"]),
            ).rowcount
            if n:
                fired.append(r)
    return fired


def prompt_block(hits: list[dict]) -> str:
    """A fixed heading, then the user's terms and notes inside a fence: they are data, not instructions."""
    lines = [f"When {' or '.join(json.loads(h['trigger_terms']))} comes up: {h['note']}" for h in hits]
    return f"{PROMPT_HEAD}\n{delimiters.wrap_topic_reminder(chr(10).join(lines))}"


async def before_model_call(state: turn_hooks.TurnState) -> None:
    """Once per turn, on its first model call, and only on the text the user typed for it: a
    continuation has none, so the message that set an intent cannot fire it on the resume."""
    if _SCRATCH in state.scratch:
        return
    state.scratch[_SCRATCH] = []
    if not state.message.strip():
        return
    # simplification: the fire is spent before the model answers, so a turn that then fails spends
    # one of the three and starts the cooldown; upgrade: refund it in end_of_turn when state.error.
    hits = await in_thread(fire, state.user.id, state.message)
    if not hits:
        return
    state.scratch[_SCRATCH] = [h["id"] for h in hits]
    block = prompt_block(hits)
    if isinstance(state.system, tuple):
        static, volatile = state.system
        state.system = (static, f"{volatile}\n\n{block}" if volatile else block)
    else:
        state.system = f"{state.system}\n\n{block}" if state.system else block


turn_hooks.register("before_model_call", before_model_call)
