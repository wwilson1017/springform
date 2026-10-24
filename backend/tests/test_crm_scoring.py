"""Lead scores: the pure composition (bands, clamps, terminals, temperature) and the stored
scores a real database keeps fresh. Behaviour ported from CakeCRM's scoring suite
(docs/PROVENANCE.md)."""

from datetime import UTC, datetime

import pytest

from backend.apps.crm import activity, deals, scoring
from backend.core import clock, db as core_db
from backend.core.contacts import api as contacts
from backend.core.timeline import api as timeline

NOW = datetime(2026, 10, 14, 15, 0, tzinfo=UTC)


def deal(**fields):
    base = {"stage": "lead", "created_at": "2026-10-10T00:00:00Z", "value_cents": 0, "person_id": None,
            "organization_id": None, "deal_temperature": None}  # fmt: skip
    return {**base, **fields}


def person(**fields):
    return {"status": "active", "email": "", "phone": "", "created_at": "2026-10-01T00:00:00Z", **fields}


# ── Pure composition ──────────────────────────────────────────────────────────


def test_terminal_stages_short_circuit():
    assert scoring.compose_deal(deal(stage="won"), 0, None, NOW)["score"] == 100
    assert scoring.compose_deal(deal(stage="lost"), 50, None, NOW)["score"] == 0


def test_an_open_deal_stays_inside_1_to_99():
    cold = scoring.compose_deal(deal(created_at="2020-01-01T00:00:00Z", deal_temperature="cold"), 0, None, NOW)
    hot = scoring.compose_deal(
        deal(stage="negotiation", value_cents=50_000_000, person_id=1, organization_id=1, deal_temperature="hot"),
        30, "2026-10-14T12:00:00Z", NOW,
    )  # fmt: skip
    assert (cold["score"], hot["score"]) == (1, 99)


@pytest.mark.parametrize("cents, multiplier", [
    (0, 0.7), (-500, 0.7), (1, 0.9), (999_999, 0.9), (1_000_000, 1.05), (4_999_999, 1.05),
    (5_000_000, 1.15), (10_000_000, 1.2),
])  # fmt: skip
def test_value_bands_are_in_cents_and_never_penalise_a_bigger_deal(cents, multiplier):
    assert scoring.compose_deal(deal(value_cents=cents), 0, None, NOW)["factors"]["value"] == multiplier


@pytest.mark.parametrize("count, multiplier", [(0, 0.6), (1, 0.9), (2, 0.9), (3, 1.05), (6, 1.15), (11, 1.25)])
def test_engagement_bands(count, multiplier):
    assert scoring.compose_deal(deal(), count, None, NOW)["factors"]["engagement"] == multiplier


@pytest.mark.parametrize("last_touch, multiplier", [
    ("2026-10-14T00:00:00Z", 1.1), ("2026-10-02T00:00:00Z", 1.05), ("2026-09-20T00:00:00Z", 1.0),
    ("2026-08-20T00:00:00Z", 0.85), ("2026-07-20T00:00:00Z", 0.7), ("2026-01-01T00:00:00Z", 0.5),
    ("2027-01-01T00:00:00Z", 1.1),
])  # fmt: skip
def test_recency_bands_and_a_future_touch_is_fresh(last_touch, multiplier):
    assert scoring.compose_deal(deal(), 1, last_touch, NOW)["factors"]["recency"] == multiplier


def test_recency_falls_back_to_the_creation_day():
    assert scoring.compose_deal(deal(created_at="2026-06-01T00:00:00Z"), 0, None, NOW)["factors"]["recency"] == 0.5


def test_temperature_is_neutral_until_someone_judges_it():
    scores = {t: scoring.compose_deal(deal(stage="proposal", deal_temperature=t), 3, None, NOW)["score"] for t in (None, "hot", "warm", "cold")}
    assert scores["cold"] < scores[None] < scores["warm"] < scores["hot"]
    a = scoring.compose_deal(deal(stage="proposal", deal_temperature="hot", person_id=1), 3, "2026-10-13T00:00:00Z", NOW)
    b = scoring.compose_deal(deal(stage="negotiation", deal_temperature="hot", person_id=1), 3, "2026-10-13T00:00:00Z", NOW)
    assert a["score"] < b["score"] < 99, "two hot deals stay distinguishable below the clamp"


def test_an_unknown_stage_reads_as_lead():
    assert scoring.compose_deal(deal(stage="mystery"), 0, None, NOW)["factors"]["stage_baseline"] == 8


