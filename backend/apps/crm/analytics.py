"""Keyless CRM analytics: win/loss, activity volume, deal aging, per-rep numbers, stage
durations and conversion, stale deals, deal health, duplicates. Ported from CakeCRM's
crm/service.py analytics section and crm/analytics_service.py (docs/PROVENANCE.md).

Day bucketing happens in Python with core.localtime in the install timezone (never
`substr(col, 1, 10)`, which is a UTC date); SQL compares only against precomputed UTC bounds.
A window of N days is N install-local calendar days ending today, so a DST day is 23 or 25
hours long. Money is integer cents; averages of cents round half up to whole cents in integer
arithmetic. "Days to close" counts local calendar days from the day a deal was created to its
closed_on day, so a same-day win is 0.

Reads run on the thread's connection, never inside transaction(). Every record list (and the
deal rows behind every aggregate) passes through the deal entity's can_read. Any active member
reads any deal today, so the check is cheap, but a restrictive can_read would hold here too.
`fn(...)` reads on the thread connection; `fn_in(conn, ...)` reads on the caller's.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from statistics import median
from typing import TYPE_CHECKING

from backend.apps.crm import deals, settings as crm_settings
from backend.apps.crm.common import CLOSED_STAGES, ENTITY, LIVE, OPEN, OPEN_STAGES, STAGES
from backend.core import clock, db, entities, localtime
from backend.core.reminders import api as reminders

if TYPE_CHECKING:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from backend.core.auth.deps import User

AGE_BUCKETS = ((0, 7, "0-7"), (8, 30, "8-30"), (31, 90, "31-90"), (91, None, "91+"))
STALE_LIMIT = 8  # stale deals listed on the analytics page; stale_count is the full total
STUCK_IN_STAGE_DAYS = 30  # this long in one stage is "stuck" however recently it was touched
DUPLICATE_LIMIT = 20
TIMELINE_TOUCH_TYPES = ("crm.deal", "core.person", "core.organization")

# The open-deal row behind the stale list. Needs `d`.
_OPEN_ROWS = f"""SELECT d.id, d.title, d.value_cents, d.stage, d.owner_user_id, p.name AS person_name,
                        o.name AS organization_name, d.created_at, {deals.LAST_TOUCH} AS last_touch
                   FROM crm_deals d LEFT JOIN core_people p ON p.id = d.person_id
                   LEFT JOIN core_organizations o ON o.id = d.organization_id
                  WHERE {LIVE} AND {OPEN}"""


def readable_in(conn: db.Conn, user: User, rows, key: str = "id") -> list:
    """The rows whose deal (`row[key]`) the user may read."""
    entity = entities.get(ENTITY)
    return [r for r in rows if entity.can_read(user, conn, r[key])]


def whole_days(since: str, now: datetime) -> int:
    """Whole elapsed days since a canonical instant; a future instant (clock skew) is 0."""
    return max(0, (now - clock.parse(since)).days)


def days_to_close(created_at: str, closed_on: str, zone: ZoneInfo) -> int:
    """Local calendar days from the creation day to the closed_on day; never negative
    (a win backdated before creation is 0)."""
    return max(0, (date.fromisoformat(closed_on) - clock.parse(created_at).astimezone(zone).date()).days)


def avg_cents(values: list[int]) -> int | None:
    """The mean of positive cent amounts, rounded half up, exact for any sum."""
    return (2 * sum(values) + len(values)) // (2 * len(values)) if values else None


def _avg(values: list[int | float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def _names_in(conn: db.Conn, ids) -> dict[int, str]:
    """Display names for user ids: name, else email, else "User N"."""
    rows = conn.execute("SELECT id, name, email FROM core_users WHERE id IN (SELECT value FROM json_each(?))", (json.dumps([i for i in ids if i is not None]),))
    return {r["id"]: (r["name"] or "").strip() or r["email"] or f"User {r['id']}" for r in rows}


# ── Stale deals ───────────────────────────────────────────────────────────────


def stale_deals_in(conn: db.Conn, user: User, days: int | None = None, limit: int = 25) -> dict:
    """Live open deals untouched for `days` (default crm.stale_days), longest-quiet first.
    Stale means the last touch (deals.LAST_TOUCH) is strictly older than now minus `days`:
    the badge, Today, deal health and the analytics page all use this comparison."""
    deals._gate(conn, user)
    days = days or crm_settings.stale_days()
    now = clock.now()
    cutoff = clock.to_iso(now - timedelta(days=days))
    rows = readable_in(conn, user, conn.execute(f"{_OPEN_ROWS} AND {deals.LAST_TOUCH} < ? ORDER BY last_touch, d.id", (cutoff,)))
    out = []
    for r in rows:
        row = dict(r)
        row["days_since_touch"] = whole_days(row.pop("last_touch"), now)
        row["age_days"] = whole_days(row.pop("created_at"), now)
        out.append(row)
    return {"stale_days": days, "total_stale": len(out), "count": min(len(out), limit), "deals": out[:limit]}


def stale_deals(user: User, days: int | None = None, limit: int = 25) -> dict:
    return stale_deals_in(db.get_conn(), user, days, limit)


# ── Analytics ─────────────────────────────────────────────────────────────────


def _bucket_ages(open_deals: list, now: datetime) -> list[dict]:
    counts = {label: 0 for _, _, label in AGE_BUCKETS}
    for r in open_deals:
        age = whole_days(r["created_at"], now)
        label = next(lb for lo, hi, lb in AGE_BUCKETS if age >= lo and (hi is None or age <= hi))
        counts[label] += 1
    return [{"label": lb, "min_days": lo, "max_days": hi, "count": counts[lb]} for lo, hi, lb in AGE_BUCKETS]


def _win_loss(rows: list, zone: ZoneInfo) -> dict:
    won = [r for r in rows if r["stage"] == "won"]
    lost = [r for r in rows if r["stage"] == "lost"]
    open_ = [r for r in rows if r["stage"] not in CLOSED_STAGES]
    closed = len(won) + len(lost)
    return {
        "deals_won": len(won),
        "deals_lost": len(lost),
        "open_deals": len(open_),
        # None, not 0: "no closed deals yet" is not a 0% record.
        "win_rate_pct": round(len(won) / closed * 100, 1) if closed else None,
        "avg_won_deal_cents": avg_cents([r["value_cents"] for r in won if r["value_cents"] > 0]),
        "avg_open_deal_cents": avg_cents([r["value_cents"] for r in open_ if r["value_cents"] > 0]),
        "avg_days_to_close": _avg([days_to_close(r["created_at"], r["closed_on"], zone) for r in won if r["closed_on"]]),
        "total_pipeline_value_cents": sum(r["value_cents"] for r in open_),
    }


def _per_rep(conn: db.Conn, rows: list, acts: list, notes: list) -> list[dict]:
    """One row per person, mixing two attributions on purpose: pipeline numbers follow the
    deal's owner (all time), activity numbers follow who acted (in the window), so a rep is
    credited for work on a colleague's deal. `records_touched` (distinct deals, people and
    organizations) is the number to compare reps on; `activity_count` inflates with one bulk
    action. An activity on a deal counts as that deal, else as its person; one linked to
    neither counts as activity but touches no record. NULL is its own "Unattributed" row
    (unowned deals, work no human did) so the numbers still add up."""
    reps: dict[int | None, dict] = {}

    def slot(user_id):
        return reps.setdefault(user_id, {
            "user_id": user_id, "deals_open": 0, "open_value_cents": 0, "deals_won": 0, "deals_lost": 0,
            "won_value_cents": 0, "activity_count": 0, "records_touched": set(),
        })  # fmt: skip

    for r in rows:
        rep = slot(r["owner_user_id"])
        if r["stage"] == "won":
            rep["deals_won"] += 1
            rep["won_value_cents"] += r["value_cents"]
        elif r["stage"] == "lost":
            rep["deals_lost"] += 1
        else:
            rep["deals_open"] += 1
            rep["open_value_cents"] += r["value_cents"]
    for a in acts:
        rep = slot(a["actor_user_id"])
        rep["activity_count"] += 1
        if a["deal_id"] is not None:
            rep["records_touched"].add(("crm.deal", a["deal_id"]))
        elif a["person_id"] is not None:
            rep["records_touched"].add(("core.person", a["person_id"]))
    for n in notes:
        rep = slot(n["author_user_id"])
        rep["activity_count"] += 1
        rep["records_touched"].add((n["entity_type"], n["entity_id"]))
    names = _names_in(conn, reps)
    for user_id, rep in reps.items():
        rep["name"] = "Unattributed" if user_id is None else names.get(user_id, f"User {user_id}")
        rep["records_touched"] = len(rep["records_touched"])
    return sorted(reps.values(), key=lambda r: (
        r["user_id"] is None, -r["records_touched"], -r["open_value_cents"], r["name"].casefold(), r["user_id"] or 0,
    ))  # fmt: skip


def analytics_in(conn: db.Conn, user: User, days: int = 30, stale_days: int | None = None) -> dict:
    """The analytics page: win/loss and per-rep pipeline over every live deal, activity volume
    and per-rep activity over the last `days` local days (7..365), deal aging and the stale
    list over live open deals. A zero state on an empty CRM. `activity.total` is the sum of the
    daily series and of `by_type`: both come from one read of one window."""
    deals._gate(conn, user)
    days = max(7, min(365, int(days)))
    stale_days = stale_days or crm_settings.stale_days()
    zone, now = localtime.tz(), clock.now()
    today = now.astimezone(zone).date()
    first = today - timedelta(days=days - 1)
    lo, hi = clock.to_iso(localtime.local_day_bounds(first)[0]), clock.to_iso(localtime.local_day_bounds(today)[1])

    rows = readable_in(conn, user, conn.execute(
        f"SELECT d.id, d.stage, d.value_cents, d.owner_user_id, d.created_at, d.closed_on FROM crm_deals d WHERE {LIVE}"
    ).fetchall())  # fmt: skip
    # simplification: the window's activity and note rows come to Python (one pass for days,
    # types and reps); fine to ~10^5 rows a request. Upgrade path: GROUP BY in SQL over a
    # stored local-day column.
    acts = conn.execute(
        "SELECT activity, actor_user_id, deal_id, person_id, created_at FROM crm_activity_log WHERE created_at >= ? AND created_at < ?",
        (lo, hi),
    ).fetchall()
    notes = conn.execute(
        """SELECT author_user_id, entity_type, entity_id FROM core_timeline
            WHERE created_at >= ? AND created_at < ? AND kind IN ('note', 'comment') AND archived_at IS NULL
              AND entity_type IN (SELECT value FROM json_each(?))""",
        (lo, hi, json.dumps(TIMELINE_TOUCH_TYPES)),
    ).fetchall()

    per_day = {(first + timedelta(days=i)).isoformat(): 0 for i in range(days)}
    by_type: dict[str, int] = {}
    for a in acts:
        per_day[clock.parse(a["created_at"]).astimezone(zone).date().isoformat()] += 1
        kind = (a["activity"] or "").strip().lower() or "other"
        by_type[kind] = by_type.get(kind, 0) + 1
    stale = stale_deals_in(conn, user, stale_days, STALE_LIMIT)
    return {
        "window_days": days,
        "stale_days": stale_days,
        "timezone": zone.key,
        "win_loss": _win_loss(rows, zone),
        "activity": {
            "daily": [{"day": d, "count": n} for d, n in per_day.items()],
            "by_type": [{"activity": k, "count": n} for k, n in sorted(by_type.items(), key=lambda kv: (-kv[1], kv[0]))],
            "total": len(acts),
        },
        "aging": {
            "buckets": _bucket_ages([r for r in rows if r["stage"] not in CLOSED_STAGES], now),
            "stale_count": stale["total_stale"],
            "stale_deals": stale["deals"],
        },
        "per_rep": _per_rep(conn, rows, acts, notes),
    }


def analytics(user: User, days: int = 30, stale_days: int | None = None) -> dict:
    return analytics_in(db.get_conn(), user, days, stale_days)


# ── Pipeline analytics ────────────────────────────────────────────────────────


def pipeline_analytics_in(conn: db.Conn, user: User, days: int = 90) -> dict:
    """Movement through the funnel from the stage log, over the last `days` local days
    (7..730), live deals only (an archived deal did not convert, it was put away):
    - time_in_stage: completed stays that began in the window; a deal's current stay is open
      and left out rather than clamped to now, which would bias the average down;
    - conversion: each deal's first entry into each open stage in the window, `advanced` when
      the deal now sits in a later stage or won (a move back down the pipeline is not progress);
    - velocity: deals whose closed_on falls in the window, with their mean days to close.
    Every deal's creation writes a stage event, so "entered" includes deals created into a
    stage. `history_covers_window` is false while the log is younger than the window."""
    deals._gate(conn, user)
    days = max(7, min(730, int(days)))
    zone, now = localtime.tz(), clock.now()
    today = now.astimezone(zone).date()
    first = today - timedelta(days=days - 1)
    since = clock.to_iso(localtime.local_day_bounds(first)[0])

    events = readable_in(conn, user, conn.execute(
        f"""SELECT e.deal_id, e.new_stage AS stage, e.changed_at, d.stage AS current_stage,
                   julianday(lead(e.changed_at) OVER (PARTITION BY e.deal_id ORDER BY e.changed_at, e.id))
                     - julianday(e.changed_at) AS days
              FROM crm_deal_stage_events e JOIN crm_deals d ON d.id = e.deal_id
             WHERE {LIVE} ORDER BY e.deal_id, e.changed_at, e.id"""
    ).fetchall(), key="deal_id")  # fmt: skip
    in_window = [e for e in events if e["changed_at"] >= since]

    stays: dict[str, list[float]] = {s: [] for s in OPEN_STAGES}
    for e in in_window:
        if e["days"] is not None and e["stage"] in stays:
            stays[e["stage"]].append(e["days"])
    time_in_stage = [
        {"stage": s, "deals": len(v), "median_days": round(median(v), 1) if v else None, "avg_days": _avg(v)}
        for s, v in stays.items()
    ]

    entered = {s: 0 for s in OPEN_STAGES}
    advanced = {s: 0 for s in OPEN_STAGES}
    seen: set[tuple[int, str]] = set()
    for e in in_window:
        if e["stage"] not in entered or (e["deal_id"], e["stage"]) in seen:
            continue
        seen.add((e["deal_id"], e["stage"]))
        entered[e["stage"]] += 1
        now_at = e["current_stage"]
        if now_at == "won" or (now_at in OPEN_STAGES and STAGES.index(now_at) > STAGES.index(e["stage"])):
            advanced[e["stage"]] += 1
    conversion = [
        {"stage": s, "entered": entered[s], "advanced": advanced[s], "rate_pct": round(advanced[s] / entered[s] * 100, 1) if entered[s] else None}
        for s in OPEN_STAGES
    ]

    won = readable_in(conn, user, conn.execute(
        f"SELECT d.id, d.created_at, d.closed_on FROM crm_deals d WHERE {LIVE} AND d.stage = 'won' AND d.closed_on >= ?",
        (first.isoformat(),),
    ).fetchall())  # fmt: skip
    history_since = conn.execute("SELECT min(changed_at) FROM crm_deal_stage_events").fetchone()[0]
    return {
        "window_days": days,
        "history_since": history_since,
        "history_days": whole_days(history_since, now) if history_since else None,
        "history_covers_window": history_since is not None and history_since <= since,
        "time_in_stage": time_in_stage,
        "conversion": conversion,
        "velocity": {
            "won_in_window": len(won),
            "avg_days_to_won": _avg([days_to_close(r["created_at"], r["closed_on"], zone) for r in won]),
        },
    }


def pipeline_analytics(user: User, days: int = 90) -> dict:
    return pipeline_analytics_in(db.get_conn(), user, days)


# ── Deal health ───────────────────────────────────────────────────────────────


def health_flags(*, operational: bool, stale: bool, days_in_stage: int, next_steps: int, overdue: int,
                 person_id: int | None, organization_id: int | None) -> list[str]:  # fmt: skip
    """The actionable flags. Pure. Stale, stuck, next-step and overdue flags apply only to a
    live open deal (`operational`); a won, lost or archived deal is not going cold."""
    flags = []
    if operational:
        if stale:
            flags.append("stale")
        if days_in_stage >= STUCK_IN_STAGE_DAYS:
            flags.append("stuck_in_stage")
        if not next_steps:
            flags.append("no_next_step")
        if overdue:
            flags.append("overdue_reminder")
    if person_id is None:
        flags.append("missing_person")
    if organization_id is None:
        flags.append("missing_organization")
    return flags


def deal_health_in(conn: db.Conn, user: User, deal_id: int) -> dict:
    """One deal's lead score with the signals a rep acts on. Archived deals resolve (to decide
    whether to restore one). A next step is an open or snoozed core reminder on the deal, by
    anyone; one due before today (install-local) is overdue, one due today is not."""
    deal = deals.get_in(conn, user, deal_id)
    stale_days = crm_settings.stale_days()
    now = clock.now()
    row = conn.execute(
        f"""SELECT {deals.LAST_TOUCH} AS last_touch,
                   coalesce((SELECT max(e.changed_at) FROM crm_deal_stage_events e WHERE e.deal_id = d.id), d.created_at) AS stage_since
              FROM crm_deals d WHERE d.id = ?""",
        (deal_id,),
    ).fetchone()
    today_start = clock.to_iso(localtime.local_day_bounds()[0])
    steps = [r for r in reminders.list_for_record_in(conn, user, ENTITY, deal_id) if r["status"] in ("open", "snoozed")]
    flags = health_flags(
        operational=deal["status"] == "open" and deal["archived_at"] is None,
        stale=row["last_touch"] < clock.to_iso(now - timedelta(days=stale_days)),
        days_in_stage=whole_days(row["stage_since"], now),
        next_steps=len(steps),
        overdue=sum(r["due_at"] < today_start for r in steps),
        person_id=deal["person_id"],
        organization_id=deal["organization_id"],
    )
    # simplification: the stored score with no factors until scoring exposes its breakdown;
    # upgrade path: call the scoring module's per-deal read here.
    return {"deal": deal, "score": deal["lead_score"], "factors": {}, "stale_days": stale_days, "flags": flags}


def deal_health(user: User, deal_id: int) -> dict:
    return deal_health_in(db.get_conn(), user, deal_id)


# ── Duplicates ────────────────────────────────────────────────────────────────


def duplicates_in(conn: db.Conn, user: User, limit: int = DUPLICATE_LIMIT) -> list[dict]:
    """Live deals sharing a title (trimmed, case-folded, otherwise exact) AND a person: the
    double-entry shape. Title alone is a false-positive machine ("Q1 renewal" across ten
    customers), and fuzzy matching would invite merging two real deals. Biggest groups first.
    People and organizations have their own duplicate finder in core contacts."""
    deals._gate(conn, user)
    # simplification: every live deal with a person comes to Python so case-folding is
    # Unicode-aware (SQLite's lower() is ASCII-only); fine to ~10^5 deals. Upgrade path: a
    # stored folded-title column with an index.
    rows = readable_in(conn, user, conn.execute(
        f"SELECT d.id, d.title, d.stage, d.person_id FROM crm_deals d WHERE {LIVE} AND d.person_id IS NOT NULL ORDER BY d.id"
    ).fetchall())  # fmt: skip
    groups: dict[tuple[str, int], list] = {}
    for r in rows:
        if key := r["title"].strip().casefold():
            groups.setdefault((key, r["person_id"]), []).append(r)
    found = sorted(((k, v) for k, v in groups.items() if len(v) > 1), key=lambda kv: (-len(kv[1]), kv[0]))
    return [
        {
            "match_on": "title+person", "value": title, "count": len(members),
            "records": [{"id": r["id"], "label": f"{r['title']} ({r['stage']})"} for r in members],
        }
        for (title, _person), members in found[:limit]
    ]  # fmt: skip


def duplicates(user: User) -> list[dict]:
    return duplicates_in(db.get_conn(), user)
