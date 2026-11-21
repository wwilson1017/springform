-- The records a stored tool result names (docs/agents/authorization.md §5): JSON [[entity_type, id], ...]
-- from the tool's `reads`, rechecked against the run's user every time the result is shown again.
-- '[]' names none; NULL is a run that did not end done, or one stored before this column (filled at startup).
ALTER TABLE core_agent_tool_runs ADD COLUMN records TEXT;
