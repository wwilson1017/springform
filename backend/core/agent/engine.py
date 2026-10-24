"""The turn loop and server-side confirmation (ported from CakeCRM `assistant/engine.py`).

`chat()` streams one turn as SSE: resolve or create the conversation, save the user message,
compact if needed, assemble the history from the database, then loop: call the provider,
forward text and tool events, persist the iteration, run or gate each tool call, and go again
until the model stops or a write waits for approval.

Tools offered are `for_user(user)` ∩ `for_source("chat")`. Every call gets a tool-run row:
- reads run at once through `handler(user, args)`, outside any transaction;
- a write that does not need confirmation (routine tier, clean turn, no hiding args) runs
  `handler_in` inside one transaction after `entities.authorize(..., "write")` on every target;
- anything else is stored `pending` and announced with a `confirm` event. The user approves out
  of band (`confirm()`, behind POST /api/agent/confirm) and the client resumes by posting
  /api/agent/chat with the conversation id and no message (a continuation).

Results of `untrusted_source` tools are fenced as data and taint the conversation: from then on
every write confirms, routine ones included. Never a provider call inside `transaction()`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator

from backend.core import db
from backend.core.agent import (
    agents,
    assembly,
    compaction,
    deferred,
    delimiters,
    execute,
    history,
    registry as tool_registry,
)
from backend.core.agent.providers.base import AIProvider, sse
from backend.core.agent.providers.windows import cache_inclusive_input_tokens, context_usage_event
from backend.core.agent.spec import ROUTINE, ToolSpec, tool_def_sha256
from backend.core.agent.write_budget import BudgetAction, BudgetState
from backend.core.auth.deps import User
from backend.core.errors import Forbidden, NotFound

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 20
CONTINUATION_ACK = "Please continue based on the results shown above."


# ── Tool plumbing shared by the loop and confirm ──────────────────────────────


def chat_tools(user: User) -> list[ToolSpec]:
    reg = tool_registry.current()
    allowed = {s.name for s in reg.for_source("chat")}
    return [s for s in reg.for_user(user) if s.name in allowed]


def needs_confirmation(spec: ToolSpec, args: dict, tainted: bool) -> bool:
    """always_confirm, or a write unless it is routine, local, the turn is clean and these args
    do not hide a record. Fails closed when hides_when itself fails."""
    if spec.always_confirm:
        return True
    if not spec.writes:
        return False
    if spec.external_effect or tainted or spec.confirm_tier != ROUTINE:
        return True
    try:
        return bool(spec.hides_when and spec.hides_when(args))
    except Exception:
        return True


def _last_user_text(messages: list[dict]) -> str | None:
    """The newest genuinely typed user text (memory matching never uses fenced or synthetic text)."""
    for m in reversed(messages):
        if m.get("role") != "user":
            continue
        content = m.get("content")
        texts = [content] if isinstance(content, str) else [
            b.get("text") for b in content if isinstance(b, dict) and b.get("type") == "text"
        ] if isinstance(content, list) else []
        for text in reversed(texts):
            text = delimiters.strip_conversation_summary(text or "").strip()
            if text and text != CONTINUATION_ACK and delimiters.UNTRUSTED_EXTERNAL_MARKER not in text:
                return text
    return None


# ── The turn ──────────────────────────────────────────────────────────────────


async def chat(
    provider: AIProvider, user: User, message: str | None, *,
    conversation_id: int | None = None, agent_slug: str | None = None,
) -> AsyncGenerator[str, None]:
    """Stream one turn as SSE lines. No message plus a conversation id is a continuation (resume
    after an approval). The response has already started, so any crash still ends with `error`."""
    try:
        async for line in _chat(provider, user, (message or "").strip() or None, conversation_id, agent_slug):
            yield line
    except Exception:
        logger.exception("agent chat crashed mid-stream")
        yield sse({"type": "error", "error": "The assistant hit an unexpected error and stopped."})


def _start(user: User, message: str | None, conversation_id: int | None, agent_slug: str | None):
    """Resolve or create the conversation and save the user row. None when not this user's."""
    if conversation_id is not None:
        conv = history.get_conversation(conversation_id, user.id)
        if conv is None:
            return None
        agent = agents.get_by_id(conv["agent_id"])
    else:
        agent = agents.get(agent_slug)
    title = None
    with db.transaction() as conn:
        cid = conversation_id if conversation_id is not None else history.create_conversation_in(conn, user.id, agent["id"])
        if message:
            history.save_message_in(conn, cid, "user", {"text": message})
            title = history.auto_title_in(conn, cid, message)
    return cid, agent, title


