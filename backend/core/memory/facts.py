"""Facts: install-shared business memory, one plain sentence each, with a validity window.

A fact is current when `valid_from <= now` and `invalid_from` is NULL or later than now.
`forget` is soft: it sets `invalid_from`, so history stays answerable. Search is FTS5
(`unicode61`), an OR of the query's keywords, current facts first.

Privacy (docs/agents/agent.md §3): `public()` is what a member sees; `with_provenance()` adds
the source conversation id, author and dates for admins. Nothing here reads a conversation.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable

from backend.core import clock, db
from backend.core.errors import Invalid, NotFound

TEXT_MAX = 1000
TAGS_MAX = 10
TAG_MAX = 40
LIMIT_MAX = 100
_QUERY_MAX = 1000
_TERMS_MAX = 20
_TOKEN = re.compile(r"\w+", re.UNICODE)
# Query-side filler, dropped so a conversational query matches on its content words.
# Lifted from CakeCRM memory/service.py (names like "will", "may", "us" are kept on purpose).
_STOPWORDS = frozenset({
    "a", "an", "and", "the", "or", "but", "of", "to", "at", "by", "for", "from",
    "with", "about", "as", "is", "am", "are", "was", "were", "be", "been", "being",
    "do", "does", "did", "have", "has", "had", "this", "that", "these", "those",
    "we", "our", "you", "your", "they", "them", "their", "he", "she", "him", "her",
    "his", "what", "who", "whom", "when", "where", "why", "how", "which", "whose",
    "if", "then", "than", "there", "here", "out", "over", "just", "only", "also",
    "very", "too", "not", "all", "any", "some", "each", "every", "into", "so", "me", "my",
})  # fmt: skip

_COLS = """f.id, f.text, f.tags, f.valid_from, f.invalid_from, f.invalidated_by, f.superseded_by,
           f.source_conversation_id, f.author_user_id, u.name AS author_name, f.created_at"""
_AUTHOR = "LEFT JOIN core_users u ON u.id = f.author_user_id"
_FROM = f"core_agent_facts f {_AUTHOR}"
_CURRENT = "(f.valid_from <= :now AND (f.invalid_from IS NULL OR f.invalid_from > :now))"


def fts_query(text: str) -> str:
    """An FTS5 MATCH expression: the distinct keywords of `text`, quoted, prefix-matched, OR-joined.
    Quoting makes it injection-safe; '' when nothing usable is left."""
    tokens: list[str] = []
    for tok in _TOKEN.findall((text or "")[:_QUERY_MAX].lower()):
        if len(tok) >= 2 and tok not in tokens:
            tokens.append(tok)
    terms = [t for t in tokens if t not in _STOPWORDS] or tokens  # an all-filler query still searches
    return " OR ".join(f'"{t}"*' for t in terms[:_TERMS_MAX])


def _clean_text(text: str) -> str:
    cleaned = " ".join(str(text or "").split())  # single line: facts reach the system prompt
    if not cleaned:
        raise Invalid("fact_text_required")
    if len(cleaned) > TEXT_MAX:
        raise Invalid(f"fact text is longer than {TEXT_MAX} characters")
    return cleaned


def _clean_tags(tags: Iterable[str]) -> list[str]:
    out: list[str] = []
    for tag in tags or ():
        tag = " ".join(str(tag).split())[:TAG_MAX]
        if tag and tag not in out:
            out.append(tag)
    return out[:TAGS_MAX]


def _row(r) -> dict:
    d = dict(r)
    d["tags"] = json.loads(d["tags"] or "[]")
    return d


def public(fact: dict) -> dict:
    """What any member sees."""
    return {k: fact[k] for k in ("id", "text", "tags", "valid_from", "invalid_from")}


def with_provenance(fact: dict) -> dict:
    """What an admin sees: the member view plus where the fact came from. Ids and dates only;
    the conversation itself stays readable by its owner alone."""
    keys = ("source_conversation_id", "author_user_id", "author_name", "created_at", "invalidated_by", "superseded_by")
    return {**public(fact), **{k: fact[k] for k in keys}}


def _limit(limit: int) -> int:
    return max(1, min(int(limit), LIMIT_MAX))


# ── Writes ────────────────────────────────────────────────────────────────────


def remember_in(
    conn: db.Conn,
    text: str,
    *,
    author_user_id: int,
    source_conversation_id: int | None = None,
    valid_from: str | None = None,
    tags: Iterable[str] = (),
) -> dict:
    now = clock.now_iso()
    try:
        start = clock.normalize(valid_from) if valid_from else now
    except ValueError as e:
        raise Invalid(str(e)) from None
    fact_id = conn.execute(
        """INSERT INTO core_agent_facts (text, tags, valid_from, source_conversation_id, author_user_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (_clean_text(text), json.dumps(_clean_tags(tags)), start, source_conversation_id, author_user_id, now),
    ).lastrowid
    return get_in(conn, fact_id)


