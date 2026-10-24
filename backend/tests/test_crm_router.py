"""The /api/crm routes through TestClient: status codes, role guards, request validation and the
shapes the CRM frontend builds against."""

import pytest

from backend.apps.crm import provenance
from backend.core import db as core_db


@pytest.fixture
def admin(login_as, freeze):
    freeze("2026-10-14T15:00:00Z")
    return login_as("admin")


@pytest.fixture
def member(admin, login_as):
    return login_as("member")


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def a_person(client, name="Zoë Démo"):
    return ok(client.post("/api/core/contacts/people", json={"name": name}))["id"]


def test_signed_out_is_401(client):
    assert client.get("/api/crm/deals").status_code == 401


def test_deal_routes(member):
    person = a_person(member)
    deal = ok(member.post("/api/crm/deals", json={"title": "Wedding cakes", "value_cents": 125_000, "person_id": person}))
    assert (deal["status"], deal["person_name"], deal["value_cents"]) == ("open", "Zoë Démo", 125_000)
    did = deal["id"]

    assert ok(member.patch(f"/api/crm/deals/{did}", json={"stage": "proposal", "deal_temperature": "hot"}))["stage"] == "proposal"
    detail = ok(member.get(f"/api/crm/deals/{did}"))
    assert [e["new_stage"] for e in detail["stage_events"]] == ["lead", "proposal"] and detail["activity"] == []
    assert ok(member.post(f"/api/crm/deals/{did}/won", json={"closed_on": "2026-10-01"}))["closed_on"] == "2026-10-01"
    assert ok(member.post(f"/api/crm/deals/{did}/lost", json={"reason": "Budget"}))["lost_reason"] == "Budget"
    assert ok(member.post(f"/api/crm/deals/{did}/archive", json={"reason": "Done"}))["archived_reason"] == "Done"
    assert member.patch(f"/api/crm/deals/{did}", json={"stage": "lead"}).status_code == 409
    assert ok(member.post(f"/api/crm/deals/{did}/restore"))["archived_at"] is None

    other = ok(member.post("/api/crm/deals", json={"title": "Second"}))["id"]
    assert ok(member.post(f"/api/crm/deals/{did}/merge", json={"source_id": other}))["id"] == did
    assert ok(member.get(f"/api/crm/deals/{other}"))["archived_reason"] == f"Merged into deal #{did}"
    assert [e["new_stage"] for e in ok(member.get(f"/api/crm/deals/{did}/stage-events"))] == ["lead", "proposal", "won", "lost"]
    assert [d["id"] for d in ok(member.get(f"/api/crm/people/{person}/deals"))] == [did]
    assert [d["title"] for d in ok(member.get("/api/crm/deals/search", params={"q": "zoe"}))] == ["Wedding cakes"]

    moved = ok(member.post("/api/crm/deals/bulk-move", json={"ids": [did, 9999], "stage": "qualified"}))
    assert moved == {"ok": True, "updated": 1, "updated_ids": [did], "errors": ["Deal 9999 not found"]}


@pytest.mark.parametrize("body", [
    {},
    {"title": ""},
    {"title": "x", "value_cents": 10.5},
    {"title": "x", "stage": "doing"},
    {"title": "x", "probability": 101},
    {"title": "x", "lost_reason": "not writable"},
    {"title": "x", "expected_close": "next week"},
    {"title": "x", "person_id": 9999},
])  # fmt: skip
def test_invalid_deals_are_422(member, body):
    assert member.post("/api/crm/deals", json=body).status_code == 422


def test_missing_records_are_404(member):
    assert member.get("/api/crm/deals/9999").status_code == 404
    assert member.patch("/api/crm/deals/9999", json={"title": "x"}).status_code == 404
    assert member.post("/api/crm/deals/9999/won", json={}).status_code == 404
    assert member.get("/api/crm/people/9999/deals").status_code == 404
    assert member.get("/api/crm/organizations/9999/rollup").status_code == 404
    assert member.patch("/api/crm/activity/9999", json={"note": "x"}).status_code == 404


def test_activity_routes(member):
    deal = ok(member.post("/api/crm/deals", json={"title": "Wedding cakes"}))["id"]
    row = ok(member.post("/api/crm/activity", json={"activity": "call", "note": "Left a message", "deal_id": deal}))
    assert (row["deal_title"], row["actor_user_id"], row["created_at"]) == ("Wedding cakes", member.user["id"], "2026-10-14T15:00:00Z")
    assert ok(member.patch(f"/api/crm/activity/{row['id']}", json={"note": "Spoke to them"}))["note"] == "Spoke to them"
    assert [a["id"] for a in ok(member.get("/api/crm/activity", params={"deal_id": deal}))] == [row["id"]]
    assert ok(member.get(f"/api/crm/deals/{deal}"))["last_activity_at"] == "2026-10-14T15:00:00Z"
    assert ok(member.delete(f"/api/crm/activity/{row['id']}")) == {"deleted": row["id"]}
    assert member.post("/api/crm/activity", json={"activity": "call", "deal_id": 9999}).status_code == 422