async def _chat(provider, user, message, conversation_id, agent_slug) -> AsyncGenerator[str, None]:
    if message is None and conversation_id is None:
        yield sse({"type": "error", "error": "Cannot continue without a conversation."})
        return
    started = await asyncio.to_thread(_start, user, message, conversation_id, agent_slug)
    if started is None:
        yield sse({"type": "error", "error": "Conversation not found."})
        return
    cid, agent, title = started
    yield sse({"type": "conversation_id", "id": cid})
    if title:
        yield sse({"type": "title_update", "conversation_id": cid, "title": title})
    if await compaction.maybe_compact(provider, cid):
        yield sse({"type": "compacted", "conversation_id": cid})

    msgs = await asyncio.to_thread(assembly.assemble_messages, provider, cid)
    if not msgs:
        yield sse({"type": "error", "error": "No conversation content to send."})
        return
    state = await asyncio.to_thread(history.compaction_state, cid)
    tainted = bool(state and state["tainted"]) or assembly.has_untrusted(msgs)
    query = _last_user_text(msgs)
    if msgs[-1]["role"] == "assistant":  # a resumed turn can end on the wrap-up narration
        msgs.append({"role": "user", "content": CONTINUATION_ACK})

    from backend.core import registry as app_registry  # imports this package; resolve at call time

    specs = chat_tools(user)
    by_name = {s.name: s for s in specs}
    active, deferred_specs, catalog = deferred.split(specs, {a.slug: a.manifest.name for a in app_registry.installed()})
    loaded = {s.name for s in active}

    def provider_tools() -> list[dict]:
        tools = [s.provider_def() for s in specs if s.name in loaded]
        return tools + ([deferred.FIND_TOOLS_DEF] if deferred_specs else [])

    system = await asyncio.to_thread(assembly.system_prompt, agent, user, query=query, catalog=catalog)
    budget = BudgetState()

    for _ in range(MAX_ITERATIONS):
        text, calls, stop, usage, native, completed = "", [], None, {}, None, False
        async for event in provider.stream_turn(msgs, provider_tools(), system):
            etype = event.get("type")
            if etype == "text":
                text += event["text"]
                yield sse({"type": "text", "text": event["text"]})
            elif etype == "tool_start":
                yield sse({"type": "tool_start", "tool": event["tool"], "tool_use_id": event["tool_use_id"]})
            elif etype == "tool_args":
                spec = by_name.get(event["tool"])
                yield sse({
                    "type": "tool_args", "tool": event["tool"], "tool_use_id": event["tool_use_id"],
                    "args": event.get("args", {}), "description": spec.description if spec else "",
                })
            elif etype == "error":
                yield sse({"type": "error", "error": str(event.get("error") or "Provider error")[:500]})
                return
            elif etype == "_turn_complete":
                calls, stop = event.get("tool_calls") or [], event.get("stop_reason")
                usage, native, completed = event.get("usage") or {}, event.get("assistant_content"), True
                break
        if not completed:
            yield sse({"type": "error", "error": "The model response ended unexpectedly."})
            return
        if meter := context_usage_event(usage, provider.context_window):
            yield sse(meter)

        persisted = [{"tool": c["name"], "tool_use_id": c["id"], "args": c.get("args") or {}} for c in calls]
        message_id = None
        if text or persisted:
            content = {"text": text, "model": provider.model, **({"tool_calls": persisted} if persisted else {})}
            try:
                message_id = await asyncio.to_thread(
                    history.save_message, cid, "assistant", content,
                    tokens_in=cache_inclusive_input_tokens(usage), tokens_out=usage.get("output_tokens"),
                )
            except Exception:
                logger.warning("could not save the assistant iteration", exc_info=True)
                if persisted:  # never run or confirm a tool call that is not recorded
                    yield sse({"type": "error", "error": "Failed to save the assistant turn."})
                    return

        if stop != "tool_use" or not calls:
            yield sse({"type": "done", "model": provider.model})
            await asyncio.to_thread(assembly.after_turn, cid)
            return

        results: list[dict] = []
        pending = terminated = False
        for call in calls:
            name, tool_use_id, args = call["name"], call["id"], call.get("args") or {}
            record = {"conversation_id": cid, "message_id": message_id, "tool_use_id": tool_use_id,
                      "tool": name, "args": args, "user_id": user.id}
            spec = by_name.get(name)
            elapsed = 0  # (run_id, status, result for the UI, content for the model) goes in outcome

            if terminated:  # every call gets a run, or compaction would see it unsettled forever
                outcome = await _refuse(record, "Not run: the turn stopped at the write budget.")
            elif name == deferred.FIND_TOOLS and deferred_specs:
                found = [s for s in deferred.find(args.get("query", ""), deferred_specs) if s.name not in loaded]
                loaded |= {s.name for s in found}
                result = {"loaded": [s.name for s in found]} if found else {"loaded": [], "note": "No tools matched; try another keyword."}
                stored = json.dumps(result)
                run_id = await asyncio.to_thread(history.insert_tool_run, **record, status="done", result=stored)
                outcome = (run_id, "done", result, stored)
            elif spec is None or name not in loaded:
                error = f"Tool {name!r} is not loaded; call {deferred.FIND_TOOLS} first." if spec else f"Unknown tool {name!r}."
                outcome = await _refuse(record, error)
            elif spec.writes and (action := budget.check_write()) != BudgetAction.ALLOW:
                terminated = action == BudgetAction.TERMINATE
                outcome = await _refuse(record, "Write budget exceeded for this turn; not run.")
            elif needs_confirmation(spec, args, tainted):
                run_id = await asyncio.to_thread(
                    history.insert_tool_run, **record, tool_def_sha256=tool_def_sha256(spec), status="pending",
                )
                results.append({"tool_use_id": tool_use_id, "tool_name": name, "content": history.model_content({"status": "pending"})})
                pending = True
                yield sse({
                    "type": "confirm", "tool_run_id": run_id, "tool": name, "tool_use_id": tool_use_id,
                    "msg_id": message_id, "args": args, "description": spec.description,
                })
                continue
            else:
                t0 = time.monotonic()
                run = await asyncio.to_thread(
                    execute.run_tool, user, spec, args, source="chat",
                    conversation_id=cid, message_id=message_id, tool_use_id=tool_use_id,
                )
                if run["tainted"] and not tainted:
                    tainted = True
                    await asyncio.to_thread(history.mark_tainted, cid)
                content = history.model_content({"status": run["status"], "result": run["stored"], "error": run["error"]})
                outcome = (run["id"], run["status"], run["result"], content)
                elapsed = int((time.monotonic() - t0) * 1000)

            run_id, status, result, content = outcome
            results.append({"tool_use_id": tool_use_id, "tool_name": name, "content": content})
            yield sse({
                "type": "tool_end", "tool": name, "tool_use_id": tool_use_id, "tool_run_id": run_id,
                "status": status, "result": result, "elapsed_ms": elapsed,
            })

        msgs = msgs + provider.build_tool_turn(text, calls, results, native=native)
        if terminated:
            yield sse({"type": "done", "model": provider.model})
            await asyncio.to_thread(assembly.after_turn, cid)
            return
        if pending:
            async for line in _wrap_up(provider, cid, msgs, provider_tools(), system):
                yield line
            await asyncio.to_thread(assembly.after_turn, cid)
            return
    yield sse({"type": "error", "error": "Tool loop exceeded maximum iterations."})


