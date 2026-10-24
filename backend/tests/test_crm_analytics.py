"""CRM analytics against a real SQLite file: install-local day buckets across both 2026 DST
changes in America/Chicago, money in exact integer cents, aging and staleness boundaries,
per-rep attribution, the stage-log funnel (including a log younger than its window), deal
health flags and duplicate deals. Behaviour ported from CakeCRM's analytics, deal-health and
analytics-service suites (docs/PROVENANCE.md); every expected number is computed by hand."""

from datetime import datetime, timedelta

import pytest

from backend.apps.crm import activity, analytics, deals
from backend.core import clock, db as core_db, settings
from backend.core.contacts import api as contacts
from backend.core.errors import NotFound
from backend.core.reminders import api as reminders
from backend.core.timeline import api as timeline

T0 = "2026-06-01T12:00:00Z"


def iso(base: str, days: float = 0, hours: float = 0) -> str:
    return clock.to_iso(clock.parse(base) + timedelta(days=days, hours=hours))


@pytest.fixture
def chicago(app):
    settings.set_setting("timezone", "America/Chicago", None)


@pytest.fixture
def admin(app, make_user):
    return make_user("admin")


@pytest.fixture
def member(app, make_user):
    return make_user("member")


def deal(user, title="Deal", **fields):
    return deals.create(user, {"title": title, **fields})


def person(user, name: str) -> int:
    with core_db.transaction() as conn:
        return contacts.create_person_in(conn, user, name=name)["id"]


def organization(user, name: str) -> int:
    with core_db.transaction() as conn:
        return contacts.create_organization_in(conn, user, name=name)["id"]


# ── Day buckets across DST ────────────────────────────────────────────────────

# (instant, install-local day in America/Chicago). Spring forward is 2026-03-08 (a 23-hour
# day), fall back is 2026-11-01 (a 25-hour day). The comments name the local wall time.
DST_ACTIVITY = [
    ("2026-03-08T05:30:00Z", "2026-03-07"),  # 23:30 CST
    ("2026-03-08T06:30:00Z", "2026-03-08"),  # 00:30 CST
    ("2026-03-09T04:59:59Z", "2026-03-08"),  # 23:59:59 CDT, the short day's last second; its UTC date is the 9th
    ("2026-03-09T05:00:00Z", "2026-03-09"),  # 00:00 CDT
    ("2026-10-27T04:59:59Z", "2026-10-26"),  # 23:59:59 CDT, one second before the 7-day window
    ("2026-10-27T05:00:00Z", "2026-10-27"),  # 00:00 CDT, the 7-day window's first second
    ("2026-11-01T04:59:59Z", "2026-10-31"),  # 23:59:59 CDT
    ("2026-11-01T05:00:00Z", "2026-11-01"),  # 00:00 CDT
    ("2026-11-02T05:59:59Z", "2026-11-01"),  # 23:59:59 CST, the long day's last second
    ("2026-11-02T06:00:00Z", "2026-11-02"),  # 00:00 CST
]


@pytest.fixture
def dst_activity(chicago, admin, freeze):
    kinds = ("Call", "call", "Email")
    for i, (instant, _day) in enumerate(DST_ACTIVITY):
        freeze(instant)
        activity.log(admin, kinds[i % 3])
    freeze("2026-11-02T18:00:00Z")  # Monday 12:00 CST


def test_daily_buckets_are_install_local_days_across_both_dst_changes(dst_activity, admin):
    out = analytics.analytics(admin, days=365)
    assert out["timezone"] == "America/Chicago" and out["window_days"] == 365
    daily = out["activity"]["daily"]
    assert len(daily) == 365 and daily[0]["day"] == "2025-11-03" and daily[-1]["day"] == "2026-11-02"
    nonzero = {d["day"]: d["count"] for d in daily if d["count"]}
    assert nonzero == {
        "2026-03-07": 1, "2026-03-08": 2, "2026-03-09": 1, "2026-10-26": 1, "2026-10-27": 1,
        "2026-10-31": 1, "2026-11-01": 2, "2026-11-02": 1,
    }  # fmt: skip
    assert out["activity"]["total"] == 10
    # "Call" and "call" are one kind; 7 calls and 3 emails, busiest first.
    assert out["activity"]["by_type"] == [{"activity": "call", "count": 7}, {"activity": "email", "count": 3}]


