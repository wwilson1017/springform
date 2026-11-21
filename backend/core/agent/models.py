"""Response models for Whisk's routes. The chat stream (SSE) stays untyped."""

from typing import Any, Literal

from backend.core.platform.models import Out

ToolRunStatus = Literal["pending", "executing", "done", "denied", "error", "stale", "uncertain", "interrupted"]


class ProviderInfo(Out):
    """A model vendor's settings; never carries the key."""

    provider: str
    has_key: bool
    enabled: bool
    model_default: str
    model_light: str
    updated_at: str | None


class AgentModels(Out):
    default: str | None
    light: str | None


class AgentStatus(Out):
    configured: bool
    default_agent: str
    name: str  # the default agent's display name
    providers: list[ProviderInfo]
    models: AgentModels


class ProviderTest(Out):
    ok: bool
    model: str
    reply: str


class AgentRow(Out):
    id: int
    slug: str
    name: str
    personality: str
    provider_override: str | None
    model_override: str | None
    model_tier: Literal["default", "light"]
    is_default: bool
    created_at: str


class Conversation(Out):
    id: int
    user_id: int
    agent_id: int
    agent_slug: str
    title: str
    is_private: bool
    created_at: str
    updated_at: str
    compacted_at: str | None


class ServerToolCall(Out):
    """A tool call the model made, with its run: status and a result capped for display."""

    tool: str
    tool_use_id: str
    args: dict[str, Any]
    tool_run_id: int | None
    status: ToolRunStatus | None
    result: Any
    error: str | None
    can_always_allow: bool = False  # a pending card may offer "Always allow" (engine.rule_eligible)
    batch: str | None = None  # pending cards with the same key share one card (engine.batch_key)
    change_list: bool = False  # the run has a change list (GET /api/agent/change-lists/{tool_run_id})


class ServerMessage(Out):
    id: int
    role: Literal["user", "assistant", "tool"]
    text: str
    tool_calls: list[ServerToolCall]
    model: str | None
    created_at: str


class ConversationDetail(Conversation):
    messages: list[ServerMessage]


class ConversationDeleted(Out):
    deleted: bool


class Intent(Out):
    """A topic reminder (`intents.public`). `status`: active, used_up (every fire spent) or expired."""

    id: int
    terms: list[str]
    note: str
    fires: int
    max_fires: int
    cooldown_hours: int
    last_fired_at: str | None
    expires_at: str
    created_at: str
    status: Literal["active", "used_up", "expired"]


class ConfirmResponse(Out):
    """`result` with "done"; `error` with "error", "uncertain" and a tool no longer offered;
    `current` (the run's status now) with "already_resolved"."""

    status: Literal["done", "denied", "error", "stale", "uncertain", "already_resolved"]
    current: ToolRunStatus | None = None
    result: Any = None
    error: str | None = None
    rule_saved: bool | None = None  # only when the approve asked for always_allow


class ApprovalRule(Out):
    """A live always-allow rule: `tool` skips its card in this user's chats with the agent."""

    id: int
    tool: str
    agent_slug: str
    agent_name: str
    created_at: str


class RuleVoided(Out):
    voided: bool


class ChangeListRow(Out):
    """One field of one record: `old` and `new` as the change log holds them."""

    entity_type: str
    entity_id: int
    title: str
    field: str
    old: Any
    new: Any


class ChangeListSkip(Out):
    entity_type: str
    entity_id: int
    title: str
    reason: str


class ChangeList(Out):
    """A bulk run's changes (agent.md §6). `staged` waits on its card; `not_applied` was denied,
    stale or refused; `reverted`/`skipped` come with `undone`. Records the caller cannot read now
    are left out and counted in `hidden`."""

    tool_run_id: int
    status: Literal["staged", "applied", "undone", "not_applied"]
    rows: list[ChangeListRow]
    notes: list[str]
    hidden: int
    reverted: int | None
    skipped: list[ChangeListSkip]


class TurnCancelled(Out):
    cancelled: bool


class UsageRow(Out):
    """One source and model's calls this month; `unpriced` counts calls on a model with no rate."""

    source: str
    model: str
    calls: int
    input_tokens: int
    output_tokens: int
    cache_read: int
    cache_write: int
    cost_micros: int
    unpriced: int


class UsageMonth(Out):
    month: str  # YYYY-MM in the install timezone
    rows: list[UsageRow]
    cost_micros: int  # priced calls only
    cache_hit_rate: float | None  # cache reads over all input tokens; None with no input yet
