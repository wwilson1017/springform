"""CRM deals on a real SQLite file: the lifecycle (lead → won → archive → restore → merge), the
stage, probability, closed_on and lost_reason rules, bulk moves, money in cents, Unicode search,
the record hooks and the CRM's own reset. Behaviour ported from CakeCRM's deal lifecycle,
closed_on and bulk-move suites (docs/PROVENANCE.md)."""

import pytest

from backend.apps.crm import activity, deals, meta, provenance, scoring
from backend.core import db as core_db, entities, settings
from backend.core.contacts import api as contacts
from backend.core.errors import Conflict, Forbidden, Invalid, NotFound
from backend.core.timeline import api as timeline

NOW = "2026-10-14T15:00:00Z"  # 10:00 in Chicago


@pytest.fixture
def me(app, make_user, freeze):
    freeze(NOW)
    return make_user("member")


@pytest.fixture
def people(me):
    with core_db.transaction() as conn:
        org = contacts.create_organization_in(conn, me, name="Demo Café Group")
        zoe = contacts.create_person_in(conn, me, name="Zoë Démo", email="zoe@example.com")
        ada = contacts.create_person_in(conn, me, name="Ada Example")
    return {"org": org["id"], "zoe": zoe["id"], "ada": ada["id"]}


def new(user, title="Wedding cakes", **fields):
    return deals.create(user, {"title": title, **fields})


def stage_moves(deal_id):
    return [(r["old_stage"], r["new_stage"]) for r in core_db.rows(
        "SELECT old_stage, new_stage FROM crm_deal_stage_events WHERE deal_id = ? ORDER BY id", (deal_id,)
    )]  # fmt: skip


def set_tz(tz):
    with core_db.transaction() as conn:
        settings.set_setting_in(conn, "timezone", tz, None)


# ── Lifecycle ─────────────────────────────────────────────────────────────────


def test_lead_to_won_to_archive_to_restore_to_merge(me, people, freeze):
    deal = new(me, person_id=people["zoe"], organization_id=people["org"], value_cents=125_000, probability=30)
    assert (deal["stage"], deal["status"], deal["person_name"], deal["organization_name"]) == ("lead", "open", "Zoë Démo", "Demo Café Group")
    assert (deal["currency"], deal["created_at"], deal["closed_on"]) == ("USD", NOW, None)

    won = deals.update(me, deal["id"], {"stage": "won"})
    assert (won["status"], won["probability"], won["closed_on"]) == ("won", 100, "2026-10-14")

    freeze("2026-10-15T09:00:00Z")
    archived = deals.archive(me, deal["id"], "  Duplicate of another deal  ")
    assert (archived["archived_at"], archived["archived_by"], archived["archived_reason"]) == ("2026-10-15T09:00:00Z", me.id, "Duplicate of another deal")
    assert archived["updated_at"] == NOW, "archiving is not a touch"
    assert deals.board(me)["deals"] == []
    assert [d["id"] for d in deals.board(me, include_archived=True)["deals"]] == [deal["id"]]

    restored = deals.restore(me, deal["id"])
    assert (restored["archived_at"], restored["archived_by"], restored["archived_reason"]) == (None, None, None)

    other = new(me, "Wedding cakes (dup)", person_id=people["ada"])
    timeline.add_note(me, "crm.deal", other["id"], "Asked about a three-tier cake")
    activity.log(me, "call", "Left a message", deal_id=other["id"])
    merged = deals.merge(me, deal["id"], other["id"])
    assert merged["id"] == deal["id"] and merged["title"] == "Wedding cakes" and merged["person_id"] == people["zoe"]
    source = deals.get(me, other["id"])
    assert (source["archived_reason"], source["archived_by"]) == (f"Merged into deal #{deal['id']}", me.id)
    bodies = [e["body"] for e in timeline.list_for(me, "crm.deal", deal["id"]) if e["kind"] == "note"]
    assert "Asked about a three-tier cake" in bodies and any(b.startswith(f"Merged deal #{other['id']}") for b in bodies)
    assert [a["deal_id"] for a in activity.list_(me)] == [deal["id"]]
    assert stage_moves(deal["id"]) == [("", "lead"), ("lead", "won")]


def test_every_edit_lands_on_the_timeline_and_the_change_log(me):
    deal = new(me)
    deals.update(me, deal["id"], {"stage": "qualified", "value_cents": 50_000})
    entry = timeline.list_for(me, "crm.deal", deal["id"])[0]
    assert entry["kind"] == "field_change"
    assert {c["field"]: (c["old"], c["new"]) for c in entry["changes"]} == {"stage": ("lead", "qualified"), "value_cents": (0, 50_000)}
    logged = core_db.rows("SELECT field FROM core_change_log WHERE entity = 'crm.deal' AND entity_id = ? ORDER BY field", (deal["id"],))
    assert [r["field"] for r in logged] == ["stage", "value_cents"]


