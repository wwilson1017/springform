"""AI touch counts: how many meaningful prospect interactions a deal has had (most deals close
between touch 5 and 12), judged by the light model over the deal's notes, comments, activity
and its own notes field. Ported from CakeCRM's crm/touch_count_service.py (docs/PROVENANCE.md),
with the in-process worker thread cut: the on_record_changed hook sets crm_deals.touch_dirty,
and the job `crm.touch_count` (every 120 s) drains at most BATCH dirty or never-counted deals.

Per deal the job (1) reads the evidence in a plain read, (2) calls
`backend.core.agent.llm.complete(..., tier="light")` OUTSIDE any transaction, (3) in one
transaction stores the count, `crm_deal_ai_touch_evidence` and clears touch_dirty, guarded so a
result built on evidence that changed meanwhile is not written (the deal stays dirty). With no
provider configured (`NoProviderConfigured`) or crm.touch_count_enabled false the run is skipped.

Interface the rest of the app relies on:
- `run(cancel_event)`: the job body;
- `evidence(user, deal_id)`: the TouchEvidence shape for GET /deals/{id}/touch-evidence;
- `status()`: the BackfillStatus shape; `request_backfill(scope)`: mark every live deal
  ("all") or every never-counted one ("missing") dirty, returns status.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from backend.apps.crm.common import ENTITY, LIVE
from backend.core import db, entities

if TYPE_CHECKING:
    from backend.core.auth.deps import User

BATCH = 20
_running = threading.Event()


def run(cancel: threading.Event) -> None:
    """Placeholder until the touch-count port lands: nothing is counted."""


def evidence(user: User, deal_id: int) -> dict:
    conn = db.get_conn()
    entities.authorize(user, conn, ENTITY, deal_id, "read")
    row = conn.execute("SELECT ai_touch_count, ai_touch_count_at FROM crm_deals WHERE id = ?", (deal_id,)).fetchone()
    return {"deal_id": deal_id, "count": row[0], "computed_at": row[1], "current": False, "items": []}


def status() -> dict:
    from backend.core.agent import providers

    pending = db.get_conn().execute(
        f"SELECT count(*) FROM crm_deals d WHERE {LIVE} AND (d.touch_dirty = 1 OR d.ai_touch_count IS NULL)"
    ).fetchone()[0]
    return {"pending": pending, "running": _running.is_set(), "last_run_at": None, "configured": providers.get_provider() is not None}


def request_backfill(scope: str) -> dict:
    with db.transaction() as conn:
        extra = "" if scope == "all" else "AND d.ai_touch_count IS NULL"
        conn.execute(f"UPDATE crm_deals SET touch_dirty = 1 WHERE id IN (SELECT d.id FROM crm_deals d WHERE {LIVE} {extra})")
    return status()
