"""The CRM dashboard's Today list and Weekly Touches on a real database. Behaviour ported from
CakeCRM's today and dashboard-touches suites (docs/PROVENANCE.md)."""

import pytest

from backend.apps.crm import dashboard, deals
from backend.core import db as core_db, settings
from backend.core.errors import Invalid
from backend.core.reminders import api as reminders
from backend.core.timeline import api as timeline


@pytest.fixture
def me(app, make_user, freeze):
    freeze("2026-10-01T15:00:00Z")
    with core_db.transaction() as conn:
        settings.set_setting_in(conn, "timezone", "America/Chicago", None)
    return make_user("member")


def hot(user, title, **fields):
    return deals.create(user, {"title": title, "deal_temperature": "hot", "owner_user_id": user.id, **fields})


# ── Today ─────────────────────────────────────────────────────────────────────


def test_today_ranks_quiet_hot_deals_then_reminders_then_the_rest(me, make_user, freeze):
    other = make_user("member")
    oldest, older, old = (hot(me, t) for t in ("Oldest", "Older", "Old"))
    hot(other, "Someone else's")
    deals.create(me, {"title": "Unowned and hot", "deal_temperature": "hot"})
    deals.create(me, {"title": "Warm", "deal_temperature": "warm", "owner_user_id": me.id})
    freeze("2026-10-10T15:00:00Z")
    timeline.add_note(me, "crm.deal", older["id"], "Still keen")  # older is fresher than old now
    freeze("2026-10-20T15:00:00Z")
    fresh = hot(me, "Fresh")
    with core_db.transaction() as conn:
        reminders.create_in(conn, me, title="Call the caterer", due_at="2026-10-20T16:30:00")
        reminders.create_in(conn, me, title="Tomorrow", due_at="2026-10-21T09:00:00")
    out = dashboard.today(me)
    assert (out["date"], out["next_refresh_at"]) == ("2026-10-20", "2026-10-21T05:00:00Z")
    shown = [(i["rank"], (i.get("deal") or i.get("reminder"))["title"]) for i in out["items"]]
    assert shown == [
        (1, "Oldest"), (1, "Old"), (2, "Call the caterer"),
        (None, "Unowned and hot"), (None, "Older"), (None, "Fresh"),
    ]
    assert out["items"][0]["reason"] == "Hot, quiet for 19 days"
    assert out["items"][-1]["reason"] == "Hot" and fresh["id"] == out["items"][-1]["deal"]["id"]


def test_today_leaves_out_closed_and_archived_deals(me, freeze):
    won, archived = hot(me, "Won"), hot(me, "Archived")
    deals.mark_won(me, won["id"])
    deals.archive(me, archived["id"], "Test")
    freeze("2026-11-01T15:00:00Z")
    assert dashboard.today(me)["items"] == []


# ── Weekly touches ────────────────────────────────────────────────────────────


def test_the_rolling_window_counts_touches_per_owner(me, make_user, freeze):
    other = make_user("member")
    mine = deals.create(me, {"title": "Mine", "owner_user_id": me.id})
    quiet = deals.create(me, {"title": "Quiet", "owner_user_id": me.id})
    theirs = deals.create(me, {"title": "Theirs", "owner_user_id": other.id})
    deals.create(me, {"title": "Nobody's"})
    freeze("2026-10-12T15:00:00Z")
    timeline.add_note(me, "crm.deal", mine["id"], "Talked pricing")
    deals.mark_won(other, theirs["id"])
    freeze("2026-10-14T15:00:00Z")
    out = dashboard.weekly_touches(me)
    assert (out["window"]["label"], out["window"]["custom"], out["window"]["end"]) == ("Last 7 days", False, "2026-10-14T15:00:00Z")
    reps = {r["name"]: (r["open_deals"], r["touches"], [d["title"] for d in r["deals"]]) for r in out["reps"]}
    assert reps == {other.name: (0, 1, ["Theirs"]), me.name: (2, 1, ["Mine"]), "Unassigned": (1, 0, [])}
    assert [r["name"] for r in out["reps"]][-1] == "Unassigned"
    assert (out["total_touches"], out["total_open_deals"]) == (2, 3)
    assert quiet["id"] not in [d["id"] for r in out["reps"] for d in r["deals"]]


def test_a_won_deal_is_dated_by_its_win(me, freeze):
    deal = deals.create(me, {"title": "Won early", "owner_user_id": me.id})
    deals.mark_won(me, deal["id"])
    freeze("2026-10-20T15:00:00Z")
    timeline.add_note(me, "crm.deal", deal["id"], "Thank-you card sent")  # after the win: not a touch
    assert dashboard.weekly_touches(me)["total_touches"] == 0
    assert dashboard.weekly_touches(me, "2026-10-01", "2026-10-01")["total_touches"] == 1


def test_custom_windows_are_whole_local_days(me, freeze):
    deal = deals.create(me, {"title": "Late night", "owner_user_id": me.id})
    freeze("2026-10-08T04:30:00Z")  # 23:30 on 7 October in Chicago
    timeline.add_note(me, "crm.deal", deal["id"], "Emailed the quote")
    freeze("2026-10-20T15:00:00Z")
    window = dashboard.weekly_touches(me, "2026-10-07", "2026-10-07")["window"]
    assert (window["start"], window["end"], window["custom"]) == ("2026-10-07T05:00:00Z", "2026-10-08T05:00:00Z", True)
    assert dashboard.weekly_touches(me, "2026-10-07", "2026-10-07")["total_touches"] == 1
    assert dashboard.weekly_touches(me, "2026-10-08", "2026-10-08")["total_touches"] == 0
    for start, end in (("2026-10-07", None), ("2026-10-08", "2026-10-07"), ("2026-10-7", "2026-10-08"), ("2026-02-30", "2026-03-01")):
        with pytest.raises(Invalid):
            dashboard.weekly_touches(me, start, end)


def test_the_detail_is_one_owner_uncapped(me, make_user, freeze):
    for i in range(12):
        timeline.add_note(me, "crm.deal", deals.create(me, {"title": f"Deal {i}", "owner_user_id": me.id})["id"], "Called")
    freeze("2026-10-01T16:00:00Z")  # the rolling window ends now, exclusive
    card = {r["user_id"]: r for r in dashboard.weekly_touches(me)["reps"]}[me.id]
    assert (card["touches"], len(card["deals"])) == (12, 10)
    detail = dashboard.weekly_touch_detail(me, str(me.id))
    assert (detail["rep"]["touches"], len(detail["deals"]), detail["truncated"]) == (12, 12, False)
    nobody = dashboard.weekly_touch_detail(me, str(make_user("member").id))
    assert (nobody["rep"]["touches"], nobody["deals"]) == (0, [])
    assert dashboard.weekly_touch_detail(me, "unassigned")["rep"]["name"] == "Unassigned"