def test_a_no_op_write_changes_nothing(me, freeze):
    deal = new(me, stage="proposal", value_cents=10_000)
    freeze("2026-10-20T12:00:00Z")
    same = deals.update(me, deal["id"], {"stage": "proposal", "value_cents": 10_000, "title": "Wedding cakes"})
    assert same["updated_at"] == NOW
    assert stage_moves(deal["id"]) == [("", "proposal")]
    assert deals.bulk_move(me, [deal["id"]], "proposal") == {"ok": True, "updated": 0, "updated_ids": [], "errors": []}
    assert timeline.list_for(me, "crm.deal", deal["id"]) == []


def test_closing_settles_probability_and_leaving_lost_clears_the_reason(me):
    deal = new(me, probability=40)
    assert deals.update(me, deal["id"], {"stage": "won", "probability": 30})["probability"] == 100, "the close overrides it"
    assert deals.update(me, deal["id"], {"probability": 80})["probability"] == 80, "an edit after the close is the caller's"
    lost = deals.mark_lost(me, deal["id"], "  Went with another baker  ")
    assert (lost["stage"], lost["probability"], lost["lost_reason"], lost["closed_on"]) == ("lost", 0, "Went with another baker", None)
    assert deals.mark_lost(me, deal["id"], "x" * 900)["lost_reason"] == "x" * 500
    assert deals.update(me, deal["id"], {"notes": "still lost"})["lost_reason"] == "x" * 500
    reopened = deals.update(me, deal["id"], {"stage": "negotiation"})
    assert (reopened["lost_reason"], reopened["status"]) == ("", "open")
    assert stage_moves(deal["id"]) == [("", "lead"), ("lead", "won"), ("won", "lost"), ("lost", "negotiation")]


def test_born_closed(me):
    won = new(me, stage="won", probability=10)
    assert (won["probability"], won["closed_on"]) == (100, "2026-10-14")
    assert new(me, stage="won", closed_on="2026-09-30")["closed_on"] == "2026-09-30"
    assert new(me, stage="lost", probability=90)["probability"] == 0
    with pytest.raises(Invalid, match="only be set on a won deal"):
        new(me, closed_on="2026-09-30")


# ── closed_on ─────────────────────────────────────────────────────────────────


def test_closed_on_is_the_install_local_day(me, freeze):
    set_tz("America/Chicago")
    freeze("2026-10-15T03:30:00Z")  # 22:30 on the 14th in Chicago
    assert deals.mark_won(me, new(me)["id"])["closed_on"] == "2026-10-14"


def test_closed_on_rules(me):
    deal = new(me)
    assert deals.mark_won(me, deal["id"], "2026-10-01")["closed_on"] == "2026-10-01", "a win can be backdated"
    assert deals.mark_won(me, deal["id"])["closed_on"] == "2026-10-01", "re-marking won keeps the day"
    assert deals.mark_won(me, deal["id"], "2026-10-03")["closed_on"] == "2026-10-03", "a day on a won deal edits it"
    assert deals.update(me, deal["id"], {"closed_on": "2026-10-04"})["closed_on"] == "2026-10-04"
    assert deals.update(me, deal["id"], {"closed_on": None})["closed_on"] == "2026-10-04", "null is 'not given', never a blank"
    for bad in ("2026-10-15", "2026-02-30", "20261001", "yesterday"):
        with pytest.raises(Invalid):
            deals.mark_won(me, deal["id"], bad)
    assert deals.update(me, deal["id"], {"stage": "proposal"})["closed_on"] is None, "leaving won clears it"
    with pytest.raises(Invalid, match="only be set on a won deal"):
        deals.update(me, deal["id"], {"closed_on": "2026-10-01"})
    assert deals.update(me, deal["id"], {"stage": "won", "closed_on": "2026-10-02"})["closed_on"] == "2026-10-02"


# ── Archive and merge guards ──────────────────────────────────────────────────


def test_an_archived_deal_keeps_its_stage_until_restored(me):
    deal = new(me)
    deals.archive(me, deal["id"], "Paused")
    with pytest.raises(Conflict, match="restore it"):
        deals.update(me, deal["id"], {"stage": "won"})
    assert deals.update(me, deal["id"], {"notes": "an edit that is not a stage move"})["notes"].startswith("an edit")
    assert deals.archive(me, deal["id"], "")["archived_reason"] == "Paused", "re-archiving is a no-op, reason or not"
    with pytest.raises(Invalid, match="reason is required"):
        deals.archive(me, new(me)["id"], "   ")
    with pytest.raises(Conflict, match="archived"):
        deals.merge(me, new(me)["id"], deal["id"])


