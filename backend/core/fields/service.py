"""Custom fields: admin-defined extra fields on any registered entity, and their values.

Definitions are admin-managed and never deleted: DELETE archives one, which hides it and its
values until it is restored. Values are read after `entities.authorize(read)` and written after
`authorize(write)`. Every change goes through `timeline.record_changes_in` with before/after keyed
`field.<key>`, so the timeline, the change log and the on_record_changed hooks all see it.

A value is stored as JSON. Per type:
  text         a string, at most 10,000 characters
  number       a JSON number (finite; not a boolean)
  boolean      true or false
  date         "YYYY-MM-DD"
  select       one of the definition's options
  multiselect  a list of distinct options
  url          an http:// or https:// URL, at most 2,048 characters
  user         the id of an active user
Writing null, "" or [] clears a value, and a cleared value has no row, so "non-empty" means
"has a row" (the merge rule relies on this). `required` is advisory: the UI shows it, the
server does not enforce it.
"""

from __future__ import annotations

import json
import math
import re
from datetime import date
from typing import TYPE_CHECKING, Any

from backend.core import clock, db, entities
from backend.core.errors import Conflict, Forbidden, Invalid, NotFound
from backend.core.timeline import api as timeline

if TYPE_CHECKING:
    from backend.core.auth.deps import User

TYPES = ("text", "number", "boolean", "date", "select", "multiselect", "url", "user")
MAX_LABEL, MAX_OPTIONS, MAX_OPTION, MAX_TEXT, MAX_URL, MAX_WRITE = 100, 100, 200, 10_000, 2048, 200
EXPECTED = {
    "text": f"text of at most {MAX_TEXT} characters",
    "number": "a number",
    "boolean": "true or false",
    "date": "a date (YYYY-MM-DD)",
    "select": "one of the field's options",
    "multiselect": "a list of distinct options",
    "url": "an http(s) URL",
    "user": "the id of an active user",
}
_KEY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_URL = re.compile(r"^https?://[^\s/?#]+\S*$")
_COLUMNS = "id, entity_type, key, label, type, options, required, position, archived_at, created_at, updated_at"


# ── Definitions ───────────────────────────────────────────────────────────────


def _definition(row) -> dict:
    d = dict(row)
    d["options"] = json.loads(d["options"]) if d["options"] else None
    d["required"] = bool(d["required"])
    return d


def _get_in(conn: db.Conn, definition_id: int) -> dict:
    row = conn.execute(f"SELECT {_COLUMNS} FROM core_field_definitions WHERE id = ?", (definition_id,)).fetchone()
    if row is None:
        raise NotFound()
    return _definition(row)


def _require_admin(user: User) -> None:
    if not user.is_admin:
        raise Forbidden("admin_only")


def _label(value: Any) -> str:
    label = (value or "").strip()
    if not label or len(label) > MAX_LABEL:
        raise Invalid(f"label: 1 to {MAX_LABEL} characters")
    return label


def _options(field_type: str, options: list | None) -> str | None:
    """JSON-encoded options: required (1..100 distinct, non-blank) for select and multiselect,
    refused for every other type."""
    if field_type not in ("select", "multiselect"):
        if options:
            raise Invalid("options: only select and multiselect fields have options")
        return None
    cleaned = [str(o).strip() for o in options or []]
    if not 1 <= len(cleaned) <= MAX_OPTIONS or any(not o or len(o) > MAX_OPTION for o in cleaned):
        raise Invalid(f"options: 1 to {MAX_OPTIONS} options of 1 to {MAX_OPTION} characters")
    if len(set(cleaned)) != len(cleaned):
        raise Invalid("options: must be distinct")
    return json.dumps(cleaned)


def list_definitions_in(conn: db.Conn, entity_type: str, include_archived: bool = False) -> list[dict]:
    """An entity type's definitions in display order. Any member may list them."""
    entities.get(entity_type)
    archived = "" if include_archived else " AND archived_at IS NULL"
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM core_field_definitions WHERE entity_type = ?{archived} ORDER BY position, id",
        (entity_type,),
    )
    return [_definition(r) for r in rows]


def list_definitions(entity_type: str, include_archived: bool = False) -> list[dict]:
    return list_definitions_in(db.get_conn(), entity_type, include_archived)