def test_the_window_starts_at_local_midnight_and_every_count_shares_it(dst_activity, admin):
    out = analytics.analytics(admin, days=7)
    days = [d["day"] for d in out["activity"]["daily"]]
    assert days == ["2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30", "2026-10-31", "2026-11-01", "2026-11-02"]
    assert [d["count"] for d in out["activity"]["daily"]] == [1, 0, 0, 0, 1, 2, 1]
    assert out["activity"]["total"] == 5 == sum(t["count"] for t in out["activity"]["by_type"])
    assert out["per_rep"][0]["activity_count"] == 5


def test_days_are_clamped_and_an_empty_crm_is_a_zero_state(app, admin):
    out = analytics.analytics(admin, days=3)
    assert out["window_days"] == 7 and out["timezone"] == "UTC" and out["stale_days"] == 14
    assert out["win_loss"] == {
        "deals_won": 0, "deals_lost": 0, "open_deals": 0, "win_rate_pct": None, "avg_won_deal_cents": None,
        "avg_open_deal_cents": None, "avg_days_to_close": None, "total_pipeline_value_cents": 0,
    }  # fmt: skip
    assert [b["count"] for b in out["aging"]["buckets"]] == [0, 0, 0, 0]
    assert out["activity"]["total"] == 0 and out["per_rep"] == [] and analytics.analytics(admin, days=999)["window_days"] == 365


# ── Win/loss and money ────────────────────────────────────────────────────────


def test_win_loss_in_exact_cents_and_local_days_to_close(chicago, admin, freeze):
    freeze("2026-03-07T12:00:00Z")  # Mar 7 06:00 CST
    w1 = deal(admin, "One cent", value_cents=1)
    freeze("2026-03-10T04:30:00Z")  # Mar 9 23:30 CDT: a UTC date would say the 10th
    w2 = deal(admin, "Two cents", value_cents=2)
    big = [deal(admin, f"Big {i}", value_cents=v)["id"] for i, v in enumerate((999_999_999_999_999, 999_999_999_999_998))]
    deal(admin, "Zero", value_cents=0)
    deal(admin, "Credit", value_cents=-5)
    lost = deal(admin, "Lost", value_cents=7)
    gone = deal(admin, "Archived", value_cents=100)
    freeze("2026-03-10T12:00:00Z")  # Mar 10 07:00 CDT
    deals.mark_won(admin, w1["id"], "2026-03-09")  # 2 local days after Mar 7
    deals.mark_won(admin, w2["id"])  # today, Mar 10: 1 local day after Mar 9
    deals.mark_lost(admin, lost["id"], "No budget")
    deals.archive(admin, gone["id"], "Duplicate")

    wl = analytics.analytics(admin)["win_loss"]
    assert wl == {
        "deals_won": 2, "deals_lost": 1, "open_deals": 4,
        "win_rate_pct": 66.7,
        "avg_won_deal_cents": 2,  # (1 + 2) / 2 = 1.5 rounds half up
        "avg_open_deal_cents": 999_999_999_999_999,  # .5 rounds up; a float mean would say 10**15
        "avg_days_to_close": 1.5,
        "total_pipeline_value_cents": 1_999_999_999_999_992,  # includes the zero and the -5 credit
    }  # fmt: skip
    assert all(type(wl[k]) is int for k in ("avg_won_deal_cents", "avg_open_deal_cents", "total_pipeline_value_cents"))
    assert analytics.avg_cents([3, 4, 4]) == 4 and analytics.avg_cents([]) is None and big


# ── Aging and staleness ───────────────────────────────────────────────────────


