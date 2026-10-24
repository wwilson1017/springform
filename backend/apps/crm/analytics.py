"""Keyless CRM analytics: win/loss, activity volume, deal aging, per-rep numbers, stage
durations and conversion, stale deals, deal health and duplicate deals. Ported from CakeCRM's
crm/service.py analytics section and crm/analytics_service.py (docs/PROVENANCE.md).

Day bucketing happens in Python with core.localtime in the install timezone (never the first
ten characters of a stored timestamp, which are a UTC date); SQL compares only against
precomputed UTC bounds. Money is integer cents; averages of cents round to whole cents. Every
read is over live (unarchived) deals: an archived deal is findable, never counted.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING

from backend.apps.crm import deals, scoring, settings as crm_settings
from backend.apps.crm.common import LIVE, OPEN, OPEN_STAGES
from backend.core import clock, db, localtime

if TYPE_CHECKING:
    from backend.core.auth.deps import User

AGE_BUCKETS = ((0, 7, "0-7"), (8, 30, "8-30"), (31, 90, "31-90"), (91, None, "91+"))
STUCK_IN_STAGE_DAYS = 30
DAY = 86400
NOTE_ENTITIES = ("crm.deal", "core.person", "core.organization")


def _midnight(day: date) -> str:
    """The canonical UTC instant of a local day's start, honest across DST."""
    return clock.to_iso(datetime.combine(day, time.min, tzinfo=localtime.tz()))


def _local_day(instant: str) -> str:
    return clock.parse(instant).astimezone(localtime.tz()).date().isoformat()


def _days_between(start: str, end: str) -> float:
    return (clock.parse(end) - clock.parse(start)).total_seconds() / DAY


def _avg_cents(values: list[int]) -> int | None:
    return round(sum(values) / len(values)) if values else None


# ── Outcomes ──────────────────────────────────────────────────────────────────


def _win_loss(conn: db.Conn) -> dict:
    rows = [dict(r) for r in conn.execute(
        f"""SELECT d.stage, d.value_cents, d.created_at,
                   (SELECT max(e.changed_at) FROM crm_deal_stage_events e WHERE e.deal_id = d.id AND e.new_stage = 'won') AS won_at
              FROM crm_deals d WHERE {LIVE}"""
    )]  # fmt: skip
    won = [r for r in rows if r["stage"] == "won"]
    lost = [r for r in rows if r["stage"] == "lost"]
    open_ = [r for r in rows if r["stage"] in OPEN_STAGES]
    closed = len(won) + len(lost)
    to_close = [max(0.0, _days_between(r["created_at"], r["won_at"])) for r in won if r["won_at"]]
    return {
        "deals_won": len(won), "deals_lost": len(lost), "open_deals": len(open_),
        "win_rate_pct": round(len(won) / closed * 100, 1) if closed else None,
        "avg_won_deal_cents": _avg_cents([r["value_cents"] for r in won if r["value_cents"] > 0]),
        "avg_open_deal_cents": _avg_cents([r["value_cents"] for r in open_ if r["value_cents"] > 0]),
        "avg_days_to_close": round(sum(to_close) / len(to_close), 1) if to_close else None,
        "total_pipeline_value_cents": sum(r["value_cents"] for r in open_),
    }


def _open_rows(conn: db.Conn) -> list[dict]:
    """Live open deals with their whole-day age and days since the last touch."""
    now = clock.now()
    rows = conn.execute(
        f"""SELECT d.id, d.title, d.value_cents, d.stage, d.owner_user_id, p.name AS person_name,
                   o.name AS organization_name, d.created_at, {deals.LAST_TOUCH} AS last_touch
              FROM crm_deals d LEFT JOIN core_people p ON p.id = d.person_id
              LEFT JOIN core_organizations o ON o.id = d.organization_id
             WHERE {LIVE} AND {OPEN}"""
    )
    out = []
    for r in rows:
        row = dict(r)
        row["age_days"] = max(0, (now - clock.parse(row.pop("created_at"))).days)
        row["days_since_touch"] = max(0, (now - clock.parse(row.pop("last_touch"))).days)
        out.append(row)
    return out