@pytest.mark.parametrize("stages, multiplier", [
    ([], 0.75), (["lost"], 0.65), (["won", "lost"], 1.5), (["lead", "won"], 1.1), (["qualified"], 1.25),
    (["proposal", "lead"], 1.45), (["negotiation", "proposal"], 1.6),
])  # fmt: skip
def test_a_person_s_best_live_deal_lifts_them(stages, multiplier):
    assert scoring.compose_person(person(), 0, None, stages, False, NOW)["factors"]["deal_linkage"] == multiplier


def test_person_factors():
    full = scoring.compose_person(person(email="a@example.com", phone="555-0100"), 4, "2026-10-12T00:00:00Z", ["proposal"], True, NOW)
    bare = scoring.compose_person(person(status="mystery"), 0, None, [], False, NOW)
    assert full["factors"]["profile_completeness"] == 1.1 and bare["factors"]["profile_completeness"] == 0.85
    assert bare["factors"]["status_base"] == 15, "an unknown status reads as inactive"
    assert 1 <= bare["score"] < full["score"] <= 99


# ── Stored scores ─────────────────────────────────────────────────────────────


@pytest.fixture
def me(app, make_user, freeze):
    freeze("2026-10-14T15:00:00Z")
    return make_user("member")


def stored(deal_id):
    return core_db.one("SELECT lead_score, lead_score_at, updated_at FROM crm_deals WHERE id = ?", (deal_id,))


def test_writes_keep_scores_fresh_without_touching_updated_at(me, freeze):
    d = deals.create(me, {"title": "Wedding cakes", "stage": "proposal"})
    first = stored(d["id"])
    assert first["lead_score"] is not None and first["lead_score_at"] == "2026-10-14T15:00:00Z"
    freeze("2026-10-14T16:00:00Z")
    for _ in range(3):
        activity.log(me, "call", deal_id=d["id"])
    after = stored(d["id"])
    assert after["lead_score"] > first["lead_score"] and after["updated_at"] == "2026-10-14T15:00:00Z"
    deals.mark_won(me, d["id"])
    assert stored(d["id"])["lead_score"] == 100


def test_notes_on_the_timeline_count_as_engagement(me):
    d = deals.create(me, {"title": "Wedding cakes"})
    before = scoring.deal_breakdown_in(core_db.get_conn(), d["id"])["factors"]["engagement"]
    timeline.add_note(me, "crm.deal", d["id"], "They liked the samples")
    assert scoring.deal_breakdown_in(core_db.get_conn(), d["id"])["factors"]["engagement"] > before


def test_a_person_is_scored_with_their_deal_and_rescored_when_it_moves_away(me):
    with core_db.transaction() as conn:
        ada = contacts.create_person_in(conn, me, name="Ada Example", email="ada@example.com")["id"]
        zoe = contacts.create_person_in(conn, me, name="Zoë Démo")["id"]
    d = deals.create(me, {"title": "Wedding cakes", "stage": "negotiation", "person_id": ada})
    linked = scoring.person_scores([ada])[0]["lead_score"]
    deals.update(me, d["id"], {"person_id": zoe})
    assert scoring.person_scores([ada])[0]["lead_score"] < linked, "the old person lost the deal's lift"
    assert scoring.person_scores([zoe])[0]["lead_score"] > 0


def test_the_refresh_job_rescores_the_stalest_rows_and_skips_scored_terminals(me, freeze):
    open_deal = deals.create(me, {"title": "Open"})
    won = deals.create(me, {"title": "Won", "stage": "won"})
    freeze("2026-10-14T18:00:00Z")
    assert scoring.refresh() == {"deals": 0, "people": 0}, "everything was scored within the day"
    freeze("2026-12-14T18:00:00Z")
    out = scoring.refresh()
    assert out["deals"] == 1
    assert stored(open_deal["id"])["lead_score_at"] == "2026-12-14T18:00:00Z"
    assert stored(won["id"])["lead_score_at"] == "2026-10-14T15:00:00Z"
    assert core_db.one("SELECT scores_refreshed_at FROM crm_meta")["scores_refreshed_at"] == clock.now_iso()


def test_backfill_scores_every_live_deal_and_person(me):
    d = deals.create(me, {"title": "Wedding cakes"})
    with core_db.transaction() as conn:
        conn.execute("UPDATE crm_deals SET lead_score = NULL, lead_score_at = NULL")
        contacts.create_person_in(conn, me, name="Ada Example")
    assert scoring.backfill() == {"deals": 1, "people": 1}
    assert stored(d["id"])["lead_score"] is not None