def test_age_buckets_and_the_strict_stale_boundary(app, admin, freeze):
    now = T0
    for age in (0, 7, 8, 30, 31, 90, 91):
        freeze(iso(now, days=-age))
        deal(admin, f"Aged {age}")
    freeze(iso(now, days=-200))
    closed = deal(admin, "Old win", stage="won")
    freeze(now)
    out = analytics.analytics(admin, days=30, stale_days=30)
    assert [(b["label"], b["count"]) for b in out["aging"]["buckets"]] == [("0-7", 2), ("8-30", 2), ("31-90", 2), ("91+", 1)]
    # Untouched exactly 30 days is not yet stale; strictly older is.
    assert out["aging"]["stale_count"] == 3
    assert [(d["title"], d["days_since_touch"], d["age_days"]) for d in out["aging"]["stale_deals"]] == [
        ("Aged 91", 91, 91), ("Aged 90", 90, 90), ("Aged 31", 31, 31),
    ]  # fmt: skip
    assert closed["id"] not in {d["id"] for d in out["aging"]["stale_deals"]}
    # A touch resets the clock: the activity is the deal's last touch now.
    activity.log(admin, "call", deal_id=out["aging"]["stale_deals"][0]["id"])
    assert analytics.stale_deals(admin, 30)["total_stale"] == 2


def test_stale_list_is_capped_but_the_count_is_not(app, admin, freeze):
    freeze(iso(T0, days=-60))
    for i in range(10):
        deal(admin, f"Quiet {i}")
    freeze(T0)
    out = analytics.analytics(admin, stale_days=14)["aging"]
    assert out["stale_count"] == 10 and len(out["stale_deals"]) == analytics.STALE_LIMIT


# ── Per rep ───────────────────────────────────────────────────────────────────


def test_per_rep_mixes_ownership_and_authorship(app, admin, member, freeze):
    freeze(iso(T0, days=-60))
    a = deal(admin, "A", value_cents=100, owner_user_id=admin.id)
    activity.log(admin, "call", deal_id=a["id"])  # outside the 30-day window
    freeze(iso(T0, days=-1))
    b = deal(admin, "B", value_cents=200, owner_user_id=admin.id)
    deal(admin, "C", value_cents=500, owner_user_id=admin.id, stage="won")
    d = deal(member, "D", value_cents=900, owner_user_id=member.id)
    deals.mark_lost(member, d["id"])
    deal(member, "E", value_cents=50)
    org = organization(member, "Example Mill")
    for _ in range(3):
        activity.log(admin, "call", deal_id=a["id"])
    timeline.add_note(admin, "crm.deal", a["id"], "Sent the price sheet")
    activity.log(member, "email", deal_id=b["id"])  # credit for work on a colleague's deal
    activity.log(member, "call")  # linked to nothing: activity, but no record touched
    timeline.add_note(member, "core.organization", org, "Met the buyer")
    freeze(T0)

    reps = {r["name"]: r for r in analytics.analytics(admin)["per_rep"]}
    assert [r["name"] for r in analytics.analytics(admin)["per_rep"]] == [member.name, admin.name, "Unattributed"]
    assert reps[admin.name] == {
        "user_id": admin.id, "name": admin.name, "deals_open": 2, "open_value_cents": 300, "deals_won": 1, "deals_lost": 0,
        "won_value_cents": 500, "activity_count": 4, "records_touched": 1,
    }  # fmt: skip
    assert (reps[member.name]["deals_lost"], reps[member.name]["activity_count"], reps[member.name]["records_touched"]) == (1, 3, 2)
    assert (reps["Unattributed"]["user_id"], reps["Unattributed"]["deals_open"], reps["Unattributed"]["open_value_cents"]) == (None, 1, 50)


# ── Pipeline analytics ────────────────────────────────────────────────────────


@pytest.fixture
def funnel(app, admin, freeze):
    """Five live deals moved through the pipeline over six days from T0, one archived."""
    freeze(T0)
    a, b, d, f = (deal(admin, t)["id"] for t in ("A", "B", "D", "F"))
    c = deal(admin, "C", stage="qualified")["id"]
    steps = [
        (1, f, "qualified"), (2, a, "qualified"), (3, c, "lead"), (4, b, "qualified"), (4, c, "qualified"),
        (5, a, "proposal"),
    ]  # fmt: skip
    for day, deal_id, stage in steps:
        freeze(iso(T0, days=day))
        deals.update(admin, deal_id, {"stage": stage})
    deals.mark_lost(admin, d)
    freeze(iso(T0, days=6))
    deals.mark_won(admin, b)  # closed_on 2026-06-07
    deals.archive(admin, f, "Test data")
    freeze(iso(T0, days=10))
    return {"a": a, "b": b, "c": c, "d": d}