def _aging(open_rows: list[dict], stale_days: int, limit: int) -> dict:
    counts = Counter()
    for r in open_rows:
        counts[next(label for lo, hi, label in AGE_BUCKETS if r["age_days"] >= lo and (hi is None or r["age_days"] <= hi))] += 1
    stale = sorted((r for r in open_rows if r["days_since_touch"] >= stale_days), key=lambda r: (-r["days_since_touch"], r["id"]))
    return {
        "buckets": [{"label": label, "min_days": lo, "max_days": hi, "count": counts[label]} for lo, hi, label in AGE_BUCKETS],
        "stale_count": len(stale),
        "stale_deals": stale[:limit],
    }


def _activity(conn: db.Conn, days: int) -> tuple[dict, str, str]:
    """The activity series over the last `days` install-local days (today included), bucketed
    by local day in Python. Returns the stats and the window's UTC bounds."""
    today = localtime.today_local()
    first = today - timedelta(days=days - 1)
    start, end = _midnight(first), _midnight(today + timedelta(days=1))
    rows = conn.execute("SELECT activity, created_at FROM crm_activity_log WHERE created_at >= ? AND created_at < ?", (start, end)).fetchall()
    per_day = Counter(_local_day(r["created_at"]) for r in rows)
    kinds = Counter((r["activity"] or "").strip().lower() or "other" for r in rows)
    daily = [{"day": d.isoformat(), "count": per_day[d.isoformat()]} for d in (first + timedelta(days=i) for i in range(days))]
    by_type = [{"activity": k, "count": n} for k, n in sorted(kinds.items(), key=lambda kv: (-kv[1], kv[0]))]
    return {"daily": daily, "by_type": by_type, "total": len(rows)}, start, end


def _per_rep(conn: db.Conn, start: str, end: str) -> list[dict]:
    """Pipeline numbers follow ownership; activity numbers follow who acted (credit for work on
    a colleague's record). Work no human did rolls up as Unattributed, last."""
    reps: dict[int | None, dict] = {}

    def slot(user_id):
        return reps.setdefault(user_id, {
            "user_id": user_id, "name": "", "deals_open": 0, "open_value_cents": 0, "deals_won": 0, "deals_lost": 0,
            "won_value_cents": 0, "activity_count": 0, "records_touched": 0,
        })  # fmt: skip

    for r in conn.execute(f"SELECT d.owner_user_id, d.stage, d.value_cents FROM crm_deals d WHERE {LIVE}"):
        s = slot(r["owner_user_id"])
        if r["stage"] == "won":
            s["deals_won"] += 1
            s["won_value_cents"] += r["value_cents"]
        elif r["stage"] == "lost":
            s["deals_lost"] += 1
        else:
            s["deals_open"] += 1
            s["open_value_cents"] += r["value_cents"]
    acts = conn.execute(
        """SELECT actor_user_id AS actor, CASE WHEN deal_id IS NOT NULL THEN 'crm.deal' WHEN person_id IS NOT NULL THEN 'core.person'
                                               ELSE 'activity' END AS kind, coalesce(deal_id, person_id, id) AS record
             FROM crm_activity_log WHERE created_at >= ? AND created_at < ?
           UNION ALL
           SELECT author_user_id, entity_type, entity_id FROM core_timeline
            WHERE kind IN ('note', 'comment') AND archived_at IS NULL AND created_at >= ? AND created_at < ?
              AND entity_type IN (SELECT value FROM json_each(?))""",
        (start, end, start, end, json.dumps(NOTE_ENTITIES)),
    ).fetchall()
    touched: dict[int | None, set] = {}
    for r in acts:
        actor = r["actor"] or None  # the system principal (0) did no human's work
        slot(actor)["activity_count"] += 1
        if r["kind"] != "activity":
            touched.setdefault(actor, set()).add((r["kind"], r["record"]))
    for actor, records in touched.items():
        reps[actor]["records_touched"] = len(records)
    names = {r[0]: r[1] or r[2] for r in conn.execute(
        "SELECT id, name, email FROM core_users WHERE id IN (SELECT value FROM json_each(?))", (json.dumps([u for u in reps if u]),)
    )}  # fmt: skip
    for user_id, r in reps.items():
        r["name"] = names.get(user_id, "") if user_id else "Unattributed"
    return sorted(reps.values(), key=lambda r: (r["user_id"] is None, -r["records_touched"], -r["open_value_cents"]))


