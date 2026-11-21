-- Fewer approval clicks (agent.md §2, §6): a person's always-allow rules, and the reason a
-- denied tool run was given. Rules are voided, never deleted; one live rule per user, agent and tool.
CREATE TABLE core_agent_approval_rules (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES core_users(id),
    agent_id    INTEGER NOT NULL REFERENCES core_agents(id),
    tool        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    voided_at   TEXT,
    void_reason TEXT
);
CREATE UNIQUE INDEX core_agent_approval_rules_live
    ON core_agent_approval_rules (user_id, agent_id, tool) WHERE voided_at IS NULL;

ALTER TABLE core_agent_tool_runs ADD COLUMN deny_reason TEXT;