async def _refuse(record: dict, error: str):
    run_id = await asyncio.to_thread(history.insert_tool_run, **record, status="error", error=error)
    return run_id, "error", {"error": error}, json.dumps({"status": "error", "error": error})


async def _wrap_up(provider, cid: int, msgs: list[dict], tools: list[dict], system) -> AsyncGenerator[str, None]:
    """One narration turn so the model says what is waiting for approval. Tools are still passed
    (Anthropic rejects tool_use history without them); any tool call it makes is ignored."""
    text = ""
    async for event in provider.stream_turn(msgs, tools, system):
        if event["type"] == "text":
            text += event["text"]
            yield sse({"type": "text", "text": event["text"]})
        elif event["type"] == "error":
            yield sse({"type": "error", "error": str(event.get("error") or "Provider error")[:500]})
            return
        elif event["type"] == "_turn_complete":
            usage = event.get("usage") or {}
            if meter := context_usage_event(usage, provider.context_window, meter_only=True):
                yield sse(meter)
            if text.strip():
                await asyncio.to_thread(
                    history.save_message, cid, "assistant", {"text": text, "model": provider.model},
                    tokens_in=cache_inclusive_input_tokens(usage),
                )
            yield sse({"type": "done", "model": provider.model})
            return
    yield sse({"type": "error", "error": "The model response ended unexpectedly."})


