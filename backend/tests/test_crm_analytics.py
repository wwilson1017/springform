"""CRM analytics on a real database: install-local day buckets across both 2026 DST changes in
America/Chicago (compared with hand-computed days), win/loss in cents, aging, per-rep credit,
the funnel, deal health and duplicates. Behaviour ported from CakeCRM's analytics suites
(docs/PROVENANCE.md)."""

import pytest

from backend.apps.crm import activity, analytics, deals
from backend.core import db as core_db, settings
from backend.core.contacts import api as contacts
from backend.core.timeline import api as timeline


@pytest.fixture
def me(app, make_user, freeze):
    freeze("2026-11-02T18:00:00Z")  # noon on 2 November in Chicago
    with core_db.transaction() as conn:
        settings.set_setting_in(conn, "timezone", "America/Chicago", None)
    return make_user("member")


def at(freeze, instant):
    freeze(instant)


def add_activity(*instants, deal_id=None, actor=None, kind="call"):
    with core_db.transaction() as conn:
        conn.executemany(
            "INSERT INTO crm_activity_log (activity, deal_id, actor_user_id, created_at) VALUES (?, ?, ?, ?)",
            [(kind, deal_id, actor, i) for i in instants],
        )


def test_days_bucket_in_the_install_timezone_across_both_dst_changes(me):
    # Hand-computed Chicago days. CST is UTC-6, CDT is UTC-5; DST starts 2026-03-08 02:00 and
    # ends 2026-11-01 02:00 local. The window is the 365 local days ending 2 November 2026.
    expected = {
        "2025-11-02": 0,  # 2025-11-03T05:59:59Z is 23:59:59 on 2 Nov: before the window
        "2025-11-03": 1,  # 2025-11-03T06:00:00Z is the window's first instant
        "2026-03-07": 1,  # 05:30Z = 23:30 CST
        "2026-03-08": 3,  # 06:30Z = 00:30 CST, 08:30Z = 03:30 CDT, and 2026-03-09T04:30Z = 23:30 CDT
        "2026-03-09": 1,  # 05:30Z = 00:30 CDT
        "2026-10-31": 1,  # 2026-11-01T04:30Z = 23:30 CDT
        "2026-11-01": 4,  # 05:30Z 00:30 CDT, 06:30Z 01:30 CDT, 07:30Z 01:30 CST, 2026-11-02T05:30Z 23:30 CST
        "2026-11-02": 1,  # 06:30Z = 00:30 CST
    }
    add_activity(
        "2025-11-03T05:59:59Z", "2025-11-03T06:00:00Z",
        "2026-03-08T05:30:00Z", "2026-03-08T06:30:00Z", "2026-03-08T08:30:00Z", "2026-03-09T04:30:00Z", "2026-03-09T05:30:00Z",
        "2026-11-01T04:30:00Z", "2026-11-01T05:30:00Z", "2026-11-01T06:30:00Z", "2026-11-01T07:30:00Z",
        "2026-11-02T05:30:00Z", "2026-11-02T06:30:00Z",
    )  # fmt: skip
    out = analytics.analytics(me, days=365)
    daily = {d["day"]: d["count"] for d in out["activity"]["daily"]}
    assert out["timezone"] == "America/Chicago"
    assert len(out["activity"]["daily"]) == 365
    assert (out["activity"]["daily"][0]["day"], out["activity"]["daily"][-1]["day"]) == ("2025-11-03", "2026-11-02")
    assert {day: daily.get(day, 0) for day in expected} == expected
    assert out["activity"]["total"] == sum(expected.values()) == 12
    assert sum(daily.values()) == 12


def test_win_loss_in_cents(me, freeze):
    at(freeze, "2026-10-01T15:00:00Z")
    a, b, c = (deals.create(me, {"title": t, "value_cents": v}) for t, v in (("A", 100), ("B", 200), ("C", 201)))
    deals.create(me, {"title": "Open", "value_cents": 999, "stage": "proposal"})
    deals.create(me, {"title": "Free", "value_cents": 0})
    gone = deals.create(me, {"title": "Archived", "value_cents": 10**9, "stage": "won"})
    deals.archive(me, gone["id"], "Test record")
    at(freeze, "2026-10-03T15:00:00Z")
    for d in (a, b, c):
        deals.mark_won(me, d["id"])
    lost = deals.create(me, {"title": "Lost", "value_cents": 5})
    deals.mark_lost(me, lost["id"], "Budget")
    wl = analytics.analytics(me)["win_loss"]
    assert wl == {
        "deals_won": 3, "deals_lost": 1, "open_deals": 2, "win_rate_pct": 75.0,
        "avg_won_deal_cents": 167, "avg_open_deal_cents": 999, "avg_days_to_close": 2.0,
        "total_pipeline_value_cents": 999,
    }  # fmt: skip
    assert all(isinstance(wl[k], int) for k in ("avg_won_deal_cents", "avg_open_deal_cents", "total_pipeline_value_cents"))


def test_an_empty_crm_answers_with_zeros(me):
    out = analytics.analytics(me, days=7)
    assert out["win_loss"]["win_rate_pct"] is None and out["win_loss"]["avg_won_deal_cents"] is None
    assert [b["count"] for b in out["aging"]["buckets"]] == [0, 0, 0, 0]
    assert out["per_rep"] == [] and out["activity"]["total"] == 0


