"""The tool calls of one model step: refuse a call, load deferred tools, gate it for approval, or run it.

`run_calls` settles a step: lookups that need no approval run together first, then every call is
settled in the model's order (`run_call`, the per-call chain moved unchanged from the engine). A
call not yet started when the user has written again is skipped (`SKIPPED`, steering). The
loop is in `turns.py`. Every call gets a tool-run row, or compaction would see it unsettled forever.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable

from backend.core.agent import deferred, execute, history, turn_hooks
from backend.core.agent.aio import in_thread
from backend.core.agent.engine import card_extras, needs_confirmation, rule_skips
from backend.core.agent.spec import tool_def_sha256
from backend.core.agent.turn_hooks import TurnState
from backend.core.agent.write_budget import BudgetAction

MAX_PARALLEL = 4  # lookups of one step running at once
# simplification: a handler past execute.TOOL_TIMEOUT is abandoned in its thread (as one at a time
# always was) and frees its slot, so an abandoned one can still be running beside four; upgrade: a
# process-wide thread cap for handlers.
BATCH_SECONDS = 120  # a lookup that has not started by then is not run
LATE = "Not run: the lookups of this step took too long."
SKIPPED = "Skipped to process your new message."  # a call not yet started when a message came in (steering)
# simplification: the 120 s bounds when a lookup may start; one already running keeps its own
# execute.TOOL_TIMEOUT, so a step's lookups can take 150 s; upgrade: pass the time left as its timeout.


async def run_calls(state: TurnState, emit: Callable[[dict], None], calls: list[dict], message_id: int | None) -> list:
    """Settle the calls of one model step; their result entries, in the model's order. The lookups
    that can run together do so first; then every call is settled in order, so a write runs after
    every lookup of its step and the hooks see the results in call order."""
    calls = [{**c} for c in calls]  # before_tool may replace "args"; the model's own call (its history) stays as sent
    early: dict[int, dict | str] = {}  # by call index: the run of a lookup, or why it was not run
    picked: list[int] = []
    for i in _together(state, calls):  # in call order, before any of them runs
        if state.terminated or state.halt:  # a hook stopped the turn: the rest is refused in order
            break
        if (refusal := await turn_hooks.before_tool(state, calls[i])) is not None:
            early[i] = refusal
        elif not (state.terminated or state.halt):
            picked.append(i)
    gate, deadline = asyncio.Semaphore(MAX_PARALLEL), time.monotonic() + BATCH_SECONDS

    async def one(i: int) -> None:
        async with gate:
            if time.monotonic() >= deadline:
                early[i] = LATE
            else:  # a lookup already running finishes; one still waiting for a slot gives way to a new message
                early[i] = SKIPPED if state.steers else await _run(state, emit, calls[i], message_id)

    async with asyncio.TaskGroup() as group:  # left only when every lookup has ended, also on a cancel
        for i in picked:
            group.create_task(one(i))
    return [await run_call(state, emit, call, message_id, early.get(i)) for i, call in enumerate(calls)]


def _together(state: TurnState, calls: list[dict]) -> list[int]:
    """The calls of a step that run first, together, by index: lookups loaded at the start of the step
    that need no approval, at most one of them from an untrusted source (a second must see the taint
    the first sets, so it keeps its place in the order and asks for approval)."""
    picked, untrusted = [], False
    for i, call in enumerate(calls):
        spec = state.by_name.get(call["name"])
        if spec is None or spec.name not in state.loaded or spec.writes or spec.external_effect:
            continue
        if needs_confirmation(spec, call.get("args") or {}, state.tainted) or (untrusted and spec.untrusted_source):
            continue
        untrusted = untrusted or spec.untrusted_source
        picked.append(i)
    return picked


async def _run(state: TurnState, emit: Callable[[dict], None], call: dict, message_id: int | None) -> dict:
    """Run one ungated call; the taint is marked and its `tool_end` emitted as soon as it returns."""
    t0 = time.monotonic()
    run = await in_thread(
        execute.run_tool,
        state.user,
        state.by_name[call["name"]],
        call.get("args") or {},
        source="chat",
        conversation_id=state.conversation_id,
        message_id=message_id,
        tool_use_id=call["id"],
    )
    elapsed = int((time.monotonic() - t0) * 1000)
    if run["tainted"] and not state.tainted:
        state.tainted = True
        await in_thread(history.mark_tainted, state.conversation_id)
    _tool_end(emit, call, run["id"], run["status"], run["result"], elapsed)
    return run


def _tool_end(emit: Callable[[dict], None], call: dict, run_id: int, status: str, result, elapsed: int = 0) -> None:
    emit(
        {
            "type": "tool_end",
            "tool": call["name"],
            "tool_use_id": call["id"],
            "tool_run_id": run_id,
            "status": status,
            "result": result,
            "elapsed_ms": elapsed,
        }
    )


async def run_call(
    state: TurnState, emit: Callable[[dict], None], call: dict, message_id: int | None, early: dict | str | None = None
) -> dict:
    """Settle one call and emit its `confirm` or `tool_end`; returns the result entry for the model.
    `early` is what `run_calls` already has for a lookup: its run, or why it was not run."""
    name, tool_use_id = call["name"], call["id"]
    if isinstance(early, dict):  # it ran with the step's other lookups: whatever stopped the turn since, it stands
        return await _shown(state, call, early)
    refusal = SKIPPED if early is None and state.steers else early  # not started, and the user wrote again
    if refusal is None and not (state.terminated or state.halt):
        refusal = await turn_hooks.before_tool(state, call)
    args = call.get("args") or {}
    record = {
        "conversation_id": state.conversation_id,
        "message_id": message_id,
        "tool_use_id": tool_use_id,
        "tool": name,
        "args": args,
        "user_id": state.user.id,
    }
    spec = state.by_name.get(name)

    if state.terminated:  # outcome: (run_id, status, result for the UI, content for the model)
        outcome = await _refuse(record, "Not run: the turn stopped at the write budget.")
    elif refusal is not None:
        outcome = await _refuse(record, refusal)
    elif state.halt:
        outcome = await _refuse(record, "Not run: the turn was stopped.")
    elif name == deferred.FIND_TOOLS and state.deferred_specs:
        found = [s for s in deferred.find(args.get("query", ""), state.deferred_specs) if s.name not in state.loaded]
        state.loaded |= {s.name for s in found}
        result = (
            {"loaded": [s.name for s in found]}
            if found
            else {"loaded": [], "note": "No tools matched; try another keyword."}
        )
        stored = json.dumps(result)
        run_id = await in_thread(history.insert_tool_run, **record, status="done", result=stored, records="[]")
        outcome = (run_id, "done", result, stored)
    elif spec is None or name not in state.loaded:
        error = f"Tool {name!r} is not loaded; call {deferred.FIND_TOOLS} first." if spec else f"Unknown tool {name!r}."
        outcome = await _refuse(record, error)
    elif spec.writes and (action := state.budget.check_write()) != BudgetAction.ALLOW:
        state.terminated = action == BudgetAction.TERMINATE
        outcome = await _refuse(record, "Write budget exceeded for this turn; not run.")
    elif needs_confirmation(spec, args, state.tainted) and not await in_thread(
        rule_skips, state.user.id, state.agent["id"], spec, args, state.tainted
    ):  # a live always-allow rule falls through and runs like a routine write
        run_id = await in_thread(
            history.insert_tool_run, **record, tool_def_sha256=tool_def_sha256(spec), status="pending"
        )
        state.pending = True
        emit(
            {
                "type": "confirm",
                "tool_run_id": run_id,
                "tool": name,
                "tool_use_id": tool_use_id,
                "msg_id": message_id,
                "args": args,
                "summary": spec.summary,
                **card_extras(spec, args, state.tainted),
            }
        )
        return {"tool_use_id": tool_use_id, "tool_name": name, "content": history.model_content({"status": "pending"})}
    else:
        return await _shown(state, call, await _run(state, emit, call, message_id))

    run_id, status, result, content = outcome
    _tool_end(emit, call, run_id, status, result)
    return {"tool_use_id": tool_use_id, "tool_name": name, "content": content}


async def _shown(state: TurnState, call: dict, run: dict) -> dict:
    """The result entry of a call that ran: what the model is shown, after the `on_tool_result` hooks."""
    content = history.model_content({"status": run["status"], "result": run["stored"], "error": run["error"]})
    content = await turn_hooks.on_tool_result(state, call, {**run, "content": content})
    return {"tool_use_id": call["id"], "tool_name": call["name"], "content": content}


async def _refuse(record: dict, error: str):
    run_id = await in_thread(history.insert_tool_run, **record, status="error", error=error)
    return run_id, "error", {"error": error}, json.dumps({"status": "error", "error": error})
