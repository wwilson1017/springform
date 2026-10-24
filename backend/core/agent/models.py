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


class ConfirmResponse(Out):
    """`result` with "done"; `error` with "error", "uncertain" and a tool no longer offered;
    `current` (the run's status now) with "already_resolved"."""

    status: Literal["done", "denied", "error", "stale", "uncertain", "already_resolved"]
    current: ToolRunStatus | None = None
    result: Any = None
    error: str | None = None
