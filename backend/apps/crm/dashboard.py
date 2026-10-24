"""The CRM home: headline numbers, the Today list and Weekly Touches. Ported from CakeCRM's
crm/service.py dashboard section and crm/today_service.py (docs/PROVENANCE.md).

Day boundaries are install-local (core.localtime); SQL compares only against precomputed UTC
bounds. Every read is over live (unarchived) deals, runs on the thread's connection (never in
transaction()), and passes its deal rows through the deal entity's can_read.
`fn(...)` reads on the thread connection; `fn_in(conn, ...)` reads on the caller's.

Today: one ranked list of what needs the caller today. No AI: "hot" is a temperature only a
person sets, "stale" is analytics.stale_deals' comparison. Rank 1 is a hot deal gone quiet, at
most HOT_DEAL_SLOTS of them so a neglected pipeline never buries the caller's own reminders;
rank 2 is each of the caller's open or snoozed reminders due today; every other hot deal
(fresh, or stale past the cap) follows with rank null, most idle first, reachable only from
the expanded list. `reason` is hot_stale | hot | reminder.

Weekly Touches: per owner, the live open deals and the deals touched in a window of
install-local days (default the last 7, today included). A deal's touch instant is its last
touch (deals.LAST_TOUCH: edit, activity, live note), except that a won deal is dated by its
latest move into won, so the week a rep worked and closed a deal keeps every touch on it and
a note typed after the win moves nothing. Creation is not a touch. Lost and archived deals
count for nothing. `open_deals` means currently open, so a deal won this week is touched but
not open and touches can exceed it. Every owner of an open deal gets a row (seeing who did
nothing is the point); unowned deals are one "Unassigned" bucket, so totals are the sums of
the rows. Counts and rows come from one statement, so they describe one snapshot.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

from backend.apps.crm import activity, deals, settings as crm_settings
from backend.apps.crm.analytics import readable_in
from backend.apps.crm.common import LIVE, OPEN, day
from backend.core import clock, db, localtime, pagination
from backend.core.errors import Invalid, NotFound
from backend.core.reminders import api as reminders

if TYPE_CHECKING:
    from backend.core.auth.deps import User

# Attention, not expected value: value is the base and probability swings it by at most 60%,
# so a big likely deal outranks a small near-certain one and a $0 deal scores 0.
TOP_DEAL_SCORE = "(max(d.value_cents, 0) * (0.4 + 0.6 * min(max(d.probability, 0), 100) / 100.0))"
HOT_DEAL_SLOTS = 2
WEEKLY_TOUCHES_LIMIT = 10  # deals listed under each rep on the card
WEEKLY_TOUCHES_DETAIL_MAX = 500  # the drill-down's ceiling; `truncated` says when a book passes it

# When a deal earned its touch (see the module docstring). A won deal with no win event counts
# for nothing (NULL fails every window test). Needs `d`.
TOUCH_AT = f"""CASE WHEN d.stage = 'won'
    THEN (SELECT max(e.changed_at) FROM crm_deal_stage_events e WHERE e.deal_id = d.id AND e.new_stage = 'won')
    ELSE {deals.LAST_TOUCH} END"""


def _live_count(conn: db.Conn, table: str) -> int:
    return conn.execute(f"SELECT count(*) FROM {table} WHERE merged_into_id IS NULL AND archived_at IS NULL").fetchone()[0]


def dashboard_in(conn: db.Conn, user: User) -> dict:
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
        "top_deals": [dict(r) for r in readable_in(conn, user, top)],
    }


def dashboard(user: User) -> dict:
    return dashboard_in(db.get_conn(), user)


# ── Today ─────────────────────────────────────────────────────────────────────


def today_in(conn: db.Conn, user: User) -> dict:
    """The full ranked list (the client shows the first ranked rows and "+N more"), the day it
    was built for, and `next_refresh_at`, the next local midnight, derived from that same day
    so a request straddling midnight cannot list one day and arm the reload for another."""
    deals._gate(conn, user)
    today = localtime.today_local()
    start, end = (clock.to_iso(b) for b in localtime.local_day_bounds(today))
    cutoff = clock.ago(crm_settings.stale_days() * 86400)
    hot = conn.execute(
        f"""SELECT x.*, h.last_touch FROM ({deals.SELECT} WHERE {LIVE} AND {OPEN} AND d.deal_temperature = 'hot') x
              JOIN (SELECT d.id, {deals.LAST_TOUCH} AS last_touch FROM crm_deals d
                     WHERE {LIVE} AND {OPEN} AND d.deal_temperature = 'hot') h ON h.id = x.id
             ORDER BY h.last_touch, x.id"""
    )
    ranked, tail = [], []
    for row in readable_in(conn, user, hot):
        deal = dict(row)
        stale = deal.pop("last_touch") < cutoff
        if stale and len(ranked) < HOT_DEAL_SLOTS:
            ranked.append({"kind": "deal", "rank": 1, "reason": "hot_stale", "deal": deal})
        else:
            tail.append({"kind": "deal", "rank": None, "reason": "hot_stale" if stale else "hot", "deal": deal})
    due = reminders.list_mine_in(conn, user, from_=start, to=end, limit=pagination.MAX_LIMIT)
    ranked += [{"kind": "reminder", "rank": 2, "reason": "reminder", "reminder": r} for r in due if r["status"] in ("open", "snoozed")]
    return {"date": today.isoformat(), "next_refresh_at": end, "items": ranked + tail}


def today(user: User) -> dict:
    return today_in(db.get_conn(), user)


# ── Weekly Touches ────────────────────────────────────────────────────────────


def _window(start: str | None, end: str | None) -> tuple[str, str, dict]:
    """`[lo, hi)` UTC bounds and the TouchWindow. Neither day: the last 7 local days, today
    included. Both: those local days, the end day whole. One alone, a reversed range or a
    malformed day is Invalid (a blank value is a cleared filter, so it counts as absent)."""
    start, end = (start or "").strip() or None, (end or "").strip() or None
    if start is None and end is None:
        last = localtime.today_local()
        first, label = last - timedelta(days=6), "Last 7 days"
    elif start is None or end is None:
        raise Invalid("A custom range needs both start and end")
    else:
        first, last = date.fromisoformat(day(start, "start")), date.fromisoformat(day(end, "end"))
        if last < first:
            raise Invalid("end must be on or after start")
        label = f"{start} – {end}"
    try:
        lo, hi = clock.to_iso(localtime.local_day_bounds(first)[0]), clock.to_iso(localtime.local_day_bounds(last)[1])
    except OverflowError:
        raise Invalid("That range is out of bounds") from None
    window = {"start": first.isoformat(), "end": last.isoformat(), "label": label, "custom": start is not None}
    return lo, hi, window


def _touch_rows_in(conn: db.Conn, user: User, lo: str, hi: str, owner_sql: str = "", owner_params: tuple = ()) -> list:
    """Every live open deal, plus every deal won in the window, with `in_window`. The window
    test is written once and read for both the roster and the touch count."""
    rows = conn.execute(
        f"""SELECT * FROM (
              SELECT t.*, (t.touched_at >= ? AND t.touched_at < ? AND t.touched_at != t.created_at) AS in_window
                FROM (SELECT d.id, d.title, d.value_cents, d.stage, d.owner_user_id, d.ai_touch_count AS touch_count,
                             {TOUCH_AT} AS touched_at, d.created_at, p.name AS person_name, o.name AS organization_name,
                             u.name AS owner_name, u.email AS owner_email
                        FROM crm_deals d
                        LEFT JOIN core_people p ON p.id = d.person_id
                        LEFT JOIN core_organizations o ON o.id = d.organization_id
                        LEFT JOIN core_users u ON u.id = d.owner_user_id
                       WHERE {LIVE} AND d.stage != 'lost'{owner_sql}) t)
             WHERE stage != 'won' OR in_window""",
        (lo, hi, *owner_params),
    )
    return readable_in(conn, user, rows)


def _rep_name(user_id: int | None, name: str | None, email: str | None) -> str:
    if user_id is None:
        return "Unassigned"
    return (name or "").strip() or email or f"User {user_id}"


def _reps(rows: list, cap: int) -> list[dict]:
    """One bucket per owner with its counts and its touched deals, most touches first (by AI
    touch count, then newest), capped per rep. Reps: busiest first, Unassigned last."""
    reps: dict[int | None, dict] = {}
    for r in rows:
        uid = r["owner_user_id"]
        rep = reps.setdefault(uid, {"user_id": uid, "name": _rep_name(uid, r["owner_name"], r["owner_email"]), "open_deals": 0, "touches": 0, "deals": []})
        if r["stage"] != "won":
            rep["open_deals"] += 1
        if r["in_window"]:
            rep["touches"] += 1
            rep["deals"].append({k: r[k] for k in (
                "id", "title", "value_cents", "stage", "owner_user_id", "touch_count", "touched_at", "person_name", "organization_name",
            )})  # fmt: skip
    for rep in reps.values():
        rep["deals"].sort(key=lambda d: (d["touch_count"] is None, -(d["touch_count"] or 0), -d["id"]))
        del rep["deals"][cap:]
    return sorted(reps.values(), key=lambda s: (s["user_id"] is None, -s["touches"], -s["open_deals"], s["name"].casefold(), s["user_id"] or 0))


def weekly_touches_in(conn: db.Conn, user: User, start: str | None = None, end: str | None = None) -> dict:
    deals._gate(conn, user)
    lo, hi, window = _window(start, end)
    reps = _reps(_touch_rows_in(conn, user, lo, hi), WEEKLY_TOUCHES_LIMIT)
    return {
        "window": window,
        "reps": reps,
        "total_touches": sum(r["touches"] for r in reps),
        "total_open_deals": sum(r["open_deals"] for r in reps),
    }


def weekly_touches(user: User, start: str | None = None, end: str | None = None) -> dict:
    return weekly_touches_in(db.get_conn(), user, start, end)


def weekly_touch_detail_in(conn: db.Conn, user: User, owner: str, start: str | None = None, end: str | None = None) -> dict:
    """One owner bucket in full (`owner`: a user id or 'unassigned'), up to
    WEEKLY_TOUCHES_DETAIL_MAX deals with `truncated` past it. The window is resolved afresh,
    not frozen from the card, so a deal worked from this page stays on it. A rep with nothing
    open and nothing won is a zero row; an unknown user is NotFound. `rep.deals` is empty: the
    list is the top-level `deals`."""
    deals._gate(conn, user)
    lo, hi, window = _window(start, end)
    if owner == "unassigned":
        uid, name, owner_sql, params = None, "Unassigned", " AND d.owner_user_id IS NULL", ()
    else:
        found = conn.execute("SELECT id, name, email FROM core_users WHERE id = ? AND role != 'system'", (int(owner),)).fetchone()
        if found is None:
            raise NotFound()
        uid, name, owner_sql, params = found["id"], _rep_name(found["id"], found["name"], found["email"]), " AND d.owner_user_id = ?", (found["id"],)
    reps = _reps(_touch_rows_in(conn, user, lo, hi, owner_sql, params), WEEKLY_TOUCHES_DETAIL_MAX)
    rep = reps[0] if reps else {"user_id": uid, "open_deals": 0, "touches": 0, "deals": []}
    listed = rep["deals"]
    return {"window": window, "rep": {**rep, "name": name, "deals": []}, "deals": listed, "truncated": rep["touches"] > len(listed)}


def weekly_touch_detail(user: User, owner: str, start: str | None = None, end: str | None = None) -> dict:
    return weekly_touch_detail_in(db.get_conn(), user, owner, start, end)
