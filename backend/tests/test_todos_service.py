"""Todos for one person against a real SQLite file: the status model, lists and filters,
recurrence, Today, deferral, projects, areas, contexts and the weekly review. Ported from
todo-gtd's service tests (docs/PROVENANCE.md); two-person rules are in test_todos_permissions.py."""

import dataclasses
import datetime
import threading

import pytest

from backend.apps.todos import common, service
from backend.apps.todos.common import next_due
from backend.core import db as core_db
from backend.core.errors import Conflict, Invalid, NotFound

TODAY = datetime.date(2026, 8, 7)  # a Friday


def titles(rows):
    return [r["title"] for r in rows]


def with_tz(user, tz):
    with core_db.transaction() as conn:
        conn.execute("UPDATE core_users SET tz = ? WHERE id = ?", (tz, user.id))
    return dataclasses.replace(user, tz=tz)


@pytest.fixture
def me(app, make_user):
    """A member in Chicago, where the donor's tests lived."""
    return with_tz(make_user("member"), "America/Chicago")


def add(user, title, **fields):
    return service.create_item(user, title, **fields)


# ── Creating and updating ─────────────────────────────────────────────────────


class TestCreate:
    def test_defaults(self, me):
        todo = add(me, "Call the bank")
        assert (todo["title"], todo["status"], todo["source"]) == ("Call the bank", "inbox", "ui")
        assert (todo["visibility"], todo["owner_user_id"], todo["assignee_user_id"]) == ("private", me.id, None)
        assert (todo["tags"], todo["people"], todo["star"], todo["auto_star_on_due"]) == ([], [], False, False)
        assert (todo["project_id"], todo["project_name"], todo["due_date"], todo["completed_at"]) == (None, None, None, None)
        assert todo["owner_name"] == me.name and todo["rev"] > 0
        assert todo["created_at"].endswith("Z") and todo["updated_at"].endswith("Z")

    @pytest.mark.parametrize("title, fields, message", [
        ("   ", {}, "title is required"),
        ("x" * 20_001, {}, "title too long"),
        ("x", {"status": "doing"}, "Invalid status"),
        ("x", {"due_date": "tomorrow"}, "YYYY-MM-DD"),
        ("x", {"source": "carrier_pigeon"}, "Invalid source"),
        ("x", {"tags": "home"}, "list of strings"),
        ("x", {"project_id": 999}, "project_id: no such project"),
        ("x", {"visibility": "public"}, "Invalid visibility"),
        ("x", {"repeat": "fortnightly"}, "Invalid repeat"),
    ])  # fmt: skip
    def test_refused(self, me, title, fields, message):
        with pytest.raises(Invalid, match=message):
            add(me, title, **fields)
        assert service.list_items(me) == []

    def test_tags_normalized_and_done_is_stamped(self, me):
        assert add(me, "x", tags=["  home ", "", "energy:low"])["tags"] == ["home", "energy:low"]
        assert add(me, "x", status="done")["completed_at"] is not None

    def test_the_default_visibility_is_a_setting(self, me):
        from backend.core import settings

        assert service.filters(me)["default_visibility"] == "private"
        settings.set_setting("todos.default_visibility", "team", None)
        assert service.filters(me)["default_visibility"] == "team"  # the form's starting point
        assert add(me, "shared by default")["visibility"] == "team"
        assert add(me, "but not this", visibility="private")["visibility"] == "private"


class TestUpdate:
    def test_done_sets_completed_at_and_undone_clears(self, me):
        todo = add(me, "x")
        assert service.update_item(me, todo["id"], {"status": "done"})["completed_at"] is not None
        back = service.update_item(me, todo["id"], {"status": "next_action"})
        assert (back["completed_at"], back["status"]) == (None, "next_action")

    def test_complete_is_the_same_transition(self, me):
        todo = add(me, "x", status="next_action")
        assert service.complete(me, todo["id"])["status"] == "done"
        with pytest.raises(NotFound):
            service.complete(me, 999)

    def test_unknown_empty_and_missing(self, me):
        todo = add(me, "x")
        with pytest.raises(Invalid, match="Unknown fields: priority"):
            service.update_item(me, todo["id"], {"priority": "high"})
        with pytest.raises(Invalid, match="No fields to update"):
            service.update_item(me, todo["id"], {})
        with pytest.raises(NotFound):
            service.update_item(me, 12345, {"title": "y"})

    def test_update_bumps_updated_at(self, me):
        todo = add(me, "x")
        with core_db.transaction() as conn:
            conn.execute("UPDATE todos_items SET updated_at = '2020-01-01T00:00:00Z' WHERE id = ?", (todo["id"],))
        assert service.update_item(me, todo["id"], {"notes": "hi"})["updated_at"] > "2020-01-01T00:00:00Z"

    def test_provenance_and_bookkeeping_are_not_updatable(self, me):
        todo = add(me, "x")
        for field in ("source", "rev", "created_at", "completed_at"):
            with pytest.raises(Invalid, match="Unknown fields"):
                service.update_item(me, todo["id"], {field: "agent"})
        service.update_item(me, todo["id"], {"title": "edited", "auto_star_on_due": True})
        after = service.get_item(me, todo["id"])
        assert (after["source"], after["auto_star_on_due"]) == ("ui", True)

    @pytest.mark.parametrize("fields, message", [
        ({"title": ""}, "title cannot be empty"),
        ({"title": 123}, "title must be a string"),
        ({"due_date": "2026-13-40"}, "not a real calendar date"),
        ({"repeat": "hourly"}, "Invalid repeat"),
        ({"status": "bogus"}, "Invalid status"),
        ({"tags": "home"}, "list of strings"),
        ({"project_id": "seven"}, "project_id must be an integer"),
        ({"context": "x" * 501}, "context too long"),
        ({"star": "false"}, "star must be true or false"),
        ({"owner_user_id": None}, "owner_user_id cannot be empty"),
    ])  # fmt: skip
    def test_malformed_fields_change_nothing(self, me, fields, message):
        todo = add(me, "x")
        with pytest.raises(Invalid, match=message):
            service.update_item(me, todo["id"], fields)
        assert service.get_item(me, todo["id"])["updated_at"] == todo["updated_at"]

    def test_an_edit_lands_on_the_record_timeline(self, me):
        from backend.core.timeline import api as timeline

        todo = add(me, "x")
        service.update_item(me, todo["id"], {"status": "next_action", "notes": "n"})
        entry = timeline.list_for(me, "todos.item", todo["id"])[0]
        assert {c["field"] for c in entry["changes"]} == {"status", "notes"}


