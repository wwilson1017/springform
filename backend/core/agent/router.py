"""Whisk's HTTP API, mounted at /api/agent (ported from CakeCRM `assistant/router.py` minus uploads
and detached turns, plus the provider and agent admin routes).

Conversations are owner-only: another user's conversation answers 404 exactly as a missing one
does. The one exception is POST /confirm, which answers 403 to a non-owner (agent.md §6).
SSE is POST + fetch streaming: `data: {"type": ..., ...}` lines.
"""

from __future__ import annotations

import asyncio
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.core.agent import agents, engine, history, providers
from backend.core.agent.providers import ProviderError, collect_text, credentials
from backend.core.auth.deps import User, current_user, require_admin

router = APIRouter(prefix="/api/agent", tags=["core"])

_RESULT_PREVIEW_CAP = 2000
_SSE_HEADERS = {"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}


class ChatIn(BaseModel):
    conversation_id: int | None = None
    agent_slug: str | None = None
    message: str | None = Field(default=None, max_length=100_000)


class ConfirmIn(BaseModel):
    tool_run_id: int
    decision: Literal["approve", "deny"]


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
    soul: str | None = Field(default=None, max_length=20_000)
    provider_override: Literal["anthropic", "openai"] | None = None
    model_override: str | None = Field(default=None, max_length=200)
    model_tier: Literal["default", "light"] | None = None


# ── Status and chat ───────────────────────────────────────────────────────────


@router.get("/status")
def status(user: User = Depends(current_user)) -> dict:
    s = providers.status()
    return {
        "configured": s["configured"],
        "default_agent": agents.get()["slug"],
        "providers": s["providers"],
        "models": {"default": s["default_model"], "light": s["light_model"]},
    }


@router.post("/chat")
def chat(body: ChatIn, user: User = Depends(current_user)) -> StreamingResponse:
    """SSE stream of one turn. No message + conversation_id = continue after an approval."""
    if not (body.message or "").strip() and body.conversation_id is None:
        raise HTTPException(422, detail="message or conversation_id is required")
    if body.conversation_id is not None:
        conv = history.get_conversation(body.conversation_id, user.id)
        if conv is None:
            raise HTTPException(404, detail="conversation_not_found")
        agent = agents.get_by_id(conv["agent_id"])
    else:
        agent = agents.get(body.agent_slug)
    provider = providers.get_provider(
        tier=agent["model_tier"], provider=agent["provider_override"], model=agent["model_override"],
    )
    if provider is None:
        raise HTTPException(400, detail="no_provider")
    stream = engine.chat(provider, user, body.message, conversation_id=body.conversation_id, agent_slug=agent["slug"])
    return StreamingResponse(stream, media_type="text/event-stream", headers=_SSE_HEADERS)


@router.post("/confirm")
def confirm(body: ConfirmIn, user: User = Depends(current_user)) -> dict:
    return engine.confirm(user, body.tool_run_id, body.decision)


# ── Conversations ─────────────────────────────────────────────────────────────


@router.get("/conversations")
def list_conversations(q: str | None = None, limit: int = 50, offset: int = 0, user: User = Depends(current_user)) -> list[dict]:
    return history.list_conversations(user.id, q=q, limit=limit, offset=offset)


@router.post("/conversations")
def create_conversation(body: ConversationIn, user: User = Depends(current_user)) -> dict:
    return history.create_conversation(user.id, agents.get(body.agent_slug)["id"])


def _preview(stored: str | None):
    if stored is None:
        return None
    if len(stored) > _RESULT_PREVIEW_CAP:
        return stored[:_RESULT_PREVIEW_CAP] + "…(truncated)"
    return json.loads(stored)


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: int, user: User = Depends(current_user)) -> dict:
    """The conversation with its messages; each tool call carries its run (status, capped result)."""
    conv = history.get_conversation(conversation_id, user.id)
    if conv is None:
        raise HTTPException(404, detail="conversation_not_found")
    runs: dict[tuple, dict] = {(r["message_id"], r["tool_use_id"]): r for r in history.tool_runs_for(conversation_id)}
    out = []
    for m in history.messages(conversation_id):
        calls = []
        for c in m["content"].get("tool_calls") or []:
            run = runs.get((m["id"], c["tool_use_id"]))
            calls.append({
                **c, "tool_run_id": run and run["id"], "status": run and run["status"],
                "result": _preview(run and run["result"]), "error": run and run["error"],
            })
        out.append({"id": m["id"], "role": m["role"], "text": m["content"].get("text", ""), "tool_calls": calls,
                    "model": m["content"].get("model"), "created_at": m["created_at"]})
    return {**conv, "messages": out}


@router.patch("/conversations/{conversation_id}")
def update_conversation(conversation_id: int, body: ConversationPatch, user: User = Depends(current_user)) -> dict:
    conv = history.update_conversation(conversation_id, user.id, title=body.title, is_private=body.is_private)
    if conv is None:
        raise HTTPException(404, detail="conversation_not_found")
    return conv


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: int, user: User = Depends(current_user)) -> dict:
    if not history.delete_conversation(conversation_id, user.id):
        raise HTTPException(404, detail="conversation_not_found")
    return {"deleted": True}


# ── Agents ────────────────────────────────────────────────────────────────────


@router.get("/agents")
def list_agents(user: User = Depends(current_user)) -> list[dict]:
    return agents.list_agents()


@router.patch("/agents/{slug}")
def update_agent(slug: str, body: AgentPatch, user: User = Depends(require_admin)) -> dict:
    return agents.update(slug, body.model_dump(exclude_unset=True))


# ── Providers (admin) ─────────────────────────────────────────────────────────


def _known(provider: str) -> str:
    if provider not in credentials.PROVIDERS:
        raise HTTPException(404, detail="unknown_provider")
    return provider


@router.get("/providers")
def list_providers(user: User = Depends(require_admin)) -> list[dict]:
    return credentials.list_providers()


@router.put("/providers/{provider}")
def update_provider(provider: str, body: ProviderPatch, user: User = Depends(require_admin)) -> dict:
    """`api_key: ""` removes the key; an omitted field is left as it is. Never returns the key."""
    return credentials.update(_known(provider), **body.model_dump(exclude_unset=True))


@router.post("/providers/{provider}/test")
async def test_provider(provider: str, user: User = Depends(require_admin)) -> dict:
    """One tiny completion with this provider's key and light model; 400 with the provider's message."""
    row = await asyncio.to_thread(credentials.usable, _known(provider))
    if row is None or row["provider"] != provider:
        raise HTTPException(400, detail="no_key")
    client = providers.make(provider, row["api_key"], row["model_light"])
    try:
        reply = await collect_text(client.stream_turn([{"role": "user", "content": "Reply with the word OK."}], [], "Reply briefly.", max_tokens=1024))
    except ProviderError as e:
        raise HTTPException(400, detail=str(e)) from None
    return {"ok": True, "model": row["model_light"], "reply": reply[:200]}
