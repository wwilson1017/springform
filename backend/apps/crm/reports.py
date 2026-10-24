"""Reports for core's registry (GET /api/core/reports) and the organization rollup.
Ported in part from CakeCRM's crm/report_service.py (docs/PROVENANCE.md). Every report applies
the deal entity's can_read row by row."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from backend.apps.crm import activity, deals
from backend.apps.crm.common import ENTITY, LIVE
from backend.core import db, entities
from backend.core.contacts import api as contacts
from backend.core.reports.registry import Report

if TYPE_CHECKING:
    from backend.core.auth.deps import User


def _readable(user, conn, rows) -> list:
    entity = entities.get(ENTITY)
    return [r for r in rows if entity.can_read(user, conn, r["id"])]


def pipeline_by_stage(params: dict, user) -> tuple[list[str], list[list]]:
    conn = db.get_conn()
    rows = _readable(user, conn, conn.execute(f"SELECT d.id, d.stage, d.value_cents FROM crm_deals d WHERE {LIVE}").fetchall())
    totals: dict[str, list[int]] = {}
    for r in rows:
        t = totals.setdefault(r["stage"], [0, 0])
        t[0] += 1
        t[1] += r["value_cents"]
    order = ("lead", "qualified", "proposal", "negotiation", "won", "lost")
    return ["stage", "deals", "value_cents"], [[s, *totals[s]] for s in order if s in totals]


def won_deals(params: dict, user) -> tuple[list[str], list[list]]:
    """Deals won between two install-local days (closed_on), inclusive."""
    conn = db.get_conn()
    rows = conn.execute(
        f"""SELECT d.id, d.title, d.closed_on, d.value_cents, d.currency, o.name AS organization, u.name AS owner
              FROM crm_deals d LEFT JOIN core_organizations o ON o.id = d.organization_id
              LEFT JOIN core_users u ON u.id = d.owner_user_id
             WHERE {LIVE} AND d.stage = 'won' AND d.closed_on BETWEEN ? AND ? ORDER BY d.closed_on, d.id""",
        (params.get("start") or "0000-01-01", params.get("end") or "9999-12-31"),
    ).fetchall()
    columns = ["id", "title", "closed_on", "value_cents", "currency", "organization", "owner"]
    return columns, [[r[c] for c in columns] for r in _readable(user, conn, rows)]


def organization_rollup(user: User, organization_id: int) -> dict:
    """One organization's people, deals, money and recent activity."""
    conn = db.get_conn()
    org = contacts.get_organization_in(conn, user, organization_id)
    if "merged_into" in org:
        organization_id, org = org["merged_into"], contacts.get_organization_in(conn, user, org["merged_into"])
    org_deals = deals.for_record_in(conn, user, "core.organization", organization_id)
    open_deals = [d for d in org_deals if d["status"] == "open"]
    deal_ids = [d["id"] for d in org_deals]
    recent = conn.execute(
        f"{activity.SELECT} WHERE a.deal_id IN (SELECT value FROM json_each(?)) ORDER BY a.created_at DESC, a.id DESC LIMIT 20",
        (json.dumps(deal_ids),),
    )
    last = max((d["last_activity_at"] for d in org_deals if d["last_activity_at"]), default=None)
    return {
        "organization_id": organization_id, "name": org["name"], "people": org.get("people", []), "deals": org_deals,
        "open_deals": len(open_deals), "open_value_cents": sum(d["value_cents"] for d in open_deals),
        "won_value_cents": sum(d["value_cents"] for d in org_deals if d["status"] == "won"),
        "last_activity_at": last, "recent_activity": [dict(r) for r in recent],
    }


_RANGE = {
    "type": "object",
    "properties": {
        "start": {"type": "string", "format": "date", "title": "From"},
        "end": {"type": "string", "format": "date", "title": "To"},
    },
    "required": [],
}
REPORTS = [
    Report(key="crm.pipeline_by_stage", label="Pipeline by stage", app="crm", run=pipeline_by_stage),
    Report(key="crm.won_deals", label="Won deals", app="crm", run=won_deals, params=_RANGE),
]
