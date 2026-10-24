"""Field provenance: which fields Whisk wrote, so the UI shows an AI badge until a person
confirms the value or edits it. Ported from CakeCRM's crm/provenance_service.py
(docs/PROVENANCE.md).

A row ties the badge to the value as written (`value_snapshot`, the stored column value as
text). The badge is live while the row is unconfirmed and the snapshot still equals the
field's current value, so a person's edit retires it without anyone touching this table. Every
AI write resets confirmation, even of an identical value."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core import clock, db, entities
from backend.core.errors import Invalid

if TYPE_CHECKING:
    from backend.core.auth.deps import User

FIELDS = {
    "crm.deal": ("crm_deals", {"title", "stage", "value_cents", "notes", "probability", "expected_close", "lost_reason", "closed_on", "deal_temperature"}),
    "core.person": ("core_people", {"email", "phone", "title", "tags", "notes"}),
}


def _kind(entity_type: str) -> tuple[str, set[str]]:
    if entity_type not in FIELDS:
        raise Invalid(f"provenance covers {', '.join(FIELDS)}")
    return FIELDS[entity_type]


def _text(value) -> str | None:
    return None if value is None else str(value)


def _current_in(conn: db.Conn, entity_type: str, entity_id: int) -> dict:
    table, fields = _kind(entity_type)
    row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (entity_id,)).fetchone()
    return {f: _text(row[f]) for f in fields} if row else {}


def record_fields_in(conn: db.Conn, entity_type: str, entity_id: int, field_names) -> None:
    """After an AI write: badge these fields at their current values (unknown names ignored)."""
    _, allowed = _kind(entity_type)
    current, now = _current_in(conn, entity_type, entity_id), clock.now_iso()
    for name in set(field_names) & allowed:
        conn.execute(
            """INSERT INTO crm_field_provenance (entity_type, entity_id, field_name, value_snapshot, source, populated_at)
               VALUES (?, ?, ?, ?, 'assistant', ?)
               ON CONFLICT (entity_type, entity_id, field_name) DO UPDATE SET
                   value_snapshot = excluded.value_snapshot, source = excluded.source,
                   populated_at = excluded.populated_at, confirmed_at = NULL, confirmed_by = NULL""",
            (entity_type, entity_id, name, current.get(name), now),
        )


def _live_in(conn: db.Conn, entity_type: str, entity_id: int) -> dict:
    current = _current_in(conn, entity_type, entity_id)
    rows = conn.execute(
        "SELECT * FROM crm_field_provenance WHERE entity_type = ? AND entity_id = ? AND confirmed_at IS NULL",
        (entity_type, entity_id),
    )
    return {
        r["field_name"]: {"source": r["source"], "populated_at": r["populated_at"], "value_snapshot": r["value_snapshot"]}
        for r in rows if r["field_name"] in current and current[r["field_name"]] == r["value_snapshot"]
    }


def get(user: User, entity_type: str, entity_id: int) -> dict:
    conn = db.get_conn()
    _kind(entity_type)
    entities.authorize(user, conn, entity_type, entity_id, "read")
    return {"entity_type": entity_type, "entity_id": entity_id, "fields": _live_in(conn, entity_type, entity_id)}


def confirm(user: User, entity_type: str, entity_id: int, fields: list[str] | None = None) -> dict:
    """A person vouches for the badged values (all of them, or `fields`)."""
    _kind(entity_type)
    with db.transaction() as conn:
        entities.authorize(user, conn, entity_type, entity_id, "write")
        names = set(_live_in(conn, entity_type, entity_id))
        if fields is not None:
            names &= set(fields)
        conn.executemany(
            """UPDATE crm_field_provenance SET confirmed_at = ?, confirmed_by = ?
                WHERE entity_type = ? AND entity_id = ? AND field_name = ?""",
            [(clock.now_iso(), user.id, entity_type, entity_id, n) for n in names],
        )
        return {"entity_type": entity_type, "entity_id": entity_id, "fields": _live_in(conn, entity_type, entity_id)}
