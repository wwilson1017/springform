-- The launcher folder an admin files an app under (docs/agents/frontend-shell.md); NULL is the top level.
ALTER TABLE core_apps_state ADD COLUMN folder TEXT;
