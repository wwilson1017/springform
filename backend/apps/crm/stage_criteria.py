"""What each pipeline stage means: a summary and an exit checklist. The standard copy is
`stage_criteria_standard.json` beside this file; seed() writes it on every boot without
overwriting an install's edits, an admin edits a stage, and reset puts the standard back.
Ported from CakeCRM's crm/stage_criteria.py (docs/PROVENANCE.md)."""

from __future__ import annotations

import json
from pathlib import Path

from backend.apps.crm.common import STAGES
from backend.core import clock, db
from backend.core.errors import NotFound

STANDARD: dict[str, dict] = json.loads(Path(__file__).with_name("stage_criteria_standard.json").read_text(encoding="utf-8"))


def _entry(row) -> dict:
    checklist = json.loads(row["checklist"])
    std = STANDARD[row["stage"]]
    return {
        "stage": row["stage"], "summary": row["summary"], "checklist": checklist, "updated_at": row["updated_at"],
        "is_default": row["summary"] == std["summary"] and checklist == std["checklist"],
    }


def _check(stage: str) -> None:
    if stage not in STAGES:
        raise NotFound(f"no stage {stage!r}")


def seed_in(conn: db.Conn) -> None:
    now = clock.now_iso()
    conn.executemany(
        "INSERT OR IGNORE INTO crm_stage_criteria (stage, summary, checklist, updated_at) VALUES (?, ?, ?, ?)",
        [(s, STANDARD[s]["summary"], json.dumps(STANDARD[s]["checklist"]), now) for s in STAGES],
    )


def list_criteria() -> list[dict]:
    """Every stage in pipeline order; a stage with no row (before the first seed) reads as standard."""
    rows = {r["stage"]: r for r in db.get_conn().execute("SELECT * FROM crm_stage_criteria")}
    standard = {s: {"stage": s, "summary": v["summary"], "checklist": json.dumps(v["checklist"]), "updated_at": None} for s, v in STANDARD.items()}
    return [_entry(rows.get(s) or standard[s]) for s in STAGES]


def set_criteria(stage: str, summary: str, checklist: list[str]) -> dict:
    _check(stage)
    items = [c.strip() for c in checklist if c and c.strip()]
    with db.transaction() as conn:
        conn.execute(
            """INSERT INTO crm_stage_criteria (stage, summary, checklist, updated_at) VALUES (?, ?, ?, ?)
               ON CONFLICT (stage) DO UPDATE SET summary = excluded.summary, checklist = excluded.checklist,
                                                updated_at = excluded.updated_at""",
            (stage, summary.strip(), json.dumps(items), clock.now_iso()),
        )
        return _entry(conn.execute("SELECT * FROM crm_stage_criteria WHERE stage = ?", (stage,)).fetchone())


def reset_criteria(stage: str) -> dict:
    _check(stage)
    return set_criteria(stage, STANDARD[stage]["summary"], STANDARD[stage]["checklist"])
