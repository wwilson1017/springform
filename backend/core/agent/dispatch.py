"""One tool call of a turn: refuse it, load deferred tools, gate it for approval, or run it.

Moved unchanged from the engine's per-call chain; the loop is in `turns.py`. Every call gets a
tool-run row, or compaction would see it unsettled forever.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable

from backend.core.agent import deferred, execute, history, turn_hooks
from backend.core.agent.aio import in_thread
from backend.core.agent.engine import needs_confirmation
from backend.core.agent.spec import tool_def_sha256
from backend.core.agent.turn_hooks import TurnState
from backend.core.agent.write_budget import BudgetAction


async def run_call(state: TurnState, emit: Callable[[dict], None], call: dict, message_id: int | None) -> dict:
    """Settle one call and emit its `confirm` or `tool_end`; returns the result entry for the model."""
    call = {**call}  # before_tool may replace "args"; the model's own call (its history) stays as sent
    name, tool_use_id = call["name"], call["id"]
    refusal = None if state.terminated or state.halt else await turn_hooks.before_tool(state, call)
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
    elapsed = 0  # (run_id, status, result for the UI, content for the model) goes in outcome

    if state.terminated:
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
        run_id = await in_thread(history.insert_tool_run, **record, status="done", result=stored)
        outcome = (run_id, "done", result, stored)
    elif spec is None or name not in state.loaded:
        error = f"Tool {name!r} is not loaded; call {deferred.FIND_TOOLS} first." if spec else f"Unknown tool {name!r}."
        outcome = await _refuse(record, error)
    elif spec.writes and (action := state.budget.check_write()) != BudgetAction.ALLOW:
        state.terminated = action == BudgetAction.TERMINATE
        outcome = await _refuse(record, "Write budget exceeded for this turn; not run.")
    elif needs_confirmation(spec, args, state.tainted):
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
            }
        )
        return {"tool_use_id": tool_use_id, "tool_name": name, "content": history.model_content({"status": "pending"})}
    else:
        t0 = time.monotonic()
        run = await in_thread(
            execute.run_tool,
            state.user,
            spec,
            args,
            source="chat",
            conversation_id=state.conversation_id,
            message_id=message_id,
            tool_use_id=tool_use_id,
        )
        elapsed = int((time.monotonic() - t0) * 1000)
        if run["tainted"] and not state.tainted:
            state.tainted = True
            await in_thread(history.mark_tainted, state.conversation_id)
        content = history.model_content({"status": run["status"], "result": run["stored"], "error": run["error"]})
        content = await turn_hooks.on_tool_result(state, call, {**run, "content": content})
        outcome = (run["id"], run["status"], run["result"], content)

    run_id, status, result, content = outcome
    emit(
        {
            "type": "tool_end",
            "tool": name,
            "tool_use_id": tool_use_id,
            "tool_run_id": run_id,
            "status": status,
            "result": result,
            "elapsed_ms": elapsed,
        }
    )
    return {"tool_use_id": tool_use_id, "tool_name": name, "content": content}


async def _refuse(record: dict, error: str):
    run_id = await in_thread(history.insert_tool_run, **record, status="error", error=error)
    return run_id, "error", {"error": error}, json.dumps({"status": "error", "error": error})
