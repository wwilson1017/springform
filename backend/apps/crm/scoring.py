"""Lead scores: a 0-100 "how alive is this?" number for deals (crm_deals.lead_score) and people
(crm_person_scores), from CRM signals only: stage, engagement, value, linkage, recency, age and
temperature. No AI. Ported from CakeCRM's crm/scoring_service.py (docs/PROVENANCE.md); the
constants are generic sales reasoning, not any customer's data.

A deal's score is a stage baseline times damped factors, clamped to 1-99; won is 100 and lost 0.
A person's is a status baseline times their interactions, recency, the best stage among their
live deals, an organization link and profile completeness. Engagement counts live notes and
comments on the record's timeline plus its logged activity.

Interface:
- `refresh_in(conn, deal_ids=(), person_ids=())`: recompute and store inside the caller's
  transaction (the record hook and every CRM write call it). A deal's person is rescored with
  it. None ids are ignored. Writes lead_score/lead_score_at, never updated_at.
- `refresh(cancel)`: the `crm.scores_refresh` job: rescore up to BATCH rows not scored in the last
  day, oldest first, so recency and age keep decaying without a write.
- `backfill()`: rescore every live deal and every live person; returns {deals, people}.
- `deal_breakdown_in(conn, deal_id)`: {score, factors: {name: multiplier}} for deal health.
- `merge_people_in(conn, target_id, source_id)`: keep the higher person score on the target.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterable
from datetime import datetime

from backend.core import clock, db

STAGE_BASELINES = {"lead": 8, "qualified": 18, "proposal": 32, "negotiation": 45}
TEMPERATURE = {"hot": 1.6, "warm": 1.1, "cold": 0.5}  # unset is neutral: only a judgement moves a score
STATUS_BASE = {"active": 30, "inactive": 15, "archived": 5}
BATCH = 200
DAY = 86400

NOTES = """SELECT count(*), max(created_at) FROM core_timeline
            WHERE entity_type = ? AND entity_id = ? AND kind IN ('note', 'comment') AND archived_at IS NULL"""


def _band(value: float | None, bands: list[tuple[float, float]], last: float) -> float:
    """The multiplier of the first band whose upper bound `value` does not pass."""
    for upper, multiplier in bands:
        if value <= upper:
            return multiplier
    return last


def _days(value: str | None, now: datetime) -> float | None:
    return None if not value else max(0.0, (now - clock.parse(value)).total_seconds() / DAY)


def _engagement(conn: db.Conn, entity_type: str, entity_id: int, activity_column: str) -> tuple[int, str | None]:
    notes, newest_note = conn.execute(NOTES, (entity_type, entity_id)).fetchone()
    acts, newest_act = conn.execute(
        f"SELECT count(*), max(created_at) FROM crm_activity_log WHERE {activity_column} = ?", (entity_id,)
    ).fetchone()
    return notes + acts, max(filter(None, (newest_note, newest_act)), default=None)


def compose_deal(deal: dict, engagement: int, last_touch: str | None, now: datetime) -> dict:
    """Pure: the score and its factors from a deal row and its engagement."""
    if deal["stage"] == "won":
        return {"score": 100, "factors": {}}
    if deal["stage"] == "lost":
        return {"score": 0, "factors": {}}
    age = _days(deal["created_at"], now)
    recency = _days(last_touch, now)
    if recency is None:
        recency = age
    cents = max(deal["value_cents"] or 0, 0)
    factors = {
        "stage_baseline": float(STAGE_BASELINES.get(deal["stage"], STAGE_BASELINES["lead"])),
        "engagement": 0.6 if engagement <= 0 else _band(engagement, [(2, 0.9), (5, 1.05), (10, 1.15)], 1.25),
        "value": 0.7 if cents <= 0 else _band(cents, [(999_999, 0.9), (4_999_999, 1.05), (9_999_999, 1.15)], 1.2),
        "relationships": {2: 1.15, 1: 1.0, 0: 0.6}[bool(deal["person_id"]) + bool(deal["organization_id"])],
        "recency": 0.7 if recency is None else _band(recency, [(7, 1.1), (14, 1.05), (30, 1.0), (60, 0.85), (90, 0.7)], 0.5),
        "age": 1.0 if age is None else (1.05 if age < 30 else _band(age, [(90, 1.0), (180, 0.9), (365, 0.75)], 0.6)),
        "temperature": TEMPERATURE.get(deal["deal_temperature"] or "", 1.0),
    }
    score = 1.0
    for multiplier in factors.values():
        score *= multiplier
    return {"score": int(max(1, min(99, round(score)))), "factors": factors}


def compose_person(person: dict, interactions: int, last_touch: str | None, stages: list[str], has_org: bool, now: datetime) -> dict:
    """Pure: a person's score and factors."""
    recency = _days(last_touch, now)
    if recency is None:
        recency = _days(person["created_at"], now)
    open_stages = [s for s in ("negotiation", "proposal", "qualified", "lead") if s in stages]
    if open_stages:
        deal_link = {"negotiation": 1.6, "proposal": 1.45, "qualified": 1.25, "lead": 1.1}[open_stages[0]]
    else:
        deal_link = 1.5 if "won" in stages else 0.65 if "lost" in stages else 0.75
    have = bool((person["email"] or "").strip()) + bool((person["phone"] or "").strip())
    factors = {
        "status_base": float(STATUS_BASE.get((person["status"] or "active").lower(), STATUS_BASE["inactive"])),
        "interactions": 0.6 if interactions <= 0 else _band(interactions, [(2, 0.9), (5, 1.1), (10, 1.2)], 1.3),
        "recency": 0.55 if recency is None else _band(recency, [(7, 1.15), (30, 1.0), (90, 0.8)], 0.55),
        "deal_linkage": deal_link,
        "organization_linkage": 1.15 if has_org else 0.9,
        "profile_completeness": {2: 1.1, 1: 1.0, 0: 0.85}[have],
    }
    score = 1.0
    for multiplier in factors.values():
        score *= multiplier
    return {"score": int(max(1, min(99, round(score)))), "factors": factors}