class TestBulkUpdate:
    def test_reports_updated_and_not_found(self, me):
        a, b = add(me, "a"), add(me, "b")
        result = service.bulk_update(me, [b["id"], a["id"], 999], {"status": "next_action"})
        assert result == {"updated": [a["id"], b["id"]], "not_found": [999]}
        assert service.get_item(me, a["id"])["status"] == "next_action"

    def test_done_transition_only_stamps_fresh_completions(self, me, freeze):
        freeze("2026-08-01T12:00:00Z")
        a, b = add(me, "a"), add(me, "b", status="done")
        freeze("2026-08-02T12:00:00Z")
        service.bulk_update(me, [a["id"], b["id"]], {"status": "done"})
        assert service.get_item(me, a["id"])["completed_at"] == "2026-08-02T12:00:00Z"
        assert service.get_item(me, b["id"])["completed_at"] == "2026-08-01T12:00:00Z"

    def test_a_bad_field_rejects_the_whole_batch(self, me):
        a = add(me, "a")
        for fields, message in (({"status": "bogus"}, "Invalid status"), ({"title": 123}, "title must be a string"),
                                ({"people": "Dee"}, "list of strings")):  # fmt: skip
            with pytest.raises(Invalid, match=message):
                service.bulk_update(me, [a["id"]], fields)
        assert service.get_item(me, a["id"])["status"] == "inbox"

    def test_a_failure_on_a_later_row_rolls_back_the_earlier_ones(self, me, monkeypatch):
        a = add(me, "a", status="next_action", repeat="daily")
        b = add(me, "b", status="next_action", repeat="daily")
        calls = []

        def second_spawn_fails(*args):
            calls.append(1)
            if len(calls) == 2:
                raise Invalid("spawn failed")
            return next_due(*args)

        with monkeypatch.context() as m:
            m.setattr(service, "next_due", second_spawn_fails)
            with pytest.raises(Invalid, match="spawn failed"):
                service.bulk_update(me, [a["id"], b["id"]], {"status": "done"})
        assert [service.get_item(me, i)["status"] for i in (a["id"], b["id"])] == ["next_action", "next_action"]
        assert len(service.list_items(me)) == 2

    def test_caps_ids_and_rejects_non_integers(self, me):
        with pytest.raises(Invalid, match="too many ids"):
            service.bulk_update(me, list(range(501)), {"status": "done"})
        with pytest.raises(Invalid, match="ids must be integers"):
            service.bulk_update(me, [1, "seven"], {"status": "done"})
        with pytest.raises(Invalid, match="ids is required"):
            service.bulk_update(me, [], {"status": "done"})

    def test_bulk_complete_spawns_each_repeating_todo(self, me):
        ids = [add(me, t, status="next_action", repeat=r)["id"] for t, r in (("water", "daily"), ("stretch", "weekly"), ("one-off", ""))]
        service.bulk_update(me, ids, {"status": "done"})
        assert sorted(titles(service.list_items(me, status="next_action"))) == ["stretch", "water"]


# ── Lists and filters ─────────────────────────────────────────────────────────


