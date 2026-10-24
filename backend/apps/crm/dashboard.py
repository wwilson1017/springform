"""The CRM home: headline numbers, the Today list and Weekly Touches. Ported from CakeCRM's
crm/service.py dashboard section and crm/today_service.py (docs/PROVENANCE.md).

Day boundaries are install-local (core.localtime); SQL compares only against precomputed UTC
bounds. Every read is over live (unarchived) deals.

Today is one ranked list of what needs the caller: their hot deals (or unowned ones) that have
gone quiet take rank 1 (at most HOT_DEAL_SLOTS, so a neglected pipeline never buries a person's
own commitments), their reminders due today rank 2, and every other hot deal follows unranked,
for the expanded list. To-dos have their own Today in the Todos app.

Weekly touches is an accountability pull per owner: how many of their live deals were touched
in the window. A deal's touch instant is its last touch, or for a won deal its win (the stage
event), so a note typed after the win moves nothing and closing the deal counts.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING

from backend.apps.crm import activity, deals, settings as crm_settings
from backend.apps.crm.analytics import readable_in
from backend.apps.crm.common import LIVE, OPEN
from backend.core import clock, db, localtime
from backend.core.errors import Invalid, NotFound
from backend.core.reminders import api as reminders

if TYPE_CHECKING:
    from backend.core.auth.deps import User

HOT_DEAL_SLOTS = 2
WEEKLY_TOUCHES_LIMIT = 10  # deals shown under each owner on the card
WEEKLY_TOUCHES_DETAIL_MAX = 500  # the drill-down says when it stops short
# Attention, not expected value: value is the base and probability swings it by at most 60%,
# so a big likely deal outranks a small near-certain one and a $0 deal scores 0.
TOP_DEAL_SCORE = "(max(d.value_cents, 0) * (0.4 + 0.6 * min(max(d.probability, 0), 100) / 100.0))"


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


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=localtime.tz())


def today_in(conn: db.Conn, user: User) -> dict:
    deals._gate(conn, user)
    day = localtime.today_local()
    start, end = _midnight(day), _midnight(day + timedelta(days=1))
    now, stale_cutoff = clock.now(), clock.ago(crm_settings.stale_days() * 86400)
    hot = conn.execute(
        f"""{deals.SELECT} WHERE {LIVE} AND {OPEN} AND d.deal_temperature = 'hot'
             AND (d.owner_user_id = ? OR d.owner_user_id IS NULL)""",
        (user.id,),
    ).fetchall()
    touches = {r[0]: r[1] for r in conn.execute(
        f"SELECT d.id, {deals.LAST_TOUCH} FROM crm_deals d WHERE d.deal_temperature = 'hot' AND {LIVE} AND {OPEN}"
    )}  # fmt: skip
    ranked, tail = [], []
    for deal in sorted((dict(r) for r in readable_in(conn, user, hot)), key=lambda d: (touches[d["id"]], d["id"])):  # most idle first
        idle = max(0, (now - clock.parse(touches[deal["id"]])).days)
        if touches[deal["id"]] < stale_cutoff:
            item = {"kind": "deal", "reason": f"Hot, quiet for {idle} days", "deal": deal}
            (ranked if len(ranked) < HOT_DEAL_SLOTS else tail).append(item)
        else:
            tail.append({"kind": "deal", "reason": "Hot", "deal": deal})
    due = [
        {"kind": "reminder", "rank": 2, "reason": "Reminder due today", "reminder": r}
        for r in reminders.list_mine_in(conn, user, from_=clock.to_iso(start), to=clock.to_iso(end))
        if r["status"] in ("open", "snoozed")  # done and voided reminders need nobody today
    ]
    items = [{**i, "rank": 1} for i in ranked] + due + [{**i, "rank": None} for i in tail]
    return {"date": day.isoformat(), "next_refresh_at": clock.to_iso(end), "items": items}


def today(user: User) -> dict:
    return today_in(db.get_conn(), user)


_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _window(start: str | None, end: str | None) -> dict:
    """[start, end) as UTC instants. No bounds: the rolling last seven days, re-resolved on
    every request. Both: whole install-local days, the end day included. One alone is refused."""
    start, end = (start or "").strip() or None, (end or "").strip() or None
    if start is None and end is None:
        return {"start": clock.ago(7 * 86400), "end": clock.now_iso(), "label": "Last 7 days", "custom": False}
    if start is None or end is None:
        raise Invalid("A custom range needs both start and end")
    try:
        first, last = (date.fromisoformat(v) for v in (start, end) if _DAY.match(v))
    except ValueError:
        raise Invalid("start and end must be YYYY-MM-DD dates") from None
    if last < first:
        raise Invalid("end must be on or after start")
    try:
        bounds = clock.to_iso(_midnight(first)), clock.to_iso(_midnight(last + timedelta(days=1)))
    except OverflowError:  # 9999-12-31 has no next day
        raise Invalid("That range is out of bounds") from None
    return {"start": bounds[0], "end": bounds[1], "label": f"{start} – {end}", "custom": True}


def _touch_rows(conn: db.Conn, user: User, window: dict) -> list[dict]:
    """Live open deals and live won deals the user can read, each with its touch instant and
    whether it falls in the window. Creation is not a touch, or a fresh import would read as a
    week of work: a won deal counts only a real move into won (creation writes a stage event
    with no old stage), and an open deal counts once it has an activity or note, or an edit
    after creation. Timestamps are whole seconds, so the test is about events, not instants."""
    rows = conn.execute(
        f"""SELECT d.id, d.title, d.value_cents, d.stage, d.owner_user_id, d.ai_touch_count AS touch_count,
                   p.name AS person_name, o.name AS organization_name, u.name AS owner_name,
                   d.created_at, {deals.LAST_ACTIVITY} AS last_activity_at,
                   CASE WHEN d.stage = 'won' THEN (SELECT max(e.changed_at) FROM crm_deal_stage_events e
                                                    WHERE e.deal_id = d.id AND e.new_stage = 'won' AND e.old_stage != '')
                        ELSE {deals.LAST_TOUCH} END AS touched_at
              FROM crm_deals d LEFT JOIN core_people p ON p.id = d.person_id
              LEFT JOIN core_organizations o ON o.id = d.organization_id
              LEFT JOIN core_users u ON u.id = d.owner_user_id
             WHERE {LIVE} AND (d.stage = 'won' OR {OPEN})"""
    )
    out = []
    for r in readable_in(conn, user, rows):
        row = dict(r)
        worked = row["stage"] == "won" or row["last_activity_at"] is not None or row["touched_at"] != row["created_at"]
        row["in_window"] = worked and row["touched_at"] is not None and window["start"] <= row["touched_at"] < window["end"]
        out.append(row)
    return out


def _reps(rows: list[dict], cap: int) -> list[dict]:
    """One row per owner of a live open deal or of a deal won in the window; unowned deals are
    the Unassigned row. Busiest first, Unassigned last."""
    reps: dict[int | None, dict] = {}
    for r in rows:
        if r["stage"] == "won" and not r["in_window"]:
            continue
        rep = reps.setdefault(r["owner_user_id"], {
            "user_id": r["owner_user_id"], "name": r["owner_name"] or ("Unassigned" if r["owner_user_id"] is None else ""),
            "open_deals": 0, "touches": 0, "deals": [],
        })  # fmt: skip
        rep["open_deals"] += r["stage"] != "won"
        if r["in_window"]:
            rep["touches"] += 1
            rep["deals"].append({k: r[k] for k in ("id", "title", "value_cents", "stage", "owner_user_id", "touch_count", "touched_at", "person_name", "organization_name")})
    for rep in reps.values():
        rep["deals"].sort(key=lambda d: (d["touch_count"] is None, -(d["touch_count"] or 0), -d["id"]))
        rep["truncated"] = len(rep["deals"]) > cap
        rep["deals"] = rep["deals"][:cap]
    return sorted(reps.values(), key=lambda r: (r["user_id"] is None, -r["touches"], r["name"].lower()))


def weekly_touches_in(conn: db.Conn, user: User, start: str | None = None, end: str | None = None) -> dict:
    deals._gate(conn, user)
    window = _window(start, end)
    reps = _reps(_touch_rows(conn, user, window), WEEKLY_TOUCHES_LIMIT)
    for rep in reps:
        del rep["truncated"]
    return {
        "window": window, "reps": reps,
        "total_touches": sum(r["touches"] for r in reps), "total_open_deals": sum(r["open_deals"] for r in reps),
    }  # fmt: skip


def weekly_touches(user: User, start: str | None = None, end: str | None = None) -> dict:
    return weekly_touches_in(db.get_conn(), user, start, end)


def weekly_touch_detail_in(conn: db.Conn, user: User, owner: str, start: str | None = None, end: str | None = None) -> dict:
    """One owner's touched deals, uncapped up to WEEKLY_TOUCHES_DETAIL_MAX. `owner` is a user id
    or 'unassigned'; an unknown id (or the system principal) is NotFound."""
    deals._gate(conn, user)
    owner_id = None if owner == "unassigned" else int(owner)
    window = _window(start, end)
    name = "Unassigned"
    if owner_id is not None:
        found = conn.execute("SELECT name FROM core_users WHERE id = ? AND role != 'system'", (owner_id,)).fetchone()
        if found is None:
            raise NotFound()
        name = found[0]
    rows = [r for r in _touch_rows(conn, user, window) if r["owner_user_id"] == owner_id]
    reps = _reps(rows, WEEKLY_TOUCHES_DETAIL_MAX)
    rep = reps[0] if reps else {"user_id": owner_id, "name": name, "open_deals": 0, "touches": 0, "deals": [], "truncated": False}
    truncated = rep.pop("truncated")
    return {"window": window, "rep": rep, "deals": rep["deals"], "truncated": truncated}


def weekly_touch_detail(user: User, owner: str, start: str | None = None, end: str | None = None) -> dict:
    return weekly_touch_detail_in(db.get_conn(), user, owner, start, end)
