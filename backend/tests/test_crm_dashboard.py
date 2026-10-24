"""The CRM dashboard's Today list and Weekly Touches on a real database. Behaviour ported from
CakeCRM's today and dashboard-touches suites (docs/PROVENANCE.md)."""

import pytest

from backend.apps.crm import dashboard, deals
from backend.core import db as core_db, settings
from backend.core.contacts import api as contacts
from backend.core.errors import Invalid, NotFound
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


# ── Fixes on top of the port ──────────────────────────────────────────────────


def test_creating_a_deal_is_not_a_touch(me, freeze):
    """A fresh import or sample load must not read as a week of work. A note in the same second
    as creation is still a touch: timestamps are whole seconds, so the rule is about events."""
    imported = deals.create(me, {"title": "Imported", "owner_user_id": me.id})
    deals.create(me, {"title": "Born won", "owner_user_id": me.id, "stage": "won"})
    noted = deals.create(me, {"title": "Noted at once", "owner_user_id": me.id})
    timeline.add_note(me, "crm.deal", noted["id"], "Called while creating it")
    freeze("2026-10-02T15:00:00Z")
    out = dashboard.weekly_touches(me)
    assert (out["total_touches"], out["total_open_deals"]) == (1, 2)
    assert [d["title"] for d in out["reps"][0]["deals"]] == ["Noted at once"]
    deals.update(me, imported["id"], {"value_cents": 500})  # an edit after creation is a touch
    freeze("2026-10-02T16:00:00Z")  # the rolling window ends now, exclusive
    assert dashboard.weekly_touches(me)["total_touches"] == 2


def test_the_detail_for_an_unknown_user_is_not_found(me):
    for owner in ("424242", "0"):  # 0 is the system principal, never a rep
        with pytest.raises(NotFound):
            dashboard.weekly_touch_detail(me, owner)


def test_a_window_past_the_last_representable_day_is_refused(me):
    with pytest.raises(Invalid):
        dashboard.weekly_touches(me, "9999-12-30", "9999-12-31")


def test_a_done_reminder_is_not_due_today(me, freeze):
    freeze("2026-10-20T15:00:00Z")
    with core_db.transaction() as conn:
        done = reminders.create_in(conn, me, title="Already called", due_at="2026-10-20T16:30:00")
        reminders.create_in(conn, me, title="Still to do", due_at="2026-10-20T17:00:00")
    reminders.complete(me, done["id"])
    assert [i["reminder"]["title"] for i in dashboard.today(me)["items"]] == ["Still to do"]


def test_a_deal_the_caller_cannot_read_stays_out_of_every_list(me, freeze, monkeypatch):
    """Any member reads any deal today; the lists still go through can_read, so a restrictive
    rule would hold."""
    from dataclasses import replace

    from backend.apps.crm import analytics
    from backend.core import entities

    with core_db.transaction() as conn:
        person = contacts.create_person_in(conn, me, name="Ada Example")["id"]
    seen = hot(me, "Seen", stage="proposal", value_cents=100, person_id=person)
    hidden = hot(me, "Hidden", stage="proposal", value_cents=10**6, person_id=person)
    hot(me, "seen", person_id=person)
    hot(me, "hidden", person_id=person)
    for deal_id in (seen["id"], hidden["id"]):
        timeline.add_note(me, "crm.deal", deal_id, "Called")
    entity = entities.get("crm.deal")
    monkeypatch.setitem(entities._ENTITIES, "crm.deal", replace(entity, can_read=lambda user, conn, i: i != hidden["id"]))
    freeze("2026-10-30T15:00:00Z")
    titles = {
        "today": [i["deal"]["title"] for i in dashboard.today(me)["items"]],
        "top": [d["title"] for d in dashboard.dashboard(me)["top_deals"]],
        "touches": [d["title"] for d in dashboard.weekly_touches(me, "2026-10-01", "2026-10-01")["reps"][0]["deals"]],
        "stale": [d["title"] for d in analytics.stale_deals(me, days=14)["deals"]],
        "duplicates": [r["label"] for g in analytics.duplicates(me) for r in g["records"]],
    }
    assert not any("Hidden" in t for ts in titles.values() for t in ts), titles
    assert titles["duplicates"] == ["Seen (proposal)", "seen (lead)"], "one readable deal is not a duplicate group"


def test_the_touch_routes_answer_404_and_422_not_500(login_as):
    admin = login_as("admin")
    assert admin.get("/api/crm/dashboard/weekly-touches/detail?owner=424242").status_code == 404
    assert admin.get("/api/crm/dashboard/weekly-touches/detail?owner=0").status_code == 404
    assert admin.get("/api/crm/dashboard/weekly-touches?start=9999-12-30&end=9999-12-31").status_code == 422
