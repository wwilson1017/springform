"""The change log: one row per changed field of any entity, for the ChangeLog page and audits.

Rows outlive their record: a delete stamps `deleted_at` instead of removing history, so an id
that later belongs to nothing stays distinguishable. Readers must apply `entities.authorize`
per row (the viewer and `/api/core/changelog` are a later workstream).
"""

from __future__ import annotations

import json
from typing import Any

from backend.core import clock, db


def record_in(
    conn: db.Conn,
    entity_type: str,
    entity_id: int,
    field: str,
    old: Any,
    new: Any,
    user_id: int | None,
    *,
    reason: str | None = None,
    request_id: str | None = None,
) -> int:
    cur = conn.execute(
        """INSERT INTO core_change_log (at, user_id, app, entity, entity_id, field, old, new, reason, request_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            clock.now_iso(), user_id, entity_type.split(".", 1)[0], entity_type, entity_id, field,
            json.dumps(old), json.dumps(new), reason, request_id,
        ),
    )
    return cur.lastrowid


def on_entity_deleted_in(conn: db.Conn, entity_type: str, entity_id: int) -> None:
    conn.execute(
        "UPDATE core_change_log SET deleted_at = ? WHERE entity = ? AND entity_id = ? AND deleted_at IS NULL",
        (clock.now_iso(), entity_type, entity_id),
    )

