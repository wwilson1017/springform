"""The CRM home against a real SQLite file: the Today ladder (hot deals gone quiet, the caller's
reminders due today, the unranked tail) and Weekly Touches (who touched what in a window of
install-local days, per owner, with the drill-down). Behaviour ported from CakeCRM's today,
dashboard-touches and weekly-touches integration suites (docs/PROVENANCE.md)."""

from datetime import timedelta

import pytest

from backend.apps.crm import activity, dashboard, deals
from backend.core import clock, db as core_db, settings
from backend.core.errors import Invalid, NotFound
from backend.core.reminders import api as reminders
from backend.core.timeline import api as timeline


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


def deal(user, title="Deal", **fields) -> int:
    return deals.create(user, {"title": title, **fields})["id"]


# ── Today ─────────────────────────────────────────────────────────────────────

NOW = "2026-03-07T20:00:00Z"  # Saturday 14:00 CST


def test_today_ranks_quiet_hot_deals_then_my_reminders_then_the_tail(chicago, admin, member, freeze):
    ids = {}
    for title, age, extra in [
        ("Idle 30", 30, {}), ("Idle 20", 20, {}), ("Idle 16", 16, {}), ("Exactly 14", 14, {}), ("Fresh", 1, {}),
        ("Warm", 30, {"deal_temperature": "warm"}), ("Won", 30, {"stage": "won"}), ("Archived", 30, {}),
    ]:  # fmt: skip
        freeze(iso(NOW, days=-age))
        ids[title] = deal(admin, title, **{"deal_temperature": "hot", **extra})
    freeze(NOW)
    deals.archive(admin, ids["Archived"], "Test data")
    late = reminders.create(admin, title="Late", due_at="2026-03-08T05:30:00Z")  # 23:30 CST tonight; a UTC date says tomorrow
    later = reminders.create(admin, title="Afternoon", due_at="2026-03-07T22:00:00Z")
    early = reminders.create(admin, title="Morning", due_at="2026-03-07T15:00:00Z", entity_type="crm.deal", entity_id=ids["Fresh"])
    reminders.create(admin, title="Tomorrow", due_at="2026-03-08T07:00:00Z")
    finished = reminders.create(admin, title="Done", due_at="2026-03-07T16:00:00Z")
    reminders.complete(admin, finished["id"])
    reminders.create(member, title="Someone else's", due_at="2026-03-07T21:00:00Z")

    out = dashboard.today(admin)
    assert (out["date"], out["next_refresh_at"]) == ("2026-03-07", "2026-03-08T06:00:00Z")
    got = [(i["kind"], i["rank"], i["reason"], (i.get("deal") or i.get("reminder"))["title"]) for i in out["items"]]
    assert got == [
        ("deal", 1, "hot_stale", "Idle 30"),
        ("deal", 1, "hot_stale", "Idle 20"),  # only HOT_DEAL_SLOTS deals may sit above my reminders
        ("reminder", 2, "reminder", "Morning"),
        ("reminder", 2, "reminder", "Afternoon"),
        ("reminder", 2, "reminder", "Late"),
        ("deal", None, "hot_stale", "Idle 16"),  # demoted past the cap, still saying it is going cold
        ("deal", None, "hot", "Exactly 14"),  # untouched exactly stale_days: not yet stale
        ("deal", None, "hot", "Fresh"),
    ]
    assert out["items"][0]["deal"]["person_name"] is None and "last_touch" not in out["items"][0]["deal"]
    assert [i["reminder"]["id"] for i in out["items"][2:5]] == [early["id"], later["id"], late["id"]]


def test_today_rolls_over_at_local_midnight_on_the_short_day(chicago, admin, freeze):
    freeze("2026-03-08T12:00:00Z")  # Sunday 07:00 CDT, the day that is 23 hours long
    out = dashboard.today(admin)
    assert (out["date"], out["next_refresh_at"], out["items"]) == ("2026-03-08", "2026-03-09T05:00:00Z", [])


def test_a_touch_moves_a_hot_deal_off_the_ladder(app, admin, freeze):
    freeze(iso(NOW, days=-30))
    quiet = deal(admin, "Quiet", deal_temperature="hot")
    freeze(NOW)
    assert dashboard.today(admin)["items"][0]["rank"] == 1
    timeline.add_note(admin, "crm.deal", quiet, "Called, they are still keen")
    assert [(i["rank"], i["reason"]) for i in dashboard.today(admin)["items"]] == [(None, "hot")]


# ── Weekly Touches ────────────────────────────────────────────────────────────

N = "2026-06-10T12:00:00Z"  # Wednesday; the default window is 2026-06-04 .. 2026-06-10 (UTC install)