def test_pipeline_funnel_is_hand_computed(funnel, admin):
    out = analytics.pipeline_analytics(admin, days=90)
    assert (out["history_since"], out["history_days"], out["history_covers_window"]) == (T0, 10, False)
    # Completed stays: lead A2 B4 C1 D5, qualified A3 B2 C3; current stays are open and left out.
    assert out["time_in_stage"] == [
        {"stage": "lead", "deals": 4, "median_days": 3.0, "avg_days": 3.0},
        {"stage": "qualified", "deals": 3, "median_days": 3.0, "avg_days": 2.7},
        {"stage": "proposal", "deals": 0, "median_days": None, "avg_days": None},
        {"stage": "negotiation", "deals": 0, "median_days": None, "avg_days": None},
    ]
    # First entry per deal and stage; advanced = now later in the pipeline, or won. C went back
    # to lead and up again: one qualified entry, not advanced; its lead entry advanced.
    assert out["conversion"] == [
        {"stage": "lead", "entered": 4, "advanced": 3, "rate_pct": 75.0},
        {"stage": "qualified", "entered": 3, "advanced": 2, "rate_pct": 66.7},
        {"stage": "proposal", "entered": 1, "advanced": 0, "rate_pct": 0.0},
        {"stage": "negotiation", "entered": 0, "advanced": 0, "rate_pct": None},
    ]
    assert out["velocity"] == {"won_in_window": 1, "avg_days_to_won": 6.0}


def test_a_short_window_counts_only_what_began_inside_it(funnel, admin):
    out = analytics.pipeline_analytics(admin, days=7)  # 2026-06-05 .. 2026-06-11
    assert out["window_days"] == 7 and out["history_covers_window"] is True
    assert out["time_in_stage"][1] == {"stage": "qualified", "deals": 1, "median_days": 2.0, "avg_days": 2.0}
    assert [(c["stage"], c["entered"], c["advanced"]) for c in out["conversion"]] == [
        ("lead", 0, 0), ("qualified", 2, 1), ("proposal", 1, 0), ("negotiation", 0, 0),
    ]  # fmt: skip
    assert out["velocity"]["won_in_window"] == 1


def test_an_empty_stage_log(app, admin):
    out = analytics.pipeline_analytics(admin, days=3)
    assert out["window_days"] == 7
    assert (out["history_since"], out["history_days"], out["history_covers_window"]) == (None, None, False)
    assert out["velocity"] == {"won_in_window": 0, "avg_days_to_won": None}


# ── Deal health ───────────────────────────────────────────────────────────────


def remind(user, deal_id, due_at):
    return reminders.create(user, title="Follow up", due_at=due_at, entity_type="crm.deal", entity_id=deal_id)


def test_a_healthy_deal_raises_no_flags(app, admin, freeze):
    freeze(T0)
    healthy = deal(admin, "Healthy", person_id=person(admin, "Ada Example"), organization_id=organization(admin, "Example Co"))
    remind(admin, healthy["id"], iso(T0, days=1))
    out = analytics.deal_health(admin, healthy["id"])
    assert (out["flags"], out["score"], out["factors"], out["stale_days"]) == ([], None, {}, 14)
    assert out["deal"]["id"] == healthy["id"]


def test_every_flag_fires_on_a_neglected_deal(app, admin, freeze):
    freeze(iso(T0, days=-40))
    neglected = deal(admin, "Neglected")["id"]
    freeze(T0)
    assert analytics.deal_health(admin, neglected)["flags"] == [
        "stale", "stuck_in_stage", "no_next_step", "missing_person", "missing_organization",
    ]  # fmt: skip
    overdue = remind(admin, neglected, iso(T0, days=-1))
    assert analytics.deal_health(admin, neglected)["flags"] == [
        "stale", "stuck_in_stage", "overdue_reminder", "missing_person", "missing_organization",
    ]  # fmt: skip
    reminders.complete(admin, overdue["id"])
    remind(admin, neglected, iso(T0, hours=-4))  # earlier today: due, not overdue
    assert analytics.deal_health(admin, neglected)["flags"] == ["stale", "stuck_in_stage", "missing_person", "missing_organization"]


