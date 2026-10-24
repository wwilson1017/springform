"""Nightly dreaming: consolidate duplicate facts. Pure Python, no model call.

Current facts with the same words (case, punctuation and word order ignored) are one fact:
the oldest stays, absorbs the others' tags, and each duplicate is ended (`invalid_from`) with
`superseded_by` pointing at it. Reads happen outside the transaction; the writes re-check that
both facts are still current.

Chatty's dreaming (core/agents/dreaming/) scores and archives context files instead; that was
not lifted, since context files here are admin-edited.
"""

from __future__ import annotations

import json
import re

from backend.core import clock, db
from backend.core.memory import facts

SYSTEM_USER_ID = 0
_WORD = re.compile(r"\w+", re.UNICODE)


def _key(text: str) -> str:
    # simplification: exact word-set duplicates only; upgrade path: a light-tier model pass that
    # merges near-duplicates and ends contradicted facts.
    return " ".join(sorted(set(_WORD.findall(text.casefold()))))


def consolidate() -> dict:
    now = clock.now_iso()
    rows = db.rows(
        """SELECT id, text, tags FROM core_agent_facts
           WHERE valid_from <= ? AND (invalid_from IS NULL OR invalid_from > ?) ORDER BY id""",
        (now, now),
    )
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(_key(row["text"]), []).append(row)
    merges = [(g[0], g[1:]) for g in groups.values() if len(g) > 1]
    merged = 0
    if merges:
        with db.transaction() as conn:
            for keep, dups in merges:
                if conn.execute("SELECT 1 FROM core_agent_facts WHERE id = ? AND invalid_from IS NULL", (keep["id"],)).fetchone() is None:
                    continue
                tags = json.loads(keep["tags"])
                for dup in dups:
                    if facts.forget_in(conn, dup["id"], SYSTEM_USER_ID, superseded_by=keep["id"])["superseded_by"] != keep["id"]:
                        continue  # someone ended it first
                    tags += [t for t in json.loads(dup["tags"]) if t not in tags]
                    merged += 1
                conn.execute("UPDATE core_agent_facts SET tags = ? WHERE id = ?", (json.dumps(tags[: facts.TAGS_MAX]), keep["id"]))
    return {"facts": len(rows), "merged": merged}