def test_merge_refuses_itself_and_missing_deals(me):
    deal = new(me)
    with pytest.raises(Invalid):
        deals.merge(me, deal["id"], deal["id"])
    with pytest.raises(NotFound):
        deals.merge(me, deal["id"], 9999)


# ── Bulk move ─────────────────────────────────────────────────────────────────


def test_bulk_move(me):
    a, b, c = (new(me, f"Deal {i}") for i in range(3))
    deals.archive(me, c["id"], "Stopped")
    deals.mark_lost(me, b["id"], "Budget")
    out = deals.bulk_move(me, [a["id"], b["id"], a["id"], c["id"], 9999], "won", "2026-10-10")
    assert (out["ok"], out["updated_ids"]) == (True, [a["id"], b["id"]])
    assert out["errors"] == [f"Deal #{c['id']} is archived; restore it before changing its stage", "Deal 9999 not found"]
    moved = deals.get(me, b["id"])
    assert (moved["closed_on"], moved["probability"], moved["lost_reason"]) == ("2026-10-10", 100, "")
    out = deals.bulk_move(me, [a["id"]], "proposal", "2026-10-10")
    assert deals.get(me, a["id"])["closed_on"] is None, "closed_on is ignored off won; leaving won clears it"


@pytest.mark.parametrize("ids, stage, message", [
    ([1], "doing", "Invalid stage"),
    ([], "won", "No deal ids"),
    ([0], "won", "positive integers"),
    ([True], "won", "positive integers"),
    (list(range(1, 202)), "won", "at most 200"),
])  # fmt: skip
def test_bulk_move_refusals_write_nothing(me, ids, stage, message):
    out = deals.bulk_move(me, ids, stage)
    assert out["ok"] is False and message in out["errors"][0]


def test_bulk_move_refuses_a_future_day(me):
    deal = new(me)
    assert deals.bulk_move(me, [deal["id"]], "won", "2026-12-25")["ok"] is False
    assert deals.get(me, deal["id"])["stage"] == "lead"


# ── Money and search ──────────────────────────────────────────────────────────


def test_money_is_integer_cents(me):
    cents = [1, 10, 33, 199_999, 10**12 + 1]
    for value in cents:
        new(me, f"Deal {value}", value_cents=value, stage="proposal")
    board = deals.board(me)
    assert board["total_pipeline_value_cents"] == sum(cents)
    assert all(isinstance(d["value_cents"], int) for d in board["deals"])
    assert core_db.one("SELECT typeof(sum(value_cents)) AS t FROM crm_deals")["t"] == "integer"
    with pytest.raises(Invalid):
        new(me, value_cents=10.5)
    with core_db.transaction() as conn, pytest.raises(Exception, match="CHECK"):
        conn.execute("UPDATE crm_deals SET value_cents = 0.1")


def test_search_folds_case_and_accents_and_reads_linked_names(me, people):
    cafe = new(me, "Café pastry subscription", notes="Weekly CROISSANTS")
    zoe = new(me, "Spring order", person_id=people["zoe"])
    org = new(me, "Shelf space", organization_id=people["org"])
    new(me, "Unrelated")

    def found(q):
        return sorted(d["id"] for d in deals.search(me, q))

    assert found("cafe") == sorted([cafe["id"], org["id"]])
    assert found("CAFÉ PASTRY") == [cafe["id"]]
    assert found("croissant") == [cafe["id"]], "prefix match"
    assert found("zoe") == [zoe["id"]]
    assert found('") OR 1=1 --') == [], "FTS syntax in user text is quoted away"
    deals.archive(me, cafe["id"], "Stopped")
    assert found("pastry") == []
    assert [d["id"] for d in deals.search(me, "pastry", include_archived=True)] == [cafe["id"]]


def test_board_modes(me):
    ids = [new(me, f"Deal {i}", stage=("lead", "proposal")[i % 2])["id"] for i in range(5)]
    page = deals.board(me, limit=2)
    assert [d["id"] for d in page["deals"]] == ids[:2] and page["stage_summary"] is not None
    rest = deals.board(me, limit=10, after_id=ids[1])
    assert [d["id"] for d in rest["deals"]] == ids[2:] and rest["stage_summary"] is None
    window = deals.board(me, limit_per_stage=1)
    assert window["deals_truncated"] is True and len(window["deals"]) == 2
    with pytest.raises(Invalid):
        deals.board(me, after_id=1)
    with pytest.raises(Invalid):
        deals.board(me, limit=1, limit_per_stage=1)


