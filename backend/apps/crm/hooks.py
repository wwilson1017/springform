"""Subscribers. Each runs inside the caller's transaction: cheap bookkeeping only, and raising
rolls the caller's write back."""

import json

from backend.apps.crm import scoring
from backend.apps.crm.common import ENTITY


def record_changed(conn, entity_type: str, entity_id: int, changes: list[dict], user_id: int | None) -> None:
    """A deal or a linked person changed: its deals' touch counts are stale and their scores
    move. The LLM work happens later, in the crm.touch_count job."""
    if entity_type == ENTITY:
        deal_ids = [entity_id]
    elif entity_type in ("core.person", "core.organization"):
        column = "person_id" if entity_type == "core.person" else "organization_id"
        deal_ids = [r[0] for r in conn.execute(f"SELECT id FROM crm_deals WHERE {column} = ?", (entity_id,))]
    else:
        return
    if deal_ids:
        conn.execute(
            "UPDATE crm_deals SET touch_dirty = 1 WHERE id IN (SELECT value FROM json_each(?))",
            (json.dumps(deal_ids),),
        )
    scoring.refresh_in(conn, deal_ids=deal_ids, person_ids=[entity_id] if entity_type == "core.person" else [])


def merged(conn, entity_type: str, target_id: int, source_id: int) -> None:
    """Two records became one: CRM rows follow the survivor."""
    if entity_type == "core.person":
        conn.execute("UPDATE crm_deals SET person_id = ? WHERE person_id = ?", (target_id, source_id))
        conn.execute("UPDATE crm_activity_log SET person_id = ? WHERE person_id = ?", (target_id, source_id))
        scoring.merge_people_in(conn, target_id, source_id)
    elif entity_type == "core.organization":
        conn.execute("UPDATE crm_deals SET organization_id = ? WHERE organization_id = ?", (target_id, source_id))
    elif entity_type == ENTITY:
        conn.execute("UPDATE crm_activity_log SET deal_id = ? WHERE deal_id = ?", (target_id, source_id))
    else:
        return
    # A badge on the loser's field would describe a record that is gone; the survivor keeps its own.
    conn.execute(
        "DELETE FROM crm_field_provenance WHERE entity_type = ? AND entity_id = ?", (entity_type, source_id)
    )


def deleted(conn, entity_type: str, entity_id: int) -> None:
    """A record is going: drop the CRM rows that only describe it (foreign keys null the links)."""
    if entity_type == "core.person":
        conn.execute("DELETE FROM crm_person_scores WHERE person_id = ?", (entity_id,))
    conn.execute("DELETE FROM crm_field_provenance WHERE entity_type = ? AND entity_id = ?", (entity_type, entity_id))


HOOKS = {
    "on_record_changed": [record_changed],
    "on_entity_merged": [merged],
    "on_entity_deleted": [deleted],
}