def test_settings_are_admin_only(admin, member):
    assert member.get("/api/crm/settings").status_code == 403
    assert member.patch("/api/crm/settings", json={"stale_days": 3}).status_code == 403
    assert ok(admin.get("/api/crm/settings")) == {"stale_days": 14, "touch_count_enabled": True, "default_currency": "USD"}
    assert ok(admin.patch("/api/crm/settings", json={"stale_days": 3, "default_currency": "EUR"}))["stale_days"] == 3
    assert admin.patch("/api/crm/settings", json={"stale_days": 0}).status_code == 422
    assert ok(member.post("/api/crm/deals", json={"title": "Euro deal"}))["currency"] == "EUR"


def test_stage_criteria(admin, member):
    criteria = ok(member.get("/api/crm/stage-criteria"))
    assert [c["stage"] for c in criteria] == ["lead", "qualified", "proposal", "negotiation", "won", "lost"]
    assert all(c["is_default"] for c in criteria)
    body = {"summary": "Someone asked", "checklist": ["Name captured", "  ", "Source noted"]}
    assert member.put("/api/crm/stage-criteria/lead", json=body).status_code == 403
    edited = ok(admin.put("/api/crm/stage-criteria/lead", json=body))
    assert (edited["checklist"], edited["is_default"]) == (["Name captured", "Source noted"], False)
    assert ok(admin.delete("/api/crm/stage-criteria/lead"))["is_default"] is True
    assert admin.put("/api/crm/stage-criteria/doing", json=body).status_code == 422


def test_provenance_badge_lives_until_a_person_edits_or_confirms(member):
    deal = ok(member.post("/api/crm/deals", json={"title": "Wedding cakes"}))["id"]
    with core_db.transaction() as conn:
        conn.execute("UPDATE crm_deals SET value_cents = 5000, notes = 'from Whisk' WHERE id = ?", (deal,))
        provenance.record_fields_in(conn, "crm.deal", deal, ["value_cents", "notes", "not_a_field"])
    badges = ok(member.get(f"/api/crm/provenance/crm.deal/{deal}"))["fields"]
    assert set(badges) == {"value_cents", "notes"} and badges["value_cents"]["value_snapshot"] == "5000"
    member.patch(f"/api/crm/deals/{deal}", json={"value_cents": 6000})
    assert set(ok(member.get(f"/api/crm/provenance/crm.deal/{deal}"))["fields"]) == {"notes"}, "an edit retires the badge"
    assert ok(member.post(f"/api/crm/provenance/crm.deal/{deal}/confirm", json={}))["fields"] == {}
    assert member.get("/api/crm/provenance/todos.item/1").status_code == 422


def test_reset_is_admin_only_and_needs_the_word(admin, member):
    ok(member.post("/api/crm/deals", json={"title": "Wedding cakes"}))
    assert member.post("/api/crm/reset", json={"confirm": "RESET"}).status_code == 403
    assert admin.post("/api/crm/reset", json={"confirm": "yes"}).status_code == 422
    assert ok(admin.post("/api/crm/reset", json={"confirm": "RESET"})) == {"deals": 1, "activity": 0}
    assert ok(member.get("/api/crm/deals"))["deals"] == []


def test_badge_counts_my_quiet_open_deals(member, freeze):
    me = member.user["id"]
    ok(member.post("/api/crm/deals", json={"title": "Mine", "owner_user_id": me}))
    ok(member.post("/api/crm/deals", json={"title": "Unowned"}))
    ok(member.post("/api/crm/deals", json={"title": "Mine, won", "owner_user_id": me, "stage": "won"}))
    assert ok(member.get("/api/crm/badge"))["count"] == 0
    freeze("2026-11-14T15:00:00Z")
    assert ok(member.get("/api/crm/badge")) == {"count": 1, "label": "Deals needing a touch"}


def test_dashboard_meta_and_reports(member):
    org = ok(member.post("/api/core/contacts/organizations", json={"name": "Demo Café Group"}))["id"]
    ok(member.post("/api/crm/deals", json={"title": "Big", "value_cents": 900_000, "stage": "proposal", "organization_id": org}))
    ok(member.post("/api/crm/deals", json={"title": "Won", "value_cents": 100_000, "stage": "won"}))
    dash = ok(member.get("/api/crm/dashboard"))
    assert (dash["total_pipeline_value_cents"], dash["won_this_month_cents"], dash["total_organizations"]) == (900_000, 100_000, 1)
    assert [d["title"] for d in dash["top_deals"]] == ["Big"]
    assert ok(member.get("/api/crm/meta"))["empty"] is False
    assert ok(member.post("/api/crm/meta/dismiss-onboarding"))["onboarding_dismissed"] is True
    rollup = ok(member.get(f"/api/crm/organizations/{org}/rollup"))
    assert (rollup["open_deals"], rollup["open_value_cents"]) == (1, 900_000)
    keys = {r["key"] for r in ok(member.get("/api/core/reports"))}
    assert {"crm.pipeline_by_stage", "crm.won_deals"} <= keys
    won = ok(member.get("/api/core/reports/crm.won_deals", params={"start": "2026-10-01", "end": "2026-10-31"}))
    assert [row[1] for row in won["rows"]] == ["Won"]
    for path in ("/dashboard/today", "/dashboard/weekly-touches", "/analytics", "/analytics/pipeline", "/stale-deals",
                 "/deals/duplicates", "/touch-count/backfill", "/scores/people?ids=1,2"):  # fmt: skip
        ok(member.get(f"/api/crm{path}"))
