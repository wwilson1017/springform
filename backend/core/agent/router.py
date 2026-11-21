"""Whisk's HTTP API, mounted at /api/agent (ported from CakeCRM `assistant/router.py` minus uploads,
plus the provider and agent admin routes).

Conversations are owner-only: another user's conversation answers 404 exactly as a missing one
does. The one exception is POST /confirm, which answers 403 to a non-owner (agent.md §6).
SSE is POST + fetch streaming: `data: {"type": ..., ...}` lines. A turn is server-owned
(`detached.py`): a client that drops re-attaches with GET /turns/{id}/events?after=<seq>; a turn
is likewise visible only to the user who started it (404 otherwise).
"""

from __future__ import annotations

import asyncio
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.core.agent import (
    agents,
    approval_rules,
    detached,
    engine,
    history,
    intents,
    models,
    providers,
    registry as tool_registry,
    usage,
)
from backend.core.agent.providers import ProviderError, collect_text, credentials
from backend.core.agent.providers.base import AIProvider
from backend.core.auth.deps import User, current_user, require_admin

router = APIRouter(prefix="/api/agent", tags=["core"])

_RESULT_PREVIEW_CAP = 2000
_SSE_HEADERS = {"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}


class RecordRef(BaseModel):
    entity_type: str = Field(max_length=100, pattern=r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
    entity_id: int = Field(gt=0, le=2**63 - 1)  # SQLite INTEGER; larger would 500, not 422


class ChatIn(BaseModel):
    conversation_id: int | None = None
    agent_slug: str | None = None
    message: str | None = Field(default=None, max_length=100_000)
    # What the user has open; named in the prompt only after authorize(read) (agents.context_note).
    page: str | None = Field(default=None, max_length=300, pattern=r"^/[A-Za-z0-9/_.~%-]*$")
    record: RecordRef | None = None


class ConfirmIn(BaseModel):
    tool_run_id: int
    decision: Literal["approve", "deny"]
    reason: str | None = Field(default=None, max_length=500)  # with deny: told to the model
    always_allow: bool = False  # with approve: save an always-allow rule for this tool


class ConversationIn(BaseModel):
    agent_slug: str | None = None


class ConversationPatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    is_private: bool | None = None


class ProviderPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: str | None = Field(default=None, max_length=8192)
    model_default: str | None = Field(default=None, max_length=200)
    model_light: str | None = Field(default=None, max_length=200)
    enabled: bool | None = None


class AgentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=80)
    personality: str | None = Field(default=None, max_length=20_000)
    provider_override: Literal["anthropic", "openai"] | None = None
    model_override: str | None = Field(default=None, max_length=200)
    model_tier: Literal["default", "light"] | None = None


# ── Status and chat ───────────────────────────────────────────────────────────


@router.get("/status", response_model=models.AgentStatus)
def status(user: User = Depends(current_user)) -> dict:
    s = providers.status()
    agent = agents.get()
    return {
        "configured": s["configured"],
        "default_agent": agent["slug"],
        "name": agent["name"],
        "providers": s["providers"],
        "models": {"default": s["default_model"], "light": s["light_model"]},
    }


def _chat_setup(body: ChatIn, user: User) -> tuple[dict, AIProvider, str]:
    if body.conversation_id is not None:
        conv = history.get_conversation(body.conversation_id, user.id)
        if conv is None:
            raise HTTPException(404, detail="conversation_not_found")
        agent = agents.get_by_id(conv["agent_id"])
    else:
        agent = agents.get(body.agent_slug)
    provider = providers.get_provider(
        tier=agent["model_tier"],
        provider=agent["provider_override"],
        model=agent["model_override"],
    )
    if provider is None:
        raise HTTPException(400, detail="no_provider")
    record = (body.record.entity_type, body.record.entity_id) if body.record else None
    return agent, provider, agents.context_note(user, body.page, record)


@router.post("/chat")
async def chat(body: ChatIn, user: User = Depends(current_user)) -> Response:
    """SSE stream of one server-owned turn. No message + conversation_id = continue after an
    approval (409 `turn_running` while the conversation has a running turn). A message while the
    turn runs is queued on it: 202 `{queued: true, turn_id}`, and the turn shows it to the model
    before its next call (steering, agent.md §5)."""
    if not (body.message or "").strip() and body.conversation_id is None:
        raise HTTPException(422, detail="message or conversation_id is required")
    agent, provider, context = await asyncio.to_thread(_chat_setup, body, user)
    message = (body.message or "").strip() or None
    try:
        stream = await detached.start(
            provider, user, message, conversation_id=body.conversation_id, agent=agent, context=context
        )
    except detached.TurnRunning:
        raise HTTPException(409, detail="turn_running") from None
    if stream is None:
        raise HTTPException(404, detail="conversation_not_found")
    if isinstance(stream, detached.Queued):
        return JSONResponse({"queued": True, "turn_id": stream.turn_id}, status_code=202)
    return StreamingResponse(stream, media_type="text/event-stream", headers=_SSE_HEADERS)


async def _own_turn(turn_id: int, user: User) -> dict:
    turn = await asyncio.to_thread(detached.get_turn, turn_id, user.id)
    if turn is None:
        raise HTTPException(404, detail="turn_not_found")
    return turn


@router.get("/turns/{turn_id}/events")
async def turn_events(
    turn_id: int, after: int = Query(-1, ge=-1), user: User = Depends(current_user)
) -> StreamingResponse:
    """SSE: the turn's events with seq > after, then live ones until it ends. Owner only."""
    turn = await _own_turn(turn_id, user)
    return StreamingResponse(detached.events(turn, after), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.post("/turns/{turn_id}/cancel", response_model=models.TurnCancelled)
async def cancel_turn(turn_id: int, user: User = Depends(current_user)) -> dict:
    """Stop a running turn: it ends with `done` + `stopped` and the status `cancelled`. Owner only;
    `cancelled: false` when it had already ended."""
    return {"cancelled": detached.cancel(await _own_turn(turn_id, user))}


@router.post("/confirm", response_model=models.ConfirmResponse, response_model_exclude_unset=True)
def confirm(body: ConfirmIn, user: User = Depends(current_user)) -> dict:
    """409 `turn_running` while the run's conversation has a turn running: that turn may still be
    making the cards of one step, and a step a new message cuts short skips its whole batch (agent.md §6)."""
    run = history.get_tool_run(body.tool_run_id)
    if run and run["conversation_id"] is not None and detached.running(run["conversation_id"]):
        raise HTTPException(409, detail="turn_running")
    return engine.confirm(user, body.tool_run_id, body.decision, reason=body.reason, always_allow=body.always_allow)


@router.get("/approval-rules", response_model=list[models.ApprovalRule])
def list_approval_rules(user: User = Depends(current_user)) -> list[dict]:
    """The caller's live always-allow rules, newest first."""
    return approval_rules.list_for(user.id)


@router.delete("/approval-rules/{rule_id}", response_model=models.RuleVoided)
def void_approval_rule(rule_id: int, user: User = Depends(current_user)) -> dict:
    """Void the caller's own rule (the row stays, with when and why); 404 otherwise."""
    if not approval_rules.void(rule_id, user.id, "removed in settings"):
        raise HTTPException(404, detail="rule_not_found")
    return {"voided": True}


# ── Conversations ─────────────────────────────────────────────────────────────


@router.get("/conversations", response_model=list[models.Conversation])
def list_conversations(
    q: str | None = None, limit: int = 50, offset: int = 0, user: User = Depends(current_user)
) -> list[dict]:
    return history.list_conversations(user.id, q=q, limit=limit, offset=offset)


@router.post("/conversations", response_model=models.Conversation)
def create_conversation(body: ConversationIn, user: User = Depends(current_user)) -> dict:
    return history.create_conversation(user.id, agents.get(body.agent_slug)["id"])


def _preview(stored: str | None):
    if stored is None:
        return None
    if len(stored) > _RESULT_PREVIEW_CAP:
        return stored[:_RESULT_PREVIEW_CAP] + "…(truncated)"
    return json.loads(stored)


@router.get("/conversations/{conversation_id}", response_model=models.ConversationDetail)
def get_conversation(conversation_id: int, user: User = Depends(current_user)) -> dict:
    """The conversation with its messages; each tool call carries its run (status, capped result)."""
    conv = history.get_conversation(conversation_id, user.id)
    if conv is None:
        raise HTTPException(404, detail="conversation_not_found")
    runs: dict[tuple, dict] = {(r["message_id"], r["tool_use_id"]): r for r in history.tool_runs_for(conversation_id)}
    tainted = bool((history.compaction_state(conversation_id) or {"tainted": 1})["tainted"])
    out = []
    for m in history.messages(conversation_id):
        calls = []
        for c in m["content"].get("tool_calls") or []:
            run = runs.get((m["id"], c["tool_use_id"]))
            calls.append(
                {
                    **c,
                    **(
                        {"args": json.loads(run["args"])} if run and run["args"] else {}
                    ),  # what ran (call_repair may coerce)
                    "tool_run_id": run and run["id"],
                    "status": run and run["status"],
                    "result": _preview(run["result"] if run else None),
                    "error": run and run["error"],
                    **(
                        engine.card_extras(spec, json.loads(run["args"]), tainted, m["id"])
                        if run and run["status"] == "pending" and (spec := tool_registry.get(run["tool"]))
                        else {}
                    ),
                }
            )
        out.append(
            {
                "id": m["id"],
                "role": m["role"],
                "text": m["content"].get("text", ""),
                "tool_calls": calls,
                "model": m["content"].get("model"),
                "created_at": m["created_at"],
            }
        )
    return {**conv, "messages": out}


@router.patch("/conversations/{conversation_id}", response_model=models.Conversation)
def update_conversation(conversation_id: int, body: ConversationPatch, user: User = Depends(current_user)) -> dict:
    conv = history.update_conversation(conversation_id, user.id, title=body.title, is_private=body.is_private)
    if conv is None:
        raise HTTPException(404, detail="conversation_not_found")
    return conv


@router.delete("/conversations/{conversation_id}", response_model=models.ConversationDeleted)
def delete_conversation(conversation_id: int, user: User = Depends(current_user)) -> dict:
    if not history.delete_conversation(conversation_id, user.id):
        raise HTTPException(404, detail="conversation_not_found")
    return {"deleted": True}


# ── Topic reminders ───────────────────────────────────────────────────────────


@router.get("/intents", response_model=list[models.Intent])
def list_intents(user: User = Depends(current_user)) -> list[dict]:
    """The caller's own topic reminders, newest first."""
    return intents.list_mine(user)


@router.delete("/intents/{intent_id}", response_model=models.ConversationDeleted)
def delete_intent(intent_id: int, user: User = Depends(current_user)) -> dict:
    """Another user's reminder answers 404, as a missing one does."""
    intents.delete(user, intent_id)
    return {"deleted": True}


# ── Agents ────────────────────────────────────────────────────────────────────


@router.get("/agents", response_model=list[models.AgentRow])
def list_agents(user: User = Depends(current_user)) -> list[dict]:
    return agents.list_agents()


@router.patch("/agents/{slug}", response_model=models.AgentRow)
def update_agent(slug: str, body: AgentPatch, user: User = Depends(require_admin)) -> dict:
    return agents.update(slug, body.model_dump(exclude_unset=True))


# ── Providers (admin) ─────────────────────────────────────────────────────────


def _known(provider: str) -> str:
    if provider not in credentials.PROVIDERS:
        raise HTTPException(404, detail="unknown_provider")
    return provider


@router.get("/providers", response_model=list[models.ProviderInfo])
def list_providers(user: User = Depends(require_admin)) -> list[dict]:
    return credentials.list_providers()


@router.put("/providers/{provider}", response_model=models.ProviderInfo)
def update_provider(provider: str, body: ProviderPatch, user: User = Depends(require_admin)) -> dict:
    """`api_key: ""` removes the key; an omitted field is left as it is. Never returns the key."""
    return credentials.update(_known(provider), **body.model_dump(exclude_unset=True))


@router.get("/usage", response_model=models.UsageMonth)
def get_usage(user: User = Depends(require_admin)) -> dict:
    """This month's model usage and estimated cost (the usage ledger, agent.md §5)."""
    return usage.month_summary()


@router.post("/providers/{provider}/test", response_model=models.ProviderTest)
async def test_provider(provider: str, user: User = Depends(require_admin)) -> dict:
    """One tiny completion with this provider's key and light model; 400 with the provider's message."""
    row = await asyncio.to_thread(credentials.usable, _known(provider))
    if row is None or row["provider"] != provider:
        raise HTTPException(400, detail="no_key")
    client = providers.make(provider, row["api_key"], row["model_light"])
    try:
        reply = await collect_text(
            usage.metered(
                client.stream_turn(
                    [{"role": "user", "content": "Reply with the word OK."}], [], "Reply briefly.", max_tokens=1024
                ),
                client,
                "test",
            )
        )
    except ProviderError as e:
        raise HTTPException(400, detail=str(e)) from None
    return {"ok": True, "model": row["model_light"], "reply": reply[:200]}