def test_closed_and_archived_deals_only_report_missing_links(app, admin, freeze):
    freeze(iso(T0, days=-40))
    won, put_away = deal(admin, "Won", stage="won")["id"], deal(admin, "Put away")["id"]
    deals.archive(admin, put_away, "Test data")
    freeze(T0)
    assert analytics.deal_health(admin, won)["flags"] == ["missing_person", "missing_organization"]
    archived = analytics.deal_health(admin, put_away)
    assert archived["deal"]["archived_at"] is not None and archived["flags"] == ["missing_person", "missing_organization"]
    with pytest.raises(NotFound):
        analytics.deal_health(admin, 9999)


def test_health_flags_is_pure():
    base = {"operational": True, "stale": False, "days_in_stage": 29, "next_steps": 1, "overdue": 0, "person_id": 1, "organization_id": 1}
    assert analytics.health_flags(**base) == []
    assert analytics.health_flags(**{**base, "days_in_stage": 30}) == ["stuck_in_stage"]


# ── Duplicates ────────────────────────────────────────────────────────────────


def test_duplicate_deals_share_a_folded_title_and_a_person(app, admin):
    p1, p2 = person(admin, "Ada Example"), person(admin, "Zoe Example")
    spring = [deal(admin, "Spring order", person_id=p1)["id"], deal(admin, "  spring ORDER ", person_id=p1)["id"]]
    deal(admin, "Spring order", person_id=p2)  # another customer's order is not a duplicate
    cafe = [deal(admin, t, person_id=p2)["id"] for t in ("Café pastry", "CAFÉ PASTRY", "café pastry")]
    gone = deal(admin, "Spring order", person_id=p1)["id"]
    deals.archive(admin, gone, "Entered twice")
    deal(admin, "Spring order")
    deal(admin, "Spring order")  # no person: title alone is not a duplicate

    groups = analytics.duplicates(admin)
    assert [(g["match_on"], g["value"], g["count"]) for g in groups] == [("title+person", "café pastry", 3), ("title+person", "spring order", 2)]
    assert [r["id"] for r in groups[0]["records"]] == cafe and [r["id"] for r in groups[1]["records"]] == spring
    assert groups[1]["records"][1]["label"] == "spring ORDER (lead)"


# ── Routes ────────────────────────────────────────────────────────────────────


def test_routes_answer_with_their_models(login_as):
    member = login_as("member")
    deal_id = member.post("/api/crm/deals", json={"title": "Route deal", "value_cents": 1234}).json()["id"]
    body = member.get("/api/crm/analytics?days=30").json()
    assert body["win_loss"]["total_pipeline_value_cents"] == 1234 and len(body["activity"]["daily"]) == 30
    assert member.get("/api/crm/analytics?days=3").status_code == 422
    pipeline = member.get("/api/crm/analytics/pipeline").json()
    assert pipeline["window_days"] == 90 and pipeline["conversion"][0] == {"stage": "lead", "entered": 1, "advanced": 0, "rate_pct": 0.0}
    health = member.get(f"/api/crm/deals/{deal_id}/health").json()
    assert health["flags"][-2:] == ["missing_person", "missing_organization"]
    assert member.get("/api/crm/deals/duplicates").json() == []
    assert member.get("/api/crm/deals/424242/health").status_code == 404


def test_days_to_close_counts_local_calendar_days(chicago):
    zone = settings.get_setting("timezone")
    from zoneinfo import ZoneInfo

    assert analytics.days_to_close("2026-03-09T04:59:59Z", "2026-03-09", ZoneInfo(zone)) == 1
    assert analytics.days_to_close("2026-03-09T05:00:00Z", "2026-03-09", ZoneInfo(zone)) == 0
    assert analytics.days_to_close("2026-03-09T05:00:00Z", "2026-03-01", ZoneInfo(zone)) == 0  # backdated: never negative
    assert analytics.whole_days("2026-03-09T05:00:00Z", datetime(2026, 3, 8, tzinfo=clock.parse(T0).tzinfo)) == 0