def test_aging_and_stale_deals(me, freeze):
    for created, title in (("2026-11-01T18:00:00Z", "Fresh"), ("2026-10-20T18:00:00Z", "Two weeks"), ("2026-07-01T18:00:00Z", "Old")):
        at(freeze, created)
        deals.create(me, {"title": title})
    at(freeze, "2026-11-02T18:00:00Z")
    aging = analytics.analytics(me, stale_days=10)["aging"]
    assert [b["count"] for b in aging["buckets"]] == [1, 1, 0, 1]
    assert [(d["title"], d["days_since_touch"], d["age_days"]) for d in aging["stale_deals"]] == [("Old", 124, 124), ("Two weeks", 13, 13)]
    old = aging["stale_deals"][0]["id"]
    timeline.add_note(me, "crm.deal", old, "Called them back")
    assert [d["title"] for d in analytics.stale_deals(me, days=10)["deals"]] == ["Two weeks"], "a note is a touch"


def test_per_rep_credit(me, make_user):
    other = make_user("member")
    mine = deals.create(me, {"title": "Mine", "owner_user_id": me.id, "value_cents": 500})
    deals.create(me, {"title": "Theirs, won", "owner_user_id": other.id, "value_cents": 700, "stage": "won"})
    activity.log(other, "call", deal_id=mine["id"])  # credit for work on a colleague's deal
    activity.log(other, "email", deal_id=mine["id"])
    timeline.add_note(me, "crm.deal", mine["id"], "Sent the samples")
    add_activity("2026-11-02T17:00:00Z", deal_id=mine["id"])  # nobody did this one
    reps = {r["name"]: r for r in analytics.analytics(me)["per_rep"]}
    assert (reps[me.name]["deals_open"], reps[me.name]["open_value_cents"], reps[me.name]["activity_count"]) == (1, 500, 1)
    assert (reps[other.name]["won_value_cents"], reps[other.name]["activity_count"], reps[other.name]["records_touched"]) == (700, 2, 1)
    assert list(reps)[-1] == "Unattributed" and reps["Unattributed"]["activity_count"] == 1


def test_the_funnel(me, freeze):
    at(freeze, "2026-10-01T15:00:00Z")
    a = deals.create(me, {"title": "A"})
    b = deals.create(me, {"title": "B"})
    for when, deal, change in (
        ("2026-10-03T15:00:00Z", a, {"stage": "qualified"}),
        ("2026-10-04T15:00:00Z", b, {"stage": "lost"}),
        ("2026-10-06T15:00:00Z", a, {"stage": "proposal"}),
        ("2026-10-07T15:00:00Z", a, {"stage": "won"}),
    ):  # fmt: skip
        at(freeze, when)
        deals.update(me, deal["id"], change)
    at(freeze, "2026-11-02T18:00:00Z")
    out = analytics.pipeline_analytics(me, days=90)
    stays = {s["stage"]: (s["samples"], s["avg_days"], s["median_days"]) for s in out["time_in_stage"]}
    assert stays == {"lead": (2, 2.5, 2.5), "qualified": (1, 3.0, 3.0), "proposal": (1, 1.0, 1.0), "negotiation": (0, None, None)}
    conv = {c["stage"]: c for c in out["conversion"]}
    assert (conv["lead"]["entered"], conv["lead"]["won"], conv["lead"]["lost"], conv["lead"]["progression_rate"]) == (2, 1, 1, 0.5)
    assert (conv["qualified"]["entered"], conv["qualified"]["win_rate"]) == (1, 1.0)
    # Won on 7 Oct, dated by its Closed on day: local midnight (05:00Z), 5 days 14 hours after creation.
    assert out["velocity"] == {"won_in_window": 1, "avg_days_to_won": 5.6}
    assert (out["history_since"], out["history_days"], out["history_covers_window"]) == ("2026-10-01T15:00:00Z", 32, False)


def test_deal_health_flags(me, freeze):
    with core_db.transaction() as conn:
        person = contacts.create_person_in(conn, me, name="Ada Example")["id"]
    deal = deals.create(me, {"title": "Wedding cakes", "person_id": person})
    health = analytics.deal_health(me, deal["id"])
    assert health["flags"] == ["no_next_step", "missing_organization"]
    assert 1 <= health["score"] <= 99 and set(health["factors"]) >= {"stage_baseline", "temperature"}
    at(freeze, "2026-12-15T18:00:00Z")
    assert analytics.deal_health(me, deal["id"])["flags"][:2] == ["stale", "stuck_in_stage"]
    deals.mark_won(me, deal["id"])
    assert analytics.deal_health(me, deal["id"])["flags"] == ["missing_organization"], "a closed deal is not stale or stuck"


def test_duplicates_are_title_and_person(me):
    with core_db.transaction() as conn:
        ada = contacts.create_person_in(conn, me, name="Ada Example")["id"]
        zoe = contacts.create_person_in(conn, me, name="Zoë Démo")["id"]
    first = deals.create(me, {"title": "Spring order", "person_id": ada})
    second = deals.create(me, {"title": "  spring ORDER ", "person_id": ada})
    deals.create(me, {"title": "Spring order", "person_id": zoe})
    archived = deals.create(me, {"title": "Spring order", "person_id": ada})
    deals.archive(me, archived["id"], "Test")
    assert analytics.duplicates(me) == [{
        "match_on": "title+person", "value": "spring order", "count": 2,
        "records": [{"id": first["id"], "label": "Spring order (lead)"}, {"id": second["id"], "label": "spring ORDER (lead)"}],
    }]  # fmt: skip