# ── Links, permissions, hooks ─────────────────────────────────────────────────


def test_links_must_exist(me):
    for field in ("person_id", "organization_id", "owner_user_id"):
        with pytest.raises(Invalid, match=field):
            new(me, **{field: 9999})


def test_the_system_principal_reads_but_never_writes(me):
    from backend.core.auth.deps import system_user

    deal = new(me)
    assert deals.get(system_user(), deal["id"])["id"] == deal["id"]
    with pytest.raises(Forbidden):
        deals.update(system_user(), deal["id"], {"title": "x"})


def test_edits_mark_the_deal_dirty_for_the_touch_job(me, people):
    deal = new(me, person_id=people["zoe"])
    with core_db.transaction() as conn:
        conn.execute("UPDATE crm_deals SET touch_dirty = 0")
    deals.update(me, deal["id"], {"notes": "new notes"})
    assert core_db.one("SELECT touch_dirty FROM crm_deals WHERE id = ?", (deal["id"],))["touch_dirty"] == 1
    with core_db.transaction() as conn:
        conn.execute("UPDATE crm_deals SET touch_dirty = 0")
        contacts.update_person_in(conn, me, people["zoe"], title="Owner")
    assert core_db.one("SELECT touch_dirty FROM crm_deals WHERE id = ?", (deal["id"],))["touch_dirty"] == 1


def test_a_person_merge_repoints_deals_and_keeps_the_higher_score(me, people):
    deal = new(me, person_id=people["ada"])
    activity.log(me, "call", person_id=people["ada"])
    with core_db.transaction() as conn:
        conn.executemany(
            "INSERT INTO crm_person_scores (person_id, lead_score, lead_score_at) VALUES (?, ?, ?)",
            [(people["zoe"], 40, NOW), (people["ada"], 75, NOW)],
        )
        contacts.merge_people_in(conn, me, people["zoe"], people["ada"])
    assert deals.get(me, deal["id"])["person_id"] == people["zoe"]
    assert activity.list_(me)[0]["person_id"] == people["zoe"]
    assert scoring.person_scores([people["zoe"], people["ada"]]) == [{"person_id": people["zoe"], "lead_score": 75, "lead_score_at": NOW}]


def test_a_failing_crm_subscriber_rolls_the_core_merge_back(me, people, monkeypatch):
    deal = new(me, person_id=people["ada"])

    def boom(conn, target_id, source_id):
        raise RuntimeError("subscriber failed")

    monkeypatch.setattr(scoring, "merge_people_in", boom)
    with pytest.raises(RuntimeError), core_db.transaction() as conn:
        contacts.merge_people_in(conn, me, people["zoe"], people["ada"])
    assert deals.get(me, deal["id"])["person_id"] == people["ada"]
    assert core_db.one("SELECT merged_into_id FROM core_people WHERE id = ?", (people["ada"],))["merged_into_id"] is None


def test_deleting_a_person_clears_its_score_and_unlinks_its_deals(me, people):
    deal = new(me, person_id=people["ada"])
    with core_db.transaction() as conn:
        conn.execute("INSERT INTO crm_person_scores (person_id, lead_score, lead_score_at) VALUES (?, 50, ?)", (people["ada"], NOW))
        provenance.record_fields_in(conn, "core.person", people["ada"], ["title"])
        entities.delete_record_in(conn, "core.person", people["ada"])
    assert deals.get(me, deal["id"])["person_id"] is None
    assert core_db.rows("SELECT * FROM crm_person_scores") == []
    assert core_db.rows("SELECT * FROM crm_field_provenance") == []


def test_reset_keeps_ids_climbing_and_leaves_nothing_behind(me, people, make_user):
    admin = make_user("admin")
    old = new(me, person_id=people["zoe"])
    timeline.add_note(me, "crm.deal", old["id"], "A private thought about this deal")
    activity.log(me, "call", deal_id=old["id"])
    assert meta.reset(admin) == {"deals": 1, "activity": 1}
    assert core_db.rows("SELECT * FROM crm_deals") == [] and core_db.rows("SELECT * FROM crm_activity_log") == []
    assert len(core_db.rows("SELECT * FROM crm_stage_criteria")) == 6, "reference data is re-seeded"
    assert contacts.get_person(me, people["zoe"])["name"] == "Zoë Démo", "the directory is core's and stays"
    fresh = new(make_user("member"), "A new deal")
    assert fresh["id"] > old["id"]
    assert timeline.list_for(me, "crm.deal", fresh["id"]) == []
    assert core_db.rows("SELECT * FROM core_timeline WHERE entity_type = 'crm.deal' AND entity_id = ?", (old["id"],)) == []