@pytest.fixture
def week(app, admin, member, make_user, freeze):
    """Deals created three weeks back, then worked (or not) during the last 7 days."""
    other = make_user("member")
    freeze(iso(N, days=-30))
    d = {t: deal(owner, t, owner_user_id=owner.id) for t, owner in [
        ("a", admin), ("b", admin), ("c", member), ("d", member), ("e", admin), ("g", admin), ("h", member), ("i", other), ("k", member),
    ]}  # fmt: skip
    d["f"] = deal(admin, "f")  # unowned
    deals.mark_won(member, d["h"])  # won a month ago: outside the window
    deals.mark_won(other, d["i"])  # the other rep's only deal: no row this week
    freeze(iso(N, days=-25))
    deals.mark_won(member, d["k"])
    freeze(iso(N, days=-24))
    deals.update(member, d["k"], {"stage": "negotiation"})  # reopened
    freeze(iso(N, days=-3))
    activity.log(admin, "call", deal_id=d["g"])
    freeze(iso(N, days=-2))
    timeline.add_note(member, "crm.deal", d["c"], "Sent samples")  # a live note is a touch
    deals.mark_won(admin, d["g"])  # the win dates g
    deals.mark_won(member, d["k"])  # re-won: counts once, at its latest win
    freeze(iso(N, days=-1))
    for key in ("a", "e", "f"):
        activity.log(admin, "call", deal_id=d[key])
    deals.mark_lost(member, d["d"])  # moved in the window, but lost counts for nothing
    deals.archive(admin, d["e"], "Test data")  # so does archived
    timeline.add_note(admin, "crm.deal", d["g"], "Thank-you card sent")  # after the win: moves nothing
    d["j"] = deal(admin, "j", owner_user_id=admin.id)  # created in the window: creation is not a touch
    d["l"] = deal(admin, "l", owner_user_id=admin.id, stage="won")  # born won: its win is its creation
    freeze(N)
    return d


def test_weekly_touches_counts_per_rep(week, admin, member):
    out = dashboard.weekly_touches(admin)
    assert out["window"] == {"start": "2026-06-04", "end": "2026-06-10", "label": "Last 7 days", "custom": False}
    reps = [(r["name"], r["open_deals"], r["touches"], [x["title"] for x in r["deals"]]) for r in out["reps"]]
    assert reps == [
        (admin.name, 3, 2, ["g", "a"]),  # open a, b, j; touched a and g (won here); ties on touches go to the bigger book
        (member.name, 1, 2, ["k", "c"]),  # open c; touched c and k (re-won); touches exceed open deals
        ("Unassigned", 1, 1, ["f"]),  # unowned is a bucket, and it sinks last
    ]
    assert (out["total_touches"], out["total_open_deals"]) == (5, 5)
    g = out["reps"][0]["deals"][0]
    assert g["touched_at"] == iso(N, days=-2) and g["stage"] == "won" and g["owner_user_id"] == admin.id


def test_a_rep_with_open_deals_and_no_touches_still_gets_a_row(app, admin, member, freeze):
    freeze(iso(N, days=-30))
    deal(member, "Untouched", owner_user_id=member.id)
    freeze(N)
    assert [(r["name"], r["open_deals"], r["touches"]) for r in dashboard.weekly_touches(admin)["reps"]] == [(member.name, 1, 0)]


def test_a_custom_window_is_whole_local_days_across_spring_forward(chicago, admin, freeze):
    freeze("2026-03-01T12:00:00Z")
    x, y, z, w = (deal(admin, t, owner_user_id=admin.id) for t in "xyzw")
    for deal_id, instant in [
        (x, "2026-03-08T06:00:00Z"),  # 00:00 CST, the day's first second
        (y, "2026-03-08T05:59:59Z"),  # 23:59:59 CST the day before
        (z, "2026-03-09T04:59:59Z"),  # 23:59:59 CDT, the 23-hour day's last second
        (w, "2026-03-09T05:00:00Z"),  # 00:00 CDT the day after
    ]:
        freeze(instant)
        activity.log(admin, "call", deal_id=deal_id)
    freeze("2026-03-10T12:00:00Z")
    out = dashboard.weekly_touches(admin, "2026-03-08", "2026-03-08")
    assert out["window"] == {"start": "2026-03-08", "end": "2026-03-08", "label": "2026-03-08 – 2026-03-08", "custom": True}
    assert sorted(d["id"] for d in out["reps"][0]["deals"]) == [x, z]
    assert dashboard.weekly_touches(admin, "  ", "")["window"]["custom"] is False  # blank is a cleared filter