def analytics(user: User, days: int = 30, stale_days: int | None = None, stale_limit: int = 8) -> dict:
    conn = db.get_conn()
    deals._gate(conn, user)
    days = max(7, min(365, int(days)))
    stale_days = max(1, min(365, int(stale_days or crm_settings.stale_days())))
    activity, start, end = _activity(conn, days)
    return {
        "window_days": days, "stale_days": stale_days, "timezone": localtime.tz().key,
        "win_loss": _win_loss(conn),
        "activity": activity,
        "aging": _aging(_open_rows(conn), stale_days, stale_limit),
        "per_rep": _per_rep(conn, start, end),
    }


def stale_deals(user: User, days: int | None = None, limit: int = 25) -> dict:
    """Live open deals untouched for `days` (default crm.stale_days), longest-quiet first."""
    conn = db.get_conn()
    deals._gate(conn, user)
    days = days or crm_settings.stale_days()
    aging = _aging(_open_rows(conn), days, limit)
    return {"stale_days": days, "total_stale": aging["stale_count"], "count": len(aging["stale_deals"]), "deals": aging["stale_deals"]}


# ── The funnel ────────────────────────────────────────────────────────────────


def pipeline_analytics(user: User, days: int = 90) -> dict:
    """Movement through the funnel, read from the stage history: time in stage (finished
    intervals only, so a deal still sitting in a stage is not counted as having left now),
    conversion of each first entry into a stage, and velocity of the wins in the window. The
    history starts when the CRM was installed; the response says how far back it goes."""
    conn = db.get_conn()
    deals._gate(conn, user)
    days = max(7, min(730, int(days)))
    cutoff = clock.ago(days * DAY)
    events = [dict(r) for r in conn.execute(
        f"""SELECT e.deal_id, e.new_stage, e.changed_at, d.stage AS current_stage, d.closed_on,
                   lead(e.changed_at) OVER (PARTITION BY e.deal_id ORDER BY e.changed_at, e.id) AS next_at,
                   row_number() OVER (PARTITION BY e.deal_id, e.new_stage ORDER BY e.changed_at, e.id) AS nth
              FROM crm_deal_stage_events e JOIN crm_deals d ON d.id = e.deal_id WHERE {LIVE}"""
    )]  # fmt: skip
    in_window = [e for e in events if e["changed_at"] >= cutoff]

    durations: dict[str, list[float]] = {s: [] for s in OPEN_STAGES}
    for e in in_window:
        if e["next_at"] and e["new_stage"] in durations:
            durations[e["new_stage"]].append(_days_between(e["changed_at"], e["next_at"]))
    time_in_stage = [
        {"stage": s, "samples": len(v), "avg_days": round(sum(v) / len(v), 1) if v else None,
         "median_days": round(statistics.median(v), 1) if v else None}
        for s, v in durations.items()
    ]  # fmt: skip

    conversion = []
    for stage in OPEN_STAGES:
        firsts = [e for e in in_window if e["new_stage"] == stage and e["nth"] == 1]
        outcome = Counter(
            "won" if e["current_stage"] == "won" else "lost" if e["current_stage"] == "lost"
            else "still_here" if e["current_stage"] == stage else "advanced"
            for e in firsts
        )  # fmt: skip
        entered = len(firsts)
        conversion.append({
            "stage": stage, "entered": entered, "still_here": outcome["still_here"], "advanced": outcome["advanced"],
            "won": outcome["won"], "lost": outcome["lost"],
            "progression_rate": round((outcome["advanced"] + outcome["won"]) / entered, 3) if entered else None,
            "win_rate": round(outcome["won"] / entered, 3) if entered else None,
        })  # fmt: skip

    by_deal: dict[int, list[dict]] = {}
    for e in events:
        by_deal.setdefault(e["deal_id"], []).append(e)
    took = []
    for rows in by_deal.values():
        if rows[0]["current_stage"] != "won":
            continue
        wins = [e["changed_at"] for e in rows if e["new_stage"] == "won"]
        # A recorded Closed on day (wins are often recorded late) dates the win at local midnight.
        won_at = _midnight(date.fromisoformat(rows[0]["closed_on"])) if rows[0]["closed_on"] else max(wins, default=None)
        if won_at and won_at >= cutoff:
            took.append(max(0.0, _days_between(min(e["changed_at"] for e in rows), won_at)))

    since = conn.execute("SELECT min(changed_at) FROM crm_deal_stage_events").fetchone()[0]
    history_days = int(_days_between(since, clock.now_iso())) if since else None
    return {
        "window_days": days, "history_since": since, "history_days": history_days,
        "history_covers_window": history_days is not None and history_days >= days,
        "time_in_stage": time_in_stage, "conversion": conversion,
        "velocity": {"won_in_window": len(took), "avg_days_to_won": round(sum(took) / len(took), 1) if took else None},
    }


