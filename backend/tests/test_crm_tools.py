"""CRM Whisk tools through the live registry and the engine's write path (targets authorized
for write, then handler_in, in one transaction): deal links, provenance badges, open-stage
moves, confirm tiers and the role filters."""

import json

import pytest

from backend.apps.crm import deals, provenance
from backend.core import db as core_db
from backend.core.agent import engine, execute, history, registry
from backend.core.agent.providers import fake
from backend.core.auth.deps import system_user
from backend.core.contacts import api as contacts


@pytest.fixture
def me(app, make_user, freeze):
    freeze("2026-10-14T15:00:00Z")
    return make_user("member")


class Refused(Exception):
    """A tool run that ended in error; the message is the run's error text."""


def call(user, name, **args):
    """Run a tool the way chat approvals and MCP do (execute.run_tool: targets authorized for
    write, then handler_in, in one transaction, and the run recorded)."""
    out = execute.run_tool(user, registry.get(name), args, source="mcp")
    if out["status"] != "done":
        raise Refused(out["error"])
    return out["result"]


def test_the_crm_tools_register_with_the_app_s_roles(me):
    names = {s.name for s in registry.for_user(me)}
    assert {"crm_search_deals", "crm_create_deal", "crm_mark_deal_won", "crm_merge_deals", "crm_today"} <= names
    unattended = {s.name for s in registry.for_source("job") if s.app == "crm"}
    assert "crm_search_deals" in unattended and "crm_create_deal" not in unattended, "jobs get reads only"


def test_only_archive_and_merge_ask_for_approval(me):
    asks = {s.name for s in registry.for_user(me) if s.app == "crm" and engine.needs_confirmation(s, {}, tainted=False)}
    assert asks == {"crm_archive_deal", "crm_merge_deals"}


def test_create_update_and_close_through_the_write_path(me):
    deal = call(me, "crm_create_deal", title="Wedding cakes", value_cents=125_000, stage="proposal")
    assert deal["url"] == f"http://localhost:8000/crm/deals/{deal['id']}"
    badges = provenance.get(me, "crm.deal", deal["id"])["fields"]
    assert set(badges) == {"value_cents", "stage"}, "the AI-written fields are badged; the title the user named is not"
    moved = call(me, "crm_update_deal_stage", deal_id=deal["id"], stage="negotiation")
    assert moved["stage"] == "negotiation"
    with pytest.raises(Refused, match="crm_mark_deal_won"):
        call(me, "crm_update_deal_stage", deal_id=deal["id"], stage="won")
    won = call(me, "crm_mark_deal_won", deal_id=deal["id"], closed_on="2026-10-10")
    assert (won["stage"], won["closed_on"], won["url"].endswith(f"/crm/deals/{deal['id']}")) == ("won", "2026-10-10", True)
    lost = call(me, "crm_mark_deal_lost", deal_id=deal["id"], lost_reason="Budget cut")
    assert lost["lost_reason"] == "Budget cut" and "lost_reason" in provenance.get(me, "crm.deal", deal["id"])["fields"]


def test_bulk_moves_stay_on_open_stages(me):
    ids = [call(me, "crm_create_deal", title=f"Deal {i}")["id"] for i in range(3)]
    out = call(me, "crm_bulk_move_deals", deal_ids=ids, stage="qualified")
    assert (out["ok"], out["updated_ids"]) == (True, ids)
    with pytest.raises(Refused, match="open stage"):
        call(me, "crm_bulk_move_deals", deal_ids=ids, stage="lost")


