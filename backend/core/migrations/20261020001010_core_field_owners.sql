-- App-declared custom fields (docs/agents/records.md §3): the app that owns a definition, and
-- when that app stopped declaring it (a retired field is archived; declaring it again restores it).
ALTER TABLE core_field_definitions ADD COLUMN owner_app TEXT;   -- app slug; NULL for an admin's field
ALTER TABLE core_field_definitions ADD COLUMN retired_at TEXT;