@pytest.mark.parametrize("start, end", [
    ("2026-03-08", None), (None, "2026-03-08"), ("2026-03-09", "2026-03-08"), ("2026-02-30", "2026-03-01"),
    ("2026-6-1", "2026-06-02"), ("9999-12-30", "9999-12-31"),
])  # fmt: skip
def test_a_bad_window_is_refused(app, admin, start, end):
    with pytest.raises(Invalid):
        dashboard.weekly_touches(admin, start, end)


def test_the_card_caps_each_rep_and_the_detail_lists_them_all(app, admin, freeze, monkeypatch):
    freeze(iso(N, days=-30))
    ids = [deal(admin, f"Deal {i:02}", owner_user_id=admin.id) for i in range(12)]
    with core_db.transaction() as conn:
        for deal_id, count in zip(ids[:3], (2, 9, 0)):
            conn.execute("UPDATE crm_deals SET ai_touch_count = ? WHERE id = ?", (count, deal_id))
    freeze(iso(N, days=-1))
    for deal_id in ids:
        activity.log(admin, "call", deal_id=deal_id)
    freeze(N)
    rep = dashboard.weekly_touches(admin)["reps"][0]
    # Most touches first, counted before uncounted, then newest; the cap is per rep.
    expected = [ids[1], ids[0], ids[2], *reversed(ids[3:])]
    assert rep["touches"] == 12 and [d["id"] for d in rep["deals"]] == expected[: dashboard.WEEKLY_TOUCHES_LIMIT]
    detail = dashboard.weekly_touch_detail(admin, str(admin.id))
    assert [d["id"] for d in detail["deals"]] == expected and detail["truncated"] is False
    assert (detail["rep"]["name"], detail["rep"]["touches"], detail["rep"]["deals"]) == (admin.name, 12, [])
    monkeypatch.setattr(dashboard, "WEEKLY_TOUCHES_DETAIL_MAX", 5)
    capped = dashboard.weekly_touch_detail(admin, str(admin.id))
    assert len(capped["deals"]) == 5 and capped["truncated"] is True and capped["rep"]["touches"] == 12


def test_the_detail_is_one_bucket_and_agrees_with_the_card(week, admin, member, make_user):
    card = {r["user_id"]: r for r in dashboard.weekly_touches(admin)["reps"]}
    for owner, key in ((str(member.id), member.id), ("unassigned", None)):
        detail = dashboard.weekly_touch_detail(admin, owner)
        assert (detail["rep"]["open_deals"], detail["rep"]["touches"]) == (card[key]["open_deals"], card[key]["touches"])
        assert [d["id"] for d in detail["deals"]] == [d["id"] for d in card[key]["deals"]]
    assert dashboard.weekly_touch_detail(admin, "unassigned")["rep"]["name"] == "Unassigned"
    idle = make_user("member")
    zero = dashboard.weekly_touch_detail(admin, str(idle.id))
    assert zero["rep"] == {"user_id": idle.id, "name": idle.name, "open_deals": 0, "touches": 0, "deals": []} and zero["deals"] == []
    for unknown in ("424242", "0"):  # 0 is the system principal, never a rep
        with pytest.raises(NotFound):
            dashboard.weekly_touch_detail(admin, unknown)


def test_working_a_deal_from_the_drill_down_keeps_it_on_the_list(week, admin):
    before = [d["id"] for d in dashboard.weekly_touch_detail(admin, str(admin.id))["deals"]]
    activity.log(admin, "call", deal_id=week["a"])  # now, from the page
    assert [d["id"] for d in dashboard.weekly_touch_detail(admin, str(admin.id))["deals"]] == before


# ── Routes ────────────────────────────────────────────────────────────────────


def test_dashboard_routes(login_as):
    admin = login_as("admin")
    assert admin.post("/api/crm/deals", json={"title": "Route deal", "deal_temperature": "hot"}).status_code == 200
    assert admin.get("/api/crm/dashboard").status_code == 200
    today = admin.get("/api/crm/dashboard/today").json()
    assert [(i["kind"], i["rank"], i["reason"], i["deal"]["title"]) for i in today["items"]] == [("deal", None, "hot", "Route deal")]
    touches = admin.get("/api/crm/dashboard/weekly-touches").json()
    assert touches["window"]["label"] == "Last 7 days" and touches["reps"][0]["name"] == "Unassigned"
    assert admin.get("/api/crm/dashboard/weekly-touches?start=2026-03-08").status_code == 422
    assert admin.get("/api/crm/dashboard/weekly-touches/detail?owner=unassigned").json()["rep"]["open_deals"] == 1
    assert admin.get("/api/crm/dashboard/weekly-touches/detail?owner=424242").status_code == 404
    assert admin.get("/api/crm/dashboard/weekly-touches/detail?owner=abc").status_code == 422
