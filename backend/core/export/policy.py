"""What the admin business-data export may contain: an explicit allow-list, nothing else.

Each entry is `table: {"entity", "columns", "id_column"?, "where"?}`, the same shape as an app's
`seed.EXPORT` (apps name a fixed entity type and may add `id_column`).
- `entity`: the entity type that authorizes each row, or None for no row check. It may name row
  columns in braces, filled from the row: "{entity_type}" (timeline, files), "core.{owner_type}".
- `id_column`: the row column holding that record's id; default "id" (the row is the record).
- `where`: a fixed SQL filter on the table.
A row is exported only when `entities.authorize(read)` passes for the exporting admin.

The full /data backup is the privileged recovery path; this export is what an admin may see.
"""

from __future__ import annotations

_POLY = {"entity": "{entity_type}", "id_column": "entity_id"}  # rows hanging off any record
_OWNER = {"entity": "core.{owner_type}", "id_column": "owner_id"}  # contact rows of a person or organization

CORE_EXPORT: dict[str, dict] = {
    "core_users": {"entity": None, "columns": ["id", "email", "name", "role"]},
    "core_people": {
        "entity": "core.person",
        "columns": [
            "id", "name", "given_name", "family_name", "email", "phone", "title", "source", "status", "tags",
            "notes", "owner_user_id", "archived_at", "merged_into_id", "created_at", "updated_at",
        ],
    },
    "core_organizations": {
        "entity": "core.organization",
        "columns": [
            "id", "name", "domain", "website", "industry", "email", "phone", "notes", "source", "status", "tags",
            "owner_user_id", "archived_at", "merged_into_id", "created_at", "updated_at",
        ],
    },
    "core_person_organizations": {
        "entity": "core.person", "id_column": "person_id",
        "columns": ["id", "person_id", "organization_id", "role", "is_primary", "started_on", "ended_on", "created_at"],
    },
    "core_addresses": {
        **_OWNER,
        "columns": [
            "id", "owner_type", "owner_id", "kind", "line1", "line2", "city", "region", "postal_code", "country",
            "is_primary", "created_at", "updated_at",
        ],
    },
    "core_contact_channels": {
        **_OWNER,
        "columns": ["id", "owner_type", "owner_id", "kind", "value", "label", "is_primary", "created_at", "updated_at"],
    },
    "core_timeline": {
        **_POLY, "where": "kind IN ('note', 'comment')",
        "columns": ["id", "entity_type", "entity_id", "kind", "body", "author_user_id", "created_at", "updated_at", "archived_at"],
    },
    "core_files": {  # metadata only; the bytes stay in the backup
        **_POLY,
        "columns": [
            "id", "entity_type", "entity_id", "timeline_id", "filename", "mime_type", "byte_size", "sha256",
            "uploaded_by", "created_at",
        ],
    },
    # Tables later workstreams add: exported once they exist, with whichever of these columns they have.
    "core_field_definitions": {
        "entity": None,
        "columns": ["id", "entity_type", "key", "label", "type", "options", "position", "created_at", "updated_at"],
    },
    "core_field_values": {
        **_POLY, "columns": ["id", "field_id", "entity_type", "entity_id", "value", "created_at", "updated_at"],
    },
    "core_reminders": {
        **_POLY,
        "columns": [
            "id", "owner_user_id", "entity_type", "entity_id", "title", "note", "due_at", "repeat", "series_id",
            "status", "fired_at", "created_at", "updated_at",
        ],
    },
}

# Never exported, whatever a policy entry says; `check` enforces it on the merged policy.
NEVER_TABLES = frozenset({
    "core_totp", "core_trusted_devices", "core_login_tokens", "core_login_attempts", "core_settings",
    "core_outbox", "core_backups", "core_sheet_cache",
})
NEVER_PREFIXES = ("core_agent_", "core_mcp_")
NEVER_COLUMNS = frozenset({"password_hash", "secret_enc", "backup_codes", "token_hash"})


def check(policy: dict[str, dict]) -> None:
    for table, spec in policy.items():
        if table in NEVER_TABLES or table.startswith(NEVER_PREFIXES):
            raise ValueError(f"export policy names {table!r}, which is never exported")
        if bad := NEVER_COLUMNS & set(spec["columns"]):
            raise ValueError(f"export policy names {table}.{sorted(bad)}, which is never exported")