class TestListItems:
    def test_filters(self, me):
        project = service.create_project(me, "Ops")
        add(me, "a", project_id=project["id"], context="@Home", tags=["home"], star=True)
        add(me, "b", status="next_action", context="@office", tags=["homework"])
        add(me, "c", tags=['say "hi"', "50%"])
        assert titles(service.list_items(me, status="next_action")) == ["b"]
        assert titles(service.list_items(me, project_id=project["id"])) == ["a"]
        assert titles(service.list_items(me, context="@home")) == ["a"]
        assert titles(service.list_items(me, tag="home")) == ["a"]
        assert titles(service.list_items(me, tag='say "hi"')) == ["c"]
        assert titles(service.list_items(me, tag="50%")) == ["c"]
        assert service.list_items(me, tag="%") == []
        assert titles(service.list_items(me, starred=True)) == ["a"]
        assert titles(service.list_items(me, starred=False)) == ["b", "c"]

    def test_due_ranges_exclude_undated(self, me):
        add(me, "early", due_date="2026-01-05")
        add(me, "late", due_date="2026-03-05")
        add(me, "undated")
        assert titles(service.list_items(me, due_before="2026-02-01")) == ["early"]
        assert titles(service.list_items(me, due_after="2026-02-01")) == ["late"]
        with pytest.raises(Invalid, match="due_before must be YYYY-MM-DD"):
            service.list_items(me, due_before="soon")

    def test_search_escapes_wildcards_and_spans_fields(self, me):
        add(me, "Buy 100% juice")
        add(me, "other", notes="contains JUICE too")
        add(me, "snake_case")
        add(me, "a", context="@calls")
        add(me, "b", tags=["errands", "café"], people=["Zoë Quinn"])
        add(me, "c", project_id=service.create_project(me, "Garage Sale")["id"])
        add(me, "unrelated")
        assert len(service.list_items(me, search="juice")) == 2
        assert titles(service.list_items(me, search="100%")) == ["Buy 100% juice"]
        assert titles(service.list_items(me, search="e_c")) == ["snake_case"]
        assert titles(service.list_items(me, search="calls")) == ["a"]
        assert titles(service.list_items(me, search="errand")) == ["b"]
        assert titles(service.list_items(me, search="café")) == ["b"]
        assert titles(service.list_items(me, search="zoë q")) == ["b"]
        assert titles(service.list_items(me, search="garage")) == ["c"]
        with pytest.raises(Invalid, match="Search too long"):
            service.list_items(me, search="x" * 501)

    def test_global_search_orders_open_before_done(self, me):
        add(me, "Water the plants", status="done")
        add(me, "Water the plants", status="done")
        live = add(me, "Water the plants", status="next_action")
        results = service.list_items(me, search="water")
        assert results[0]["id"] == live["id"]
        assert [t["status"] for t in results] == ["next_action", "done", "done"]

    def test_orderings_and_limit(self, me):
        a, b = add(me, "first"), add(me, "second")
        assert titles(service.list_items(me)) == ["first", "second"]
        with core_db.transaction() as conn:
            conn.execute("UPDATE todos_items SET status='done', completed_at='2026-01-01T10:00:00Z' WHERE id=?", (a["id"],))
            conn.execute("UPDATE todos_items SET status='done', completed_at='2026-06-01T10:00:00Z' WHERE id=?", (b["id"],))
        assert titles(service.list_items(me, status="done")) == ["second", "first"]
        add(me, "third")
        assert len(service.list_items(me, limit=2)) == 2
        assert len(service.list_items(me, limit=0)) == 1
        assert len(service.list_items(me, limit=10**9)) == 3
        assert titles(service.list_items(me, limit=1, offset=2)) == ["third"]


class TestFilters:
    def test_counts_contexts_tags_people_areas(self, me):
        work = service.create_area(me, "Work")
        add(me, "a", context="@home", tags=["deep", "quick"], people=["bo", "Ana"])
        add(me, "b", context="@home", tags=["quick"], people=["Ana"], status="done")
        add(me, "c")
        f = service.filters(me)
        assert f["status_counts"] == {**dict.fromkeys(common.TODO_STATUSES, 0), "inbox": 2, "done": 1}
        assert (f["contexts"], f["tags"], f["people"]) == (["@home"], ["deep", "quick"], ["Ana", "bo"])
        assert f["areas"] == [{"id": work["id"], "name": "Work"}]
        assert {"id": me.id, "name": me.name} in f["members"]

    def test_filters_carry_the_users_timezone(self, app, make_user):
        assert service.filters(with_tz(make_user(), "Europe/Paris"))["tz"] == "Europe/Paris"
        assert service.filters(with_tz(make_user(), "Mars/Olympus"))["tz"] == "UTC"  # falls back to the install's
        assert service.filters(make_user())["tz"] == "UTC"


# ── Recurrence ────────────────────────────────────────────────────────────────