def create_definition_in(conn: db.Conn, user: User, data: dict) -> dict:
    """data: entity_type, label, type, and optionally key (derived from the label when absent),
    options, required, position (default: after the last). Admin only. entity_type, key and type
    never change afterwards."""
    _require_admin(user)
    entity_type, field_type = data.get("entity_type"), data.get("type")
    entities.get(entity_type)
    if field_type not in TYPES:
        raise Invalid(f"type: one of {', '.join(TYPES)}")
    label = _label(data.get("label"))
    key = data.get("key") or re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    if not _KEY.match(key):
        raise Invalid("key: lowercase letters, digits and underscores, starting with a letter, at most 64")
    options = _options(field_type, data.get("options"))
    if conn.execute("SELECT 1 FROM core_field_definitions WHERE entity_type = ? AND key = ?", (entity_type, key)).fetchone():
        raise Conflict("duplicate_key")  # archived definitions keep their key
    position = data.get("position")
    if position is None:
        position = conn.execute(
            "SELECT COALESCE(MAX(position), 0) + 10 FROM core_field_definitions WHERE entity_type = ?", (entity_type,)
        ).fetchone()[0]
    now = clock.now_iso()
    cur = conn.execute(
        """INSERT INTO core_field_definitions
           (entity_type, key, label, type, options, required, position, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (entity_type, key, label, field_type, options, int(bool(data.get("required"))), int(position), now, now),
    )
    return _get_in(conn, cur.lastrowid)


def create_definition(user: User, data: dict) -> dict:
    with db.transaction() as conn:
        return create_definition_in(conn, user, data)


def update_definition_in(conn: db.Conn, user: User, definition_id: int, data: dict) -> dict:
    """Change any of label, options, required, position, archived (false restores). Admin only."""
    _require_admin(user)
    current = _get_in(conn, definition_id)
    sets: dict[str, Any] = {}
    if "label" in data:
        sets["label"] = _label(data["label"])
    if "options" in data:
        sets["options"] = _options(current["type"], data["options"])
    if "required" in data:
        sets["required"] = int(bool(data["required"]))
    if "position" in data:
        sets["position"] = int(data["position"])
    if "archived" in data:
        sets["archived_at"] = (current["archived_at"] or clock.now_iso()) if data["archived"] else None
    if sets:
        assignments = ", ".join(f"{k} = ?" for k in sets)  # keys are this function's own
        conn.execute(
            f"UPDATE core_field_definitions SET {assignments}, updated_at = ? WHERE id = ?",
            (*sets.values(), clock.now_iso(), definition_id),
        )
    return _get_in(conn, definition_id)


def update_definition(user: User, definition_id: int, data: dict) -> dict:
    with db.transaction() as conn:
        return update_definition_in(conn, user, definition_id, data)


def archive_definition_in(conn: db.Conn, user: User, definition_id: int) -> dict:
    return update_definition_in(conn, user, definition_id, {"archived": True})


def archive_definition(user: User, definition_id: int) -> dict:
    with db.transaction() as conn:
        return archive_definition_in(conn, user, definition_id)


# ── Values ────────────────────────────────────────────────────────────────────


def _values_in(conn: db.Conn, entity_type: str, entity_id: int) -> dict[str, Any]:
    rows = conn.execute(
        """SELECT d.key, v.value FROM core_field_values v
           JOIN core_field_definitions d ON d.id = v.definition_id
           WHERE v.entity_type = ? AND v.entity_id = ? AND d.archived_at IS NULL
           ORDER BY d.position, d.id""",
        (entity_type, entity_id),
    )
    return {r["key"]: json.loads(r["value"]) for r in rows}


def _is_date(value: Any) -> bool:
    try:
        return isinstance(value, str) and bool(_DATE.match(value)) and bool(date.fromisoformat(value))
    except ValueError:
        return False


def _valid_in(conn: db.Conn, definition: dict, value: Any) -> bool:
    t = definition["type"]
    if t == "text":
        return isinstance(value, str) and len(value) <= MAX_TEXT
    if t == "number":
        return type(value) is int or (type(value) is float and math.isfinite(value))
    if t == "boolean":
        return isinstance(value, bool)
    if t == "date":
        return _is_date(value)
    if t == "url":
        return isinstance(value, str) and len(value) <= MAX_URL and bool(_URL.match(value))
    if t == "user":
        return type(value) is int and conn.execute(
            "SELECT 1 FROM core_users WHERE id = ? AND is_active = 1 AND role != 'system'", (value,)
        ).fetchone() is not None
    options = json.loads(definition["options"] or "[]")
    if t == "select":
        return isinstance(value, str) and value in options
    return isinstance(value, list) and all(isinstance(v, str) and v in options for v in value) and len(set(value)) == len(value)


def values_for_in(conn: db.Conn, user: User, entity_type: str, entity_id: int) -> dict[str, Any]:
    """{key: value} of the record's set values (archived definitions left out)."""
    entities.authorize(user, conn, entity_type, entity_id, "read")
    return _values_in(conn, entity_type, entity_id)


def values_for(user: User, entity_type: str, entity_id: int) -> dict[str, Any]:
    return values_for_in(db.get_conn(), user, entity_type, entity_id)


def set_values_in(conn: db.Conn, user: User, entity_type: str, entity_id: int, values: dict[str, Any]) -> dict[str, Any]:
    """Set some of a record's values ({key: value}; null, "" or [] clears) and return all of
    them. All or nothing: an unknown or archived key, or a value of the wrong type, changes
    nothing. Changed values are reported through timeline.record_changes_in."""
    entities.authorize(user, conn, entity_type, entity_id, "write")
    if len(values) > MAX_WRITE:
        raise Invalid(f"values: at most {MAX_WRITE} per write")
    definitions = {
        r["key"]: dict(r)
        for r in conn.execute(
            "SELECT id, key, type, options FROM core_field_definitions WHERE entity_type = ? AND archived_at IS NULL",
            (entity_type,),
        )
    }
    if unknown := sorted(set(values) - set(definitions)):
        raise Invalid(f"unknown field: {', '.join(unknown)}")
    clean = {k: None if v in (None, "", []) else v for k, v in values.items()}
    for key, value in clean.items():
        if value is not None and not _valid_in(conn, definitions[key], value):
            raise Invalid(f"{key}: expected {EXPECTED[definitions[key]['type']]}")
    before = _values_in(conn, entity_type, entity_id)
    now = clock.now_iso()
    for key, value in clean.items():
        if value == before.get(key):
            continue
        params = (entity_type, entity_id, definitions[key]["id"])
        if value is None:
            conn.execute("DELETE FROM core_field_values WHERE entity_type = ? AND entity_id = ? AND definition_id = ?", params)
        else:
            conn.execute(
                """INSERT INTO core_field_values (entity_type, entity_id, definition_id, value, updated_at, updated_by)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT (entity_type, entity_id, definition_id)
                   DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at, updated_by = excluded.updated_by""",
                (*params, json.dumps(value), now, user.id),
            )
    timeline.record_changes_in(
        conn, entity_type, entity_id,
        {f"field.{k}": before.get(k) for k in clean}, {f"field.{k}": v for k, v in clean.items()}, user.id,
    )
    return _values_in(conn, entity_type, entity_id)


def set_values(user: User, entity_type: str, entity_id: int, values: dict[str, Any]) -> dict[str, Any]:
    with db.transaction() as conn:
        return set_values_in(conn, user, entity_type, entity_id, values)


# ── Hooks (sync, in the caller's transaction) ────────────────────────────────


def on_entity_deleted_in(conn: db.Conn, entity_type: str, entity_id: int) -> None:
    conn.execute("DELETE FROM core_field_values WHERE entity_type = ? AND entity_id = ?", (entity_type, entity_id))


def on_entity_merged_in(conn: db.Conn, entity_type: str, target_id: int, source_id: int) -> None:
    """The target's non-empty value wins, else the source's. Empty values have no row, so the
    source's rows move unless the target already has that field; the rest are dropped."""
    # simplification: values moved by a merge get no field_change row (hooks carry no user);
    # the merge's own system timeline row covers it. Upgrade: pass the actor through the hook.
    conn.execute(
        "UPDATE OR IGNORE core_field_values SET entity_id = ? WHERE entity_type = ? AND entity_id = ?",
        (target_id, entity_type, source_id),
    )
    conn.execute("DELETE FROM core_field_values WHERE entity_type = ? AND entity_id = ?", (entity_type, source_id))