# ── Confirmation ──────────────────────────────────────────────────────────────


def _already(run_id: int) -> dict:
    return {"status": "already_resolved", "current": history.get_tool_run(run_id)["status"]}


def _finish(run_id: int, status: str, user: User, error: str | None = None) -> dict:
    if not history.resolve(run_id, status, error=error, resolved_by=user.id):
        return _already(run_id)
    return {"status": status, **({"error": error} if error else {})}


def confirm(user: User, tool_run_id: int, decision: str) -> dict:
    """Approve or deny a pending tool run. Idempotent: a second call returns
    {"status": "already_resolved", "current": <status>} and nothing runs twice.

    (a) the approver must own the conversation (Forbidden); (b) the tool must still be offered
    to them; (c) its tool_def_sha256 must match the live registry, else `stale`; (d)
    `execute.run_tool` claims the row and runs it with the args stored in the database: a local
    write claims, authorizes every target and runs handler_in in one transaction; a handler-form
    tool (external effect, or a read that always confirms) is claimed in one transaction, run
    outside it, resolved in another; an external effect that fails or times out is `uncertain`."""
    run = history.get_tool_run(tool_run_id)
    if run is None or run["conversation_id"] is None or run["source"] != "chat":
        raise NotFound("tool run not found")
    if history.owner_of(run["conversation_id"]) != user.id:
        raise Forbidden("not_your_conversation")
    if run["status"] != "pending":
        return _already(run["id"])
    if decision == "deny":
        return _finish(run["id"], "denied", user)

    spec = tool_registry.get(run["tool"])
    if spec is None or spec.name not in {s.name for s in chat_tools(user)}:
        return _finish(run["id"], "error", user, "This tool is no longer available to you.")
    if tool_def_sha256(spec) != run["tool_def_sha256"]:
        return _finish(run["id"], "stale", user)
    out = execute.run_tool(user, spec, json.loads(run["args"]), source=run["source"], run_id=run["id"])
    if out["status"] == "already_resolved":
        return _already(run["id"])
    if out["tainted"]:
        history.mark_tainted(run["conversation_id"])
    if out["status"] == "done":
        return {"status": "done", "result": out["result"]}
    return {"status": out["status"], "error": out["error"]}
