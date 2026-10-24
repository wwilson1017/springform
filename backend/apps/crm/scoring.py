"""Lead scores: a 0-100 "how alive is this?" number for deals (crm_deals.lead_score) and people
(crm_person_scores), from CRM signals only: stage, engagement, value, linkage, recency, age,
temperature. No AI. Ported from CakeCRM's crm/scoring_service.py (docs/PROVENANCE.md).

Interface the rest of the app relies on:
- `refresh_in(conn, deal_ids=(), person_ids=())`: recompute the given deals and people inside
  the caller's transaction. Cheap SQL only (it runs from the on_record_changed hook); None ids
  are ignored. Writes lead_score/lead_score_at, never updated_at.
- `backfill()`: rescore every live deal and every person with a deal or activity; returns
  {deals, people}. Admin route and Whisk tool.
- `merge_people_in(conn, target_id, source_id)`: keep the higher of the two person scores on
  the target and drop the source's row (the on_entity_merged subscriber calls it).
"""

from __future__ import annotations

import json
from collections.abc import Iterable

from backend.core import db


def refresh_in(conn: db.Conn, deal_ids: Iterable[int | None] = (), person_ids: Iterable[int | None] = ()) -> None:
    """Placeholder until the scoring port lands: scores stay NULL (never scored)."""


def backfill() -> dict:
    return {"deals": 0, "people": 0}


def merge_people_in(conn: db.Conn, target_id: int, source_id: int) -> None:
    conn.execute(
        """INSERT INTO crm_person_scores (person_id, lead_score, lead_score_at)
           SELECT ?, lead_score, lead_score_at FROM crm_person_scores WHERE person_id = ?
           ON CONFLICT (person_id) DO UPDATE SET lead_score = excluded.lead_score, lead_score_at = excluded.lead_score_at
           WHERE excluded.lead_score > crm_person_scores.lead_score""",
        (target_id, source_id),
    )
    conn.execute("DELETE FROM crm_person_scores WHERE person_id = ?", (source_id,))


def person_scores(ids: list[int]) -> list[dict]:
    """Stored person scores for the given ids (people never scored are absent)."""
    rows = db.get_conn().execute(
        "SELECT person_id, lead_score, lead_score_at FROM crm_person_scores WHERE person_id IN (SELECT value FROM json_each(?))",
        (json.dumps(ids),),
    )
    return [dict(r) for r in rows]