def deal_breakdown_in(conn: db.Conn, deal_id: int, now: datetime | None = None) -> dict | None:
    row = conn.execute("SELECT * FROM crm_deals WHERE id = ?", (deal_id,)).fetchone()
    if row is None:
        return None
    count, newest = _engagement(conn, "crm.deal", deal_id, "deal_id")
    return compose_deal(dict(row), count, newest, now or clock.now())


def _person_breakdown_in(conn: db.Conn, person_id: int, now: datetime) -> dict | None:
    row = conn.execute("SELECT * FROM core_people WHERE id = ? AND merged_into_id IS NULL", (person_id,)).fetchone()
    if row is None:
        return None
    count, newest = _engagement(conn, "core.person", person_id, "person_id")
    stages = [r[0] for r in conn.execute("SELECT stage FROM crm_deals WHERE person_id = ? AND archived_at IS NULL", (person_id,))]
    has_org = conn.execute("SELECT 1 FROM core_person_organizations WHERE person_id = ? LIMIT 1", (person_id,)).fetchone() is not None
    return compose_person(dict(row), count, newest, stages, has_org, now)


def _unique(ids: Iterable[int | None]) -> list[int]:
    return list(dict.fromkeys(i for i in ids if i))


def refresh_in(conn: db.Conn, deal_ids: Iterable[int | None] = (), person_ids: Iterable[int | None] = ()) -> None:
    now = clock.now()
    stamp = clock.to_iso(now)
    deal_ids = _unique(deal_ids)
    linked = conn.execute(
        "SELECT person_id FROM crm_deals WHERE id IN (SELECT value FROM json_each(?))", (json.dumps(deal_ids),)
    ).fetchall()
    for deal_id in deal_ids:
        if (result := deal_breakdown_in(conn, deal_id, now)) is not None:
            conn.execute("UPDATE crm_deals SET lead_score = ?, lead_score_at = ? WHERE id = ?", (result["score"], stamp, deal_id))
    for person_id in _unique([*person_ids, *(r[0] for r in linked)]):
        if (result := _person_breakdown_in(conn, person_id, now)) is not None:
            conn.execute(
                """INSERT INTO crm_person_scores (person_id, lead_score, lead_score_at) VALUES (?, ?, ?)
                   ON CONFLICT (person_id) DO UPDATE SET lead_score = excluded.lead_score, lead_score_at = excluded.lead_score_at""",
                (person_id, result["score"], stamp),
            )


def refresh(cancel: threading.Event | None = None) -> dict:
    """Rescore the stalest rows (never scored, or not in the last day): live open deals first."""
    with db.transaction() as conn:
        cutoff = clock.ago(DAY)
        deal_ids = [r[0] for r in conn.execute(
            """SELECT id FROM crm_deals WHERE archived_at IS NULL AND (lead_score_at IS NULL OR lead_score_at < ?)
                 AND NOT (stage IN ('won', 'lost') AND lead_score IS NOT NULL)
               ORDER BY lead_score_at IS NOT NULL, lead_score_at, id LIMIT ?""",
            (cutoff, BATCH),
        )]  # fmt: skip
        person_ids = [r[0] for r in conn.execute(
            """SELECT p.id FROM core_people p LEFT JOIN crm_person_scores s ON s.person_id = p.id
                WHERE p.merged_into_id IS NULL AND p.archived_at IS NULL AND (s.lead_score_at IS NULL OR s.lead_score_at < ?)
                ORDER BY s.lead_score_at IS NOT NULL, s.lead_score_at, p.id LIMIT ?""",
            (cutoff, max(0, BATCH - len(deal_ids))),
        )]  # fmt: skip
        refresh_in(conn, deal_ids, person_ids)
        conn.execute(
            """INSERT INTO crm_meta (id, scores_refreshed_at, updated_at) VALUES (1, ?, ?)
               ON CONFLICT (id) DO UPDATE SET scores_refreshed_at = excluded.scores_refreshed_at""",
            (clock.now_iso(), clock.now_iso()),
        )
    return {"deals": len(deal_ids), "people": len(person_ids)}


def backfill() -> dict:
    with db.transaction() as conn:
        deal_ids = [r[0] for r in conn.execute("SELECT id FROM crm_deals WHERE archived_at IS NULL")]
        person_ids = [r[0] for r in conn.execute("SELECT id FROM core_people WHERE merged_into_id IS NULL AND archived_at IS NULL")]
        refresh_in(conn, deal_ids, person_ids)
    return {"deals": len(deal_ids), "people": len(person_ids)}


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