def test_archive_restore_and_merge(me):
    keep = call(me, "crm_create_deal", title="Wedding cakes")["id"]
    dup = call(me, "crm_create_deal", title="Wedding cakes")["id"]
    call(me, "crm_log_activity", activity="call", note="Left a message", deal_id=dup)
    assert [g["count"] for g in call(me, "crm_find_duplicate_deals")] == [], "no person on either: not a double entry"
    merged = call(me, "crm_merge_deals", target_id=keep, source_id=dup)
    assert merged["id"] == keep and call(me, "crm_get_activity_log", deal_id=keep)[0]["note"] == "Left a message"
    archived = call(me, "crm_archive_deal", deal_id=keep, reason="Test record")
    assert archived["archived_reason"] == "Test record"
    assert call(me, "crm_search_deals", q="wedding") == []
    assert [d["id"] for d in call(me, "crm_search_deals", q="wedding", include_archived=True, bogus="ignored")] == [dup, keep]
    assert call(me, "crm_restore_deal", deal_id=keep)["archived_at"] is None


def test_reads_carry_links_and_lean_analytics(me):
    deal = call(me, "crm_create_deal", title="Wedding cakes", stage="proposal", value_cents=50_000)
    pipeline = call(me, "crm_get_pipeline", limit_per_stage=5)
    assert pipeline["deals"][0]["url"].endswith(f"/crm/deals/{deal['id']}")
    stats = call(me, "crm_analytics", days=30)
    assert "daily" not in str(stats.keys()) and stats["open_deals"] == 1 and stats["total_pipeline_value_cents"] == 50_000
    detail = call(me, "crm_get_deal", deal_id=deal["id"])
    assert detail["url"].endswith(f"/crm/deals/{deal['id']}") and detail["stage_events"][0]["new_stage"] == "proposal"
    health = call(me, "crm_get_deal_health", deal_id=deal["id"])
    assert health["deal"]["url"] and "missing_person" in health["flags"]
    with core_db.transaction() as conn:
        ada = contacts.create_person_in(conn, me, name="Ada Example")["id"]
    assert call(me, "crm_get_lead_score", person_id=ada)["person_id"] == ada
    assert 1 <= call(me, "crm_get_lead_score", deal_id=deal["id"])["score"] <= 99
    with pytest.raises(Refused, match="deal_id or person_id"):
        call(me, "crm_get_lead_score")


def test_the_write_path_authorizes_its_targets(me):
    with pytest.raises(Refused, match="not_found"):
        call(me, "crm_update_deal", deal_id=9999, title="x")
    deal = call(me, "crm_create_deal", title="Wedding cakes")
    with pytest.raises(Refused, match="forbidden"):  # the system principal never writes (core refuses before the handler)
        call(system_user(), "crm_update_deal", deal_id=deal["id"], title="x")
    assert call(system_user(), "crm_get_deal", deal_id=deal["id"])["title"] == "Wedding cakes"


def test_through_chat_mine_reads_inline_and_archive_waits_for_the_owner_s_approval(login_as, monkeypatch):
    monkeypatch.setenv("AGENT_FAKE_PROVIDER", "1")
    fake.reset()
    member, other = login_as("member"), login_as("member")
    mine = deals.create(member.principal, {"title": "Wedding cakes", "owner_user_id": member.principal.id})
    deals.create(member.principal, {"title": "Café order"})

    def turn(client, step):
        fake.script(step, "Done.")
        r = client.post("/api/agent/chat", json={"message": "go"})
        assert r.status_code == 200, r.text
        return [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]

    ends = [e for e in turn(member, {"tool": "crm_search_deals", "args": {"mine": True}}) if e["type"] == "tool_end"]
    assert ends[0]["status"] == "done" and [d["id"] for d in ends[0]["result"]] == [mine["id"]]

    evs = turn(member, {"tool": "crm_archive_deal", "args": {"deal_id": mine["id"], "reason": "Created by mistake"}})
    run_id = next(e for e in evs if e["type"] == "confirm")["tool_run_id"]
    assert deals.get(member.principal, mine["id"])["archived_at"] is None, "nothing happens before approval"
    assert other.post("/api/agent/confirm", json={"tool_run_id": run_id, "decision": "approve"}).status_code == 403
    done = member.post("/api/agent/confirm", json={"tool_run_id": run_id, "decision": "approve"}).json()
    assert done["status"] == "done" and done["result"]["archived_reason"] == "Created by mistake"
    assert history.get_tool_run(run_id)["status"] == "done"
    fake.reset()
