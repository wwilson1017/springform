"""The CRM home: headline numbers, the Today list and Weekly Touches. Ported from CakeCRM's
crm/service.py dashboard section and crm/today_service.py (docs/PROVENANCE.md).

Day boundaries are install-local (core.localtime); SQL compares only against precomputed UTC
bounds. Every read is over live (unarchived) deals.

Contracts still to port (the shapes are in models.py):
- `today(user)`: hot deals that have gone quiet (rank 1), the caller's reminders due today
  (rank 2), every other hot deal (rank null); `next_refresh_at` = next local midnight.
- `weekly_touches(start, end)` / `weekly_touch_detail(owner, start, end)`: per owner, live open
  deals touched in the window plus deals won in it (a won deal is dated by its win's
  stage event); the default window is the last 7 install-local days.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING

from backend.apps.crm import activity, deals
from backend.apps.crm.common import LIVE, OPEN
from backend.core import clock, db, localtime

if TYPE_CHECKING:
    from backend.core.auth.deps import User

# Attention, not expected value: value is the base and probability swings it by at most 60%,
# so a big likely deal outranks a small near-certain one and a $0 deal scores 0.
TOP_DEAL_SCORE = "(max(d.value_cents, 0) * (0.4 + 0.6 * min(max(d.probability, 0), 100) / 100.0))"


def _live_count(conn: db.Conn, table: str) -> int:
    return conn.execute(f"SELECT count(*) FROM {table} WHERE merged_into_id IS NULL AND archived_at IS NULL").fetchone()[0]


def dashboard(user: User) -> dict:
    conn = db.get_conn()
    deals._gate(conn, user)
    month_start = localtime.today_local().replace(day=1).isoformat()
    by_stage = deals.stage_summary_in(conn, open_only=False)
    won = conn.execute(
        f"SELECT coalesce(sum(value_cents), 0) FROM crm_deals d WHERE {LIVE} AND d.stage = 'won' AND d.closed_on >= ?",
        (month_start,),
    ).fetchone()[0]
    top = conn.execute(
        f"""{deals.SELECT} WHERE {LIVE} AND {OPEN} AND d.stage != 'lead'
             ORDER BY {TOP_DEAL_SCORE} DESC, d.updated_at DESC, d.id DESC LIMIT 5"""
    )
    return {
        "total_people": _live_count(conn, "core_people"),
        "total_organizations": _live_count(conn, "core_organizations"),
        "pipeline_by_stage": by_stage,
        "total_pipeline_value_cents": sum(s["total_value_cents"] for s in by_stage if s["stage"] not in ("won", "lost")),
        "won_this_month_cents": won,
        "recent_activity": activity.list_in(conn, user, limit=10),
        "top_deals": [dict(r) for r in top],
    }


def _next_midnight() -> str:
    zone = localtime.tz()
    tomorrow = localtime.today_local() + timedelta(days=1)
    return clock.to_iso(datetime.combine(tomorrow, time.min, tzinfo=zone))


def today(user: User) -> dict:
    """Placeholder until the Today port lands: an empty list with the real date and refresh."""
    return {"date": localtime.today_local().isoformat(), "next_refresh_at": _next_midnight(), "items": []}


def _window(start: str | None, end: str | None) -> dict:
    last = localtime.today_local()
    first = last - timedelta(days=6)
    return {"start": start or first.isoformat(), "end": end or last.isoformat(), "label": "Last 7 days", "custom": bool(start or end)}


def weekly_touches(user: User, start: str | None = None, end: str | None = None) -> dict:
    """Placeholder until the Weekly Touches port lands."""
    return {"window": _window(start, end), "reps": [], "total_touches": 0, "total_open_deals": 0}


def weekly_touch_detail(user: User, owner: str, start: str | None = None, end: str | None = None) -> dict:
    """Placeholder until the Weekly Touches port lands. `owner` is a user id or 'unassigned'."""
    rep = {"user_id": None if owner == "unassigned" else int(owner), "name": "", "open_deals": 0, "touches": 0, "deals": []}
    return {"window": _window(start, end), "rep": rep, "deals": [], "truncated": False}
