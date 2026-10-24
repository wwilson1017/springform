"""Keyless CRM analytics: win/loss, activity volume, deal aging, per-rep numbers, stage
durations and conversion, stale deals, deal health, duplicates. Ported from CakeCRM's
crm/service.py analytics section and crm/analytics_service.py (docs/PROVENANCE.md).

Day bucketing happens in Python with core.localtime in the install timezone (never the first
ten characters of a stored timestamp, which are a UTC date); SQL compares only against
precomputed UTC bounds.
Money is integer cents; averages of cents round to whole cents.

Contracts still to port (the shapes are in models.py): `analytics(user, days, stale_days)`,
`pipeline_analytics(user, days)`, `deal_health(user, deal_id)`, `duplicates(user)`.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from backend.apps.crm import deals, settings as crm_settings
from backend.apps.crm.common import LIVE, OPEN
from backend.core import clock, db, localtime

if TYPE_CHECKING:
    from backend.core.auth.deps import User

AGE_BUCKETS = ((0, 7, "0-7"), (8, 30, "8-30"), (31, 90, "31-90"), (91, None, "91+"))


def stale_deals(user: User, days: int | None = None, limit: int = 25) -> dict:
    """Live open deals untouched for `days` (default crm.stale_days), longest-quiet first."""
    conn = db.get_conn()
    deals._gate(conn, user)
    days = days or crm_settings.stale_days()
    now = clock.now()
    rows = [
        dict(r) for r in conn.execute(
            f"""SELECT d.id, d.title, d.value_cents, d.stage, d.owner_user_id, p.name AS person_name,
                       o.name AS organization_name, d.created_at, {deals.LAST_TOUCH} AS last_touch
                  FROM crm_deals d LEFT JOIN core_people p ON p.id = d.person_id
                  LEFT JOIN core_organizations o ON o.id = d.organization_id
                 WHERE {LIVE} AND {OPEN} AND {deals.LAST_TOUCH} < ?
                 ORDER BY last_touch, d.id""",
            (clock.ago(days * 86400),),
        )
    ]
    for r in rows:
        r["days_since_touch"] = (now - clock.parse(r.pop("last_touch"))).days
        r["age_days"] = (now - clock.parse(r.pop("created_at"))).days
    return {"stale_days": days, "total_stale": len(rows), "count": min(len(rows), limit), "deals": rows[:limit]}


def analytics(user: User, days: int = 30, stale_days: int | None = None) -> dict:
    """Placeholder until the analytics port lands: the zero state, with a real day series."""
    deals._gate(db.get_conn(), user)
    days = max(7, min(365, days))
    today = localtime.today_local()
    daily = [{"day": (today - timedelta(days=i)).isoformat(), "count": 0} for i in range(days - 1, -1, -1)]
    return {
        "window_days": days, "stale_days": stale_days or crm_settings.stale_days(), "timezone": localtime.tz().key,
        "win_loss": {
            "deals_won": 0, "deals_lost": 0, "open_deals": 0, "win_rate_pct": None, "avg_won_deal_cents": None,
            "avg_open_deal_cents": None, "avg_days_to_close": None, "total_pipeline_value_cents": 0,
        },
        "activity": {"daily": daily, "by_type": [], "total": 0},
        "aging": {"buckets": [{"label": lb, "min_days": lo, "max_days": hi, "count": 0} for lo, hi, lb in AGE_BUCKETS], "stale_count": 0, "stale_deals": []},
        "per_rep": [],
    }


def pipeline_analytics(user: User, days: int = 90) -> dict:
    """Placeholder until the pipeline-analytics port lands."""
    deals._gate(db.get_conn(), user)
    return {
        "window_days": days, "history_since": None, "history_days": None, "history_covers_window": False,
        "time_in_stage": [], "conversion": [], "velocity": {"won_in_window": 0, "avg_days_to_won": None},
    }


def deal_health(user: User, deal_id: int) -> dict:
    """Placeholder until the deal-health port lands."""
    return {"deal": deals.get(user, deal_id), "score": None, "factors": {}, "stale_days": crm_settings.stale_days(), "flags": []}


def duplicates(user: User) -> list[dict]:
    """Placeholder until the duplicate-deals port lands (people and organizations: core)."""
    deals._gate(db.get_conn(), user)
    return []