class TestRecurrence:
    def test_completing_a_repeating_todo_spawns_its_next_occurrence(self, me):
        house = service.create_project(me, "House")
        a = add(me, "Water the plants", status="next_action", context="@home", notes="both rooms", tags=["chore"],
                people=["Ana"], due_date="2099-06-01", repeat="weekly", star=True, project_id=house["id"])  # fmt: skip
        service.update_item(me, a["id"], {"status": "done"})
        [nxt] = service.list_items(me, status="next_action")
        assert nxt["id"] != a["id"]
        assert (nxt["title"], nxt["notes"], nxt["context"], nxt["tags"], nxt["people"]) == (
            "Water the plants", "both rooms", "@home", ["chore"], ["Ana"])
        assert (nxt["due_date"], nxt["repeat"], nxt["project_name"]) == ("2099-06-08", "weekly", "House")
        assert (nxt["star"], nxt["completed_at"]) == (False, None)  # today's priority doesn't carry over
        assert [t["id"] for t in service.list_items(me, status="done")] == [a["id"]]

    @pytest.mark.parametrize("prior", ["inbox", "waiting_for", "delegated", "someday_maybe"])
    def test_spawn_keeps_the_prior_status(self, me, prior):
        a = add(me, "repeating", status=prior, repeat="daily")
        service.update_item(me, a["id"], {"status": "done"})
        [spawned] = service.list_items(me, status=prior)
        assert spawned["id"] != a["id"]

    def test_spawn_from_dropped_falls_back_to_next_action(self, me):
        a = add(me, "was dropped", status="dropped", repeat="weekly")
        service.update_item(me, a["id"], {"status": "done"})
        assert titles(service.list_items(me, status="next_action")) == ["was dropped"]

    def test_only_a_fresh_completion_of_a_repeating_todo_spawns(self, me):
        assert service.complete(me, add(me, "one-off", status="next_action")["id"])
        assert service.list_items(me, status="next_action") == []
        b = add(me, "weekly thing", status="next_action", repeat="weekly")
        first = service.update_item(me, b["id"], {"status": "done"})
        again = service.update_item(me, b["id"], {"notes": "edited after done", "status": "done"})
        assert again["completed_at"] == first["completed_at"]
        assert len(service.list_items(me, status="next_action")) == 1
        service.update_item(me, b["id"], {"status": "next_action"})  # a deliberate re-completion spawns again
        service.update_item(me, b["id"], {"status": "done"})
        assert len(service.list_items(me, status="next_action")) == 2

    def test_clearing_repeat_while_completing_does_not_spawn(self, me):
        a = add(me, "was repeating", status="next_action", repeat="weekly")
        service.update_item(me, a["id"], {"repeat": "", "status": "done"})
        assert service.list_items(me, status="next_action") == []

    def test_edits_saved_with_the_completion_carry_to_the_spawn(self, me):
        a = add(me, "old title", status="next_action", repeat="weekly")
        service.update_item(me, a["id"], {"title": "new title", "repeat": "daily", "status": "done"})
        [nxt] = service.list_items(me, status="next_action")
        assert (nxt["title"], nxt["repeat"]) == ("new title", "daily")

    def test_repeat_none_means_no_repeat(self, me):
        assert add(me, "z", repeat="None")["repeat"] == ""

    def test_spawn_copies_provenance_area_and_link_but_not_the_revisit_date(self, me):
        work = service.create_area(me, "Work")
        person = _person()
        a = add(me, "r", status="next_action", repeat="daily", source="agent", area_id=work["id"],
                revisit_on="2026-08-01", entity_type="core.person", entity_id=person)  # fmt: skip
        service.complete(me, a["id"])
        [nxt] = service.list_items(me, status="next_action")
        assert (nxt["source"], nxt["area_id"], nxt["revisit_on"]) == ("agent", work["id"], None)
        assert (nxt["entity_type"], nxt["entity_id"]) == ("core.person", person)

    def test_a_failed_spawn_rolls_back_the_completion(self, me, monkeypatch):
        a = add(me, "r", status="next_action", repeat="daily")

        def boom(*args):
            raise RuntimeError("spawn failed")

        with monkeypatch.context() as m:
            m.setattr(service, "next_due", boom)
            with pytest.raises(RuntimeError, match="spawn failed"):
                service.update_item(me, a["id"], {"status": "done", "title": "renamed"})
        after = service.get_item(me, a["id"])
        assert (after["status"], after["title"], after["completed_at"]) == ("next_action", "r", None)
        assert len(service.list_items(me)) == 1
        assert service.update_item(me, a["id"], {"status": "done"})["status"] == "done"  # the connection is usable

    def test_two_threads_completing_the_same_todo_spawn_once(self, me):
        a = add(me, "r", status="next_action", repeat="daily")
        barrier, errors = threading.Barrier(8), []

        def complete():
            try:
                barrier.wait()
                service.update_item(me, a["id"], {"status": "done"})
            except Exception as e:  # pragma: no cover - reported below
                errors.append(e)

        threads = [threading.Thread(target=complete) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        assert len(service.list_items(me, status="done")) == 1
        assert len(service.list_items(me, status="next_action")) == 1


def _person() -> int:
    from backend.core import clock

    now = clock.now_iso()
    with core_db.transaction() as conn:
        return conn.execute("INSERT INTO core_people (name, created_at, updated_at) VALUES ('Ada', ?, ?)", (now, now)).lastrowid


class TestAutoStar:
    """Opt-in: the spawned occurrence comes back starred only when it is due today."""

    @pytest.fixture(autouse=True)
    def _clock(self, freeze):
        freeze("2026-08-07T18:00:00Z")  # 1pm Aug 7 in Chicago

    def _spawn(self, me, days_ago, **kw):
        due = (TODAY - datetime.timedelta(days=days_ago)).isoformat()
        a = add(me, "routine", status="next_action", repeat="weekly", due_date=due, **kw)
        service.update_item(me, a["id"], {"status": "done"})
        return service.list_items(me, status="next_action")[0]

    def test_stars_when_the_spawn_is_due_today(self, me):
        nxt = self._spawn(me, 7, auto_star_on_due=True)
        assert (nxt["due_date"], nxt["star"], nxt["auto_star_on_due"]) == ("2026-08-07", True, True)

    def test_does_not_star_a_future_occurrence(self, me):
        nxt = self._spawn(me, -1, auto_star_on_due=True)
        assert (nxt["due_date"], nxt["star"]) == ("2026-08-15", False)

    def test_does_not_star_when_more_than_one_interval_late(self, me):
        nxt = self._spawn(me, 14, auto_star_on_due=True)
        assert (nxt["due_date"], nxt["star"]) == ("2026-08-14", False)  # re-anchored past today

    def test_due_today_without_the_flag_is_not_starred(self, me):
        nxt = self._spawn(me, 7)
        assert (nxt["due_date"], nxt["star"], nxt["auto_star_on_due"]) == ("2026-08-07", False, False)


class TestEachUsersToday:
    """"Today" is each user's own calendar date."""

    def test_today_view_across_a_timezone_boundary(self, app, make_user, freeze):
        freeze("2026-08-08T01:00:00Z")  # Aug 7 8pm in Chicago, Aug 8 1pm in Auckland
        chicago, auckland = with_tz(make_user(), "America/Chicago"), with_tz(make_user(), "Pacific/Auckland")
        for user in (chicago, auckland):
            add(user, "due the 7th", due_date="2026-08-07")
            add(user, "due the 8th", due_date="2026-08-08")
            add(user, "starred", star=True)
            add(user, "later", due_date="2026-09-01")
            add(user, "done", due_date="2026-08-01", status="done")
            add(user, "archived", due_date="2026-08-01", status="dropped")
        assert titles(service.today_view(chicago)) == ["due the 7th", "starred"]
        assert titles(service.today_view(auckland)) == ["due the 7th", "due the 8th", "starred"]

    def test_today_view_across_a_dst_boundary(self, me, freeze):
        add(me, "due Nov 1", due_date="2026-11-01")
        freeze("2026-11-01T04:30:00Z")  # 23:30 Oct 31, still daylight time
        assert service.today_view(me) == []
        freeze("2026-11-01T05:30:00Z")  # 00:30 Nov 1 CDT; a fixed UTC-6 would say Oct 31
        assert titles(service.today_view(me)) == ["due Nov 1"]

    def test_the_install_timezone_when_the_user_has_none(self, app, make_user, freeze):
        from backend.core import settings

        settings.set_setting("timezone", "Pacific/Auckland", None)
        freeze("2026-08-08T01:00:00Z")
        user = make_user()
        add(user, "due the 8th", due_date="2026-08-08")
        assert titles(service.today_view(user)) == ["due the 8th"]

    def test_spawn_uses_the_completers_own_today(self, app, make_user, freeze):
        freeze("2026-08-08T01:00:00Z")
        results = {}
        for tz in ("America/Chicago", "Pacific/Auckland"):
            user = with_tz(make_user(), tz)
            a = add(user, "daily", status="next_action", repeat="daily", due_date="2026-08-06", auto_star_on_due=True)
            service.update_item(user, a["id"], {"status": "done"})
            nxt = service.list_items(user, status="next_action")[0]
            results[tz] = (nxt["due_date"], nxt["star"])
        assert results["America/Chicago"] == ("2026-08-07", True)  # one day late on the 7th: due today, starred
        assert results["Pacific/Auckland"] == ("2026-08-09", False)  # two days late on the 8th: re-anchored


# ── People and the revisit date ───────────────────────────────────────────────


class TestPeople:
    def test_validated_and_capped_like_tags(self, me):
        assert add(me, "x", people=["  Ana ", "", "Bo"])["people"] == ["Ana", "Bo"]
        for people, message in (("Ana", "people must be a list of strings"), ([str(i) for i in range(51)], "too many people"),
                                (["x" * 501], "person too long")):  # fmt: skip
            with pytest.raises(Invalid, match=message):
                add(me, "x", people=people)
        assert len(service.list_items(me)) == 1

    def test_update_bulk_and_exact_filter(self, me):
        a = add(me, "with ana", people=["Ana", "Bo"])
        b = add(me, "with anabel", people=["Anabel"])
        add(me, "tagged ana", tags=["Ana"])
        assert titles(service.list_items(me, person="Ana")) == ["with ana"]
        assert service.list_items(me, person="ana") == []
        service.bulk_update(me, [a["id"], b["id"]], {"people": ["Dee"]})
        assert titles(service.list_items(me, person="Dee")) == ["with ana", "with anabel"]
        assert service.update_item(me, a["id"], {"people": None})["people"] == []


class TestRevisit:
    def test_validated_like_a_due_date(self, me):
        a = add(me, "x", revisit_on="2026-09-01")
        assert a["revisit_on"] == "2026-09-01"
        with pytest.raises(Invalid, match="revisit_on must be YYYY-MM-DD"):
            add(me, "x", revisit_on="next month")
        with pytest.raises(Invalid, match="revisit_on is not a real calendar date"):
            service.update_item(me, a["id"], {"revisit_on": "2026-02-30"})
        assert service.update_item(me, a["id"], {"revisit_on": ""})["revisit_on"] is None

    def test_surfaces_on_today_by_the_users_calendar_and_changes_nothing(self, me, freeze):
        freeze("2026-08-08T01:00:00Z")  # Aug 7 8pm in Chicago
        a = add(me, "back the 7th", status="someday_maybe", revisit_on="2026-08-07")
        add(me, "back the 8th", status="someday_maybe", revisit_on="2026-08-08")
        add(me, "no date", status="someday_maybe")
        add(me, "done", status="done", revisit_on="2026-08-01")
        assert titles(service.today_view(me)) == ["back the 7th"]
        assert service.get_item(me, a["id"]) == a  # still someday, same date, untouched
        freeze("2026-08-08T05:00:00Z")  # Chicago's date turns
        assert titles(service.today_view(me)) == ["back the 7th", "back the 8th"]


class TestDeferred:
    """A todo with a future revisit date is off the working lists until that day in the user's
    own timezone, then shows as usual. Record views, search and the review's `upcoming` still see it."""

    @pytest.fixture
    def deferred(self, me, freeze):
        freeze("2026-08-08T18:00:00Z")
        project = service.create_project(me, "Lease")
        later = add(me, "ask about the lease", status="next_action", revisit_on="2026-08-09",
                    project_id=project["id"], star=True, due_date="2026-08-01")  # fmt: skip
        add(me, "plain", status="next_action")
        return later

    def test_off_the_working_lists_until_its_day(self, me, deferred, freeze):
        assert titles(service.list_items(me)) == ["plain"]
        assert titles(service.list_items(me, starred=True)) == []
        assert service.today_view(me) == []  # starred and overdue, and still not on Today
        assert service.filters(me)["status_counts"]["next_action"] == 1
        freeze("2026-08-09T04:59:00Z")  # 23:59 on the 8th in Chicago
        assert titles(service.list_items(me)) == ["plain"]
        freeze("2026-08-09T05:00:00Z")  # midnight: its day
        assert titles(service.list_items(me)) == ["ask about the lease", "plain"]
        assert titles(service.today_view(me)) == ["ask about the lease"]
        assert service.filters(me)["status_counts"]["next_action"] == 2

    def test_search_and_record_views_still_reach_it(self, me, deferred):
        assert titles(service.list_items(me, search="lease")) == ["ask about the lease"]
        assert titles(service.list_items(me, include_deferred=True)) == ["ask about the lease", "plain"]
        assert service.get_item(me, deferred["id"])["revisit_on"] == "2026-08-09"
        assert service.list_projects(me)[0]["open_count"] == 1  # it still covers its project
        assert service.review(me)["projects_without_next_action"] == []

    def test_finished_todos_and_cleared_dates_are_not_hidden(self, me, deferred):
        add(me, "done", status="done", revisit_on="2026-09-01")
        add(me, "archived", status="dropped", revisit_on="2026-09-01")
        assert titles(service.list_items(me, status="done")) == ["done"]
        assert titles(service.list_items(me, status="dropped")) == ["archived"]
        service.update_item(me, deferred["id"], {"revisit_on": None})
        assert titles(service.list_items(me, status="next_action")) == ["ask about the lease", "plain"]


# ── Projects and areas ────────────────────────────────────────────────────────


class TestProjects:
    def test_create_validate_and_rename(self, me):
        p = service.create_project(me, "Launch", purpose="grow revenue", outcome="live by Q4")
        assert (p["purpose"], p["outcome"], p["status"], p["visibility"], p["open_count"]) == (
            "grow revenue", "live by Q4", "active", "private", 0)
        with pytest.raises(Invalid, match='Project "launch" already exists'):
            service.create_project(me, "launch")
        with pytest.raises(Invalid, match="name is required"):
            service.create_project(me, "  ")
        with pytest.raises(Invalid, match="Invalid project status"):
            service.create_project(me, "x", status="paused")
        with pytest.raises(Invalid, match="purpose too long"):
            service.create_project(me, "Q", purpose="x" * 20_001)
        b = service.create_project(me, "B")
        with pytest.raises(Invalid, match="already exists"):
            service.update_container(me, "project", b["id"], {"name": "LAUNCH"})
        assert service.update_container(me, "project", b["id"], {"name": "b"})["name"] == "b"  # its own name, recased
        after = service.update_container(me, "project", p["id"], {"outcome": "live by Q3", "purpose": None})
        assert (after["purpose"], after["outcome"]) == ("", "live by Q3")
        with pytest.raises(NotFound):
            service.update_container(me, "project", 999, {"name": "x"})

    def test_open_count_archive_and_order(self, me):
        p = service.create_project(me, "P")
        for status in ("inbox", "done", "dropped"):
            add(me, status, project_id=p["id"], status=status)
        assert service.list_projects(me)[0]["open_count"] == 1
        assert service.update_container(me, "project", p["id"], {"status": "dropped"})["status"] == "dropped"
        assert service.list_projects(me, status="active") == []
        assert service.list_items(me, project_id=p["id"], status="inbox")[0]["project_id"] == p["id"]
        for name in ("beta", "Alpha", "Gamma"):
            service.create_project(me, name)
        assert [x["name"] for x in service.list_projects(me, status="active")] == ["Alpha", "beta", "Gamma"]

    def test_delete_leaves_its_todos_loose(self, me):
        p = service.create_project(me, "P")
        t = add(me, "x", project_id=p["id"])
        service.delete_container(me, "project", p["id"])
        assert service.get_item(me, t["id"])["project_id"] is None
        with pytest.raises(NotFound):
            service.get_container(me, "project", p["id"])


class TestAreas:
    def test_create_list_update_archive(self, me):
        health = service.create_area(me, "  Health ", notes="body and mind")
        assert (health["name"], health["notes"], health["status"]) == ("Health", "body and mind", "active")
        service.create_area(me, "family")
        assert [a["name"] for a in service.list_areas(me)] == ["family", "Health"]
        renamed = service.update_container(me, "area", health["id"], {"name": "Fitness", "notes": ""})
        assert (renamed["name"], renamed["notes"]) == ("Fitness", "")
        assert service.update_container(me, "area", health["id"], {"status": "dropped"})["status"] == "dropped"
        assert [a["name"] for a in service.list_areas(me, status="active")] == ["family"]
        assert len(service.list_areas(me)) == 2  # archived, not gone

    def test_validation(self, me):
        a, b = service.create_area(me, "Work"), service.create_area(me, "Home")
        with pytest.raises(Invalid, match='Area "work" already exists'):
            service.create_area(me, "work")
        with pytest.raises(Invalid, match="already exists"):
            service.update_container(me, "area", b["id"], {"name": "WORK"})
        with pytest.raises(Invalid, match="name cannot be empty"):
            service.update_container(me, "area", a["id"], {"name": " "})
        with pytest.raises(Invalid, match="Invalid area status"):
            service.update_container(me, "area", a["id"], {"status": "completed"})
        with pytest.raises(Invalid, match="Invalid area status"):
            service.list_areas(me, status="completed")
        with pytest.raises(Invalid, match="Unknown fields: area_id"):
            service.update_container(me, "area", a["id"], {"area_id": 2})

    def test_a_todo_shows_its_projects_area_unless_it_has_its_own(self, me):
        work, home = service.create_area(me, "Work"), service.create_area(me, "Home")
        project = service.create_project(me, "Launch", area_id=work["id"])
        assert (project["area_id"], project["area_name"]) == (work["id"], "Work")
        inherited = add(me, "inherits", project_id=project["id"])
        assert (inherited["area_id"], inherited["effective_area_id"], inherited["area_name"]) == (None, work["id"], "Work")
        own = add(me, "has its own", project_id=project["id"], area_id=home["id"])
        assert (own["effective_area_id"], own["area_name"]) == (home["id"], "Home")
        add(me, "loose", area_id=home["id"])
        assert titles(service.list_items(me, area_id=work["id"])) == ["inherits"]
        assert titles(service.list_items(me, area_id=home["id"])) == ["has its own", "loose"]
        service.update_container(me, "project", project["id"], {"area_id": home["id"]})
        assert service.get_item(me, inherited["id"])["area_name"] == "Home"
        assert [p["name"] for p in service.list_projects(me, area_id=home["id"])] == ["Launch"]

    def test_an_archived_area_keeps_its_items_but_leaves_the_pickers(self, me):
        work = service.create_area(me, "Work")
        todo = add(me, "x", area_id=work["id"])
        service.update_container(me, "area", work["id"], {"status": "dropped"})
        assert service.filters(me)["areas"] == []
        assert service.get_item(me, todo["id"])["area_name"] == "Work"

    def test_delete_leaves_projects_and_todos_loose(self, me):
        work = service.create_area(me, "Work")
        p = service.create_project(me, "P", area_id=work["id"])
        t = add(me, "x", area_id=work["id"])
        service.delete_container(me, "area", work["id"])
        assert service.get_container(me, "project", p["id"])["area_id"] is None
        assert service.get_item(me, t["id"])["area_id"] is None


# ── Contexts ──────────────────────────────────────────────────────────────────


class TestRenameContext:
    def test_rename_moves_every_todo_carrying_it(self, me):
        open_one = add(me, "bake", context="@Baking", status="next_action")
        add(me, "bake", context="@Baking", status="done")
        office = add(me, "bake", context="TK Office")
        assert service.rename_context(me, "@Baking", " Baking ") == {"old": "@Baking", "new": "Baking", "updated": 2, "merged": False}
        assert service.filters(me)["contexts"] == ["Baking", "TK Office"]
        after = service.get_item(me, open_one["id"])
        assert after["context"] == "Baking" and after["updated_at"] == open_one["updated_at"]  # a rename is not an edit
        assert after["rev"] > open_one["rev"]  # but a sync sees it
        assert service.get_item(me, office["id"])["context"] == "TK Office"

    def test_a_merge_waits_for_the_confirmation(self, me):
        a = add(me, "bake", context="@Baking")
        add(me, "bake", context="Baking")
        with pytest.raises(Conflict, match='already have a context named "Baking"'):
            service.rename_context(me, "@Baking", "Baking")
        assert service.get_item(me, a["id"])["context"] == "@Baking"
        assert service.rename_context(me, "@Baking", "Baking", merge=True)["merged"] is True
        assert service.filters(me)["contexts"] == ["Baking"]

    @pytest.mark.parametrize("old, new, error, message", [
        ("", "Baking", Invalid, "context is required"),
        ("@Baking", "  ", Invalid, "new name cannot be empty"),
        ("@Baking", "@Baking", Invalid, "already named"),
        ("@Baking", "x" * 501, Invalid, "new name too long"),
        ("@Nope", "Baking", NotFound, "No todo you can see"),
    ])  # fmt: skip
    def test_refused(self, me, old, new, error, message):
        add(me, "bake", context="@Baking")
        with pytest.raises(error, match=message):
            service.rename_context(me, old, new)


# ── The weekly review ─────────────────────────────────────────────────────────


class TestReview:
    def test_sections_hide_deferred_todos_until_their_day(self, me, freeze):
        freeze("2026-07-01T18:00:00Z")
        for title, extra in (("put away", {"revisit_on": "2026-08-15"}), ("live", {})):
            add(me, f"{title}, waiting", status="waiting_for", due_date="2026-07-02", **extra)
            add(me, f"{title}, inbox", **extra)

        def sections():
            data = service.review(me)
            return {name: (titles(data[name]["items"]), data[name]["count"]) for name in
                    ("inbox", "dated_today_or_overdue", "waiting_for", "stale", "upcoming")}  # fmt: skip

        freeze("2026-08-08T18:00:00Z")  # weeks untouched and overdue, but not back until the 15th
        assert sections() == {
            "inbox": (["live, inbox"], 1),
            "dated_today_or_overdue": (["live, waiting"], 1),
            "waiting_for": (["live, waiting"], 1),
            "stale": (["live, waiting"], 1),
            "upcoming": (["put away, waiting", "put away, inbox"], 2),
        }
        freeze("2026-08-15T05:00:00Z")  # its day in Chicago
        both = ["put away, waiting", "live, waiting"]
        assert sections() == {
            "inbox": (["put away, inbox", "live, inbox"], 2),
            "dated_today_or_overdue": (["put away, waiting", "put away, inbox", "live, waiting"], 3),
            "waiting_for": (both, 2),
            "stale": (both, 2),
            "upcoming": ([], 0),
        }

    def test_completed_routines_projects_and_areas(self, me, freeze):
        freeze("2026-07-30T12:00:00Z")
        old = add(me, "long done", status="next_action")
        service.complete(me, old["id"])
        freeze("2026-08-08T12:00:00Z")
        service.complete(me, add(me, "just done")["id"])
        add(me, "water", status="next_action", repeat="daily")
        idle = service.create_project(me, "Idle")
        busy = service.create_project(me, "Busy")
        add(me, "next", status="next_action", project_id=busy["id"])
        service.create_area(me, "Home")
        data = service.review(me, limit=1)
        assert titles(data["completed_last_week"]["items"]) == ["just done"]
        assert titles(data["routines"]["items"]) == ["water"]
        assert [p["id"] for p in data["projects_without_next_action"]] == [idle["id"]]
        assert [a["name"] for a in data["areas"]] == ["Home"]
        assert data["today"] == "2026-08-08"

    def test_review_status_counts_the_users_calendar_days(self, me, freeze):
        with core_db.transaction() as conn:
            conn.execute("UPDATE core_users SET created_at = '2026-08-01T12:00:00Z' WHERE id = ?", (me.id,))
        freeze("2026-08-01T12:00:00Z")
        assert service.review_status(me) == {"review_due": False, "days_since_review": None, "last_review_at": None}
        freeze("2026-08-20T12:00:00Z")
        assert service.review_status(me)["review_due"] is True  # a week past the account's creation
        freeze("2026-08-21T04:50:00Z")  # 23:50 on the 20th in Chicago
        assert service.mark_review_done(me) == {"review_due": False, "days_since_review": 0, "last_review_at": "2026-08-21T04:50:00Z"}
        freeze("2026-08-21T05:00:00Z")  # ten minutes later it is "yesterday"
        assert service.review_status(me)["days_since_review"] == 1


# ── Recurrence math and validators (common.py) ────────────────────────────────


def _future(days: int) -> datetime.date:
    return TODAY + datetime.timedelta(days=days)


def test_next_due_advances_from_the_old_due_date_and_reanchors_when_past():
    base = _future(10)
    assert next_due("weekly", base.isoformat(), TODAY) == (base + datetime.timedelta(days=7)).isoformat()
    assert next_due("every:3", base, TODAY) == (base + datetime.timedelta(days=3)).isoformat()
    assert next_due("weekly", "2020-01-06", TODAY) == _future(7).isoformat()  # years late: no overdue copy
    assert next_due("daily", _future(-1).isoformat(), TODAY) == TODAY.isoformat()  # one day late: today, not tomorrow
    assert next_due("weekly", _future(-3).isoformat(), TODAY) == _future(4).isoformat()  # keeps its anchor
    assert next_due("weekly", None, TODAY) == _future(7).isoformat()
    assert next_due("daily", "not-a-date", TODAY) == _future(1).isoformat()


def test_next_due_calendar_rules():
    assert next_due("weekdays", TODAY.isoformat(), TODAY) == "2026-08-10"  # Friday to Monday
    assert next_due("monthly", "2030-01-31", TODAY) == "2030-02-28"
    assert next_due("monthly", "2030-03-31", TODAY) == "2030-04-30"
    assert next_due("monthly", "2099-12-15", TODAY) == "2100-01-15"
    assert next_due("yearly", "2032-02-29", TODAY) == "2033-02-28"
    for bad in ("", "bogus"):
        with pytest.raises(Invalid, match="Invalid repeat"):
            next_due(bad, "2099-01-01", TODAY)
    with pytest.raises(Invalid, match="out of range"):
        next_due("yearly", "9999-06-01", TODAY)


@pytest.mark.parametrize("value, expected", [
    ("", ""), ("none", ""), ("None", ""), (None, ""), ("DAILY", "daily"), ("weekdays", "weekdays"), ("every:14", "every:14"),
])  # fmt: skip
def test_validate_repeat_accepts(value, expected):
    assert common.validate_repeat(value) == expected


@pytest.mark.parametrize("value", ["hourly", "every:0", "every:10000", "every:", "weekly-ish"])
def test_validate_repeat_rejects(value):
    with pytest.raises(Invalid):
        common.validate_repeat(value)


@pytest.mark.parametrize("value", ["tomorrow", "08/15/2026", "2026-8-5", "2026-13-01", "2026-02-30", "2026-00-10"])
def test_validate_due_rejects(value):
    with pytest.raises(Invalid):
        common.validate_due(value)


def test_validate_due_accepts_real_dates_and_none():
    assert (common.validate_due("2026-08-15"), common.validate_due(None), common.validate_due("")) == ("2026-08-15", None, None)