def remember(text: str, **kw) -> dict:
    with db.transaction() as conn:
        return remember_in(conn, text, **kw)


def forget_in(conn: db.Conn, fact_id: int, by_user_id: int, *, superseded_by: int | None = None) -> dict:
    """End a fact's validity now. Idempotent: an already-ended fact keeps its window."""
    conn.execute(
        """UPDATE core_agent_facts SET invalid_from = max(?, valid_from), invalidated_by = ?, superseded_by = ?
           WHERE id = ? AND invalid_from IS NULL""",
        (clock.now_iso(), by_user_id, superseded_by, fact_id),
    )
    return get_in(conn, fact_id)


def forget(fact_id: int, by_user_id: int, **kw) -> dict:
    with db.transaction() as conn:
        return forget_in(conn, fact_id, by_user_id, **kw)


# ── Reads ─────────────────────────────────────────────────────────────────────


def get_in(conn: db.Conn, fact_id: int) -> dict:
    row = conn.execute(f"SELECT {_COLS} FROM {_FROM} WHERE f.id = ?", (fact_id,)).fetchone()
    if row is None:
        raise NotFound("fact_not_found")
    return _row(row)


def get(fact_id: int) -> dict:
    return get_in(db.get_conn(), fact_id)


def search_in(conn: db.Conn, query: str, limit: int = 10, *, include_history: bool = False) -> list[dict]:
    """Facts matching any keyword of `query`, best match first. Current facts only, unless
    `include_history`, which appends ended and not-yet-valid facts after the current ones."""
    match = fts_query(query)
    if not match:
        return []
    rows = conn.execute(
        f"""SELECT {_COLS} FROM core_agent_facts_fts JOIN core_agent_facts f ON f.id = core_agent_facts_fts.rowid {_AUTHOR}
            WHERE core_agent_facts_fts MATCH :match AND (:history OR {_CURRENT})
            ORDER BY {_CURRENT} DESC, bm25(core_agent_facts_fts), f.id DESC LIMIT :limit""",
        {"match": match, "history": int(include_history), "now": clock.now_iso(), "limit": _limit(limit)},
    )
    return [_row(r) for r in rows]


def search(query: str, limit: int = 10, *, include_history: bool = False) -> list[dict]:
    return search_in(db.get_conn(), query, limit, include_history=include_history)


def list_facts_in(conn: db.Conn, limit: int = 50, offset: int = 0, *, include_history: bool = False) -> list[dict]:
    """Newest first; current facts only unless `include_history`."""
    rows = conn.execute(
        f"""SELECT {_COLS} FROM {_FROM} WHERE (:history OR {_CURRENT})
            ORDER BY {_CURRENT} DESC, f.id DESC LIMIT :limit OFFSET :offset""",
        {"history": int(include_history), "now": clock.now_iso(), "limit": _limit(limit), "offset": max(0, int(offset))},
    )
    return [_row(r) for r in rows]


def list_facts(limit: int = 50, offset: int = 0, *, include_history: bool = False) -> list[dict]:
    return list_facts_in(db.get_conn(), limit, offset, include_history=include_history)