# ── One deal ──────────────────────────────────────────────────────────────────


def _todo_counts(user: User, deal_id: int) -> tuple[int, int] | None:
    """(open, overdue) to-dos linked to the deal, through the Todos app's published API; None
    when that app is not installed."""
    try:
        from backend.apps.todos.api import list_for_record
    except ModuleNotFoundError:
        return None
    today = localtime.today_local().isoformat()
    todos = list_for_record(user, "crm.deal", deal_id)
    return len(todos), sum(1 for t in todos if t.get("due_date") and t["due_date"] < today)


def deal_health(user: User, deal_id: int) -> dict:
    """The lead score with its factors, plus the flags a person acts on: stale, stuck in its
    stage, no next step, an overdue to-do, no person, no organization. Archived deals answer too."""
    conn = db.get_conn()
    deal = deals.get_in(conn, user, deal_id)
    stale_days = crm_settings.stale_days()
    now = clock.now()
    last_touch = conn.execute(f"SELECT {deals.LAST_TOUCH} FROM crm_deals d WHERE d.id = ?", (deal_id,)).fetchone()[0]
    entered = conn.execute("SELECT max(changed_at) FROM crm_deal_stage_events WHERE deal_id = ?", (deal_id,)).fetchone()[0]
    flags = []
    if deal["status"] == "open":
        if (now - clock.parse(last_touch)).days >= stale_days:
            flags.append("stale")
        if (now - clock.parse(entered or deal["created_at"])).days >= STUCK_IN_STAGE_DAYS:
            flags.append("stuck_in_stage")
        if (todos := _todo_counts(user, deal_id)) is not None:
            if not todos[0]:
                flags.append("no_next_step")
            if todos[1]:
                flags.append("overdue_todo")
    if not deal["person_id"]:
        flags.append("missing_person")
    if not deal["organization_id"]:
        flags.append("missing_organization")
    breakdown = scoring.deal_breakdown_in(conn, deal_id, now)
    return {"deal": deal, "score": breakdown["score"], "factors": breakdown["factors"], "stale_days": stale_days, "flags": flags}


def duplicates(user: User, limit: int = 25) -> list[dict]:
    """Live deals sharing a title (ignoring case and spacing) and the same person: the real
    double-entry shape. Title alone is not a duplicate ("Q1 renewal" across ten customers)."""
    conn = db.get_conn()
    deals._gate(conn, user)
    groups = conn.execute(
        f"""SELECT lower(trim(d.title)) AS value, d.person_id, count(*) AS count, json_group_array(d.id) AS ids
              FROM (SELECT * FROM crm_deals d WHERE {LIVE} AND trim(d.title) != '' AND d.person_id IS NOT NULL ORDER BY d.id) d
             GROUP BY lower(trim(d.title)), d.person_id HAVING count(*) > 1
             ORDER BY count(*) DESC, value, d.person_id LIMIT ?""",
        (limit,),
    ).fetchall()
    ids = [i for g in groups for i in json.loads(g["ids"])]
    labels = {r[0]: f"{r[1]} ({r[2]})" for r in conn.execute(
        "SELECT id, title, stage FROM crm_deals WHERE id IN (SELECT value FROM json_each(?))", (json.dumps(ids),)
    )}  # fmt: skip
    return [
        {"match_on": "title+person", "value": g["value"], "count": g["count"],
         "records": [{"id": i, "label": labels[i]} for i in json.loads(g["ids"])]}
        for g in groups
    ]  # fmt: skip
