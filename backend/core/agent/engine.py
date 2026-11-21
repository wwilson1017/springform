"""Tool gating and server-side confirmation (ported from CakeCRM `assistant/engine.py`).

The turn loop is in `turns.py` (the per-call chain in `dispatch.py`, server ownership of the turn in
`detached.py`). Tools offered are `for_user(user)` ∩ `for_source("chat")`. Every call gets a
tool-run row:
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

import json

from backend.core import db
from backend.core.agent import execute, history, registry as tool_registry
from backend.core.agent.spec import ROUTINE, ToolSpec, tool_def_sha256
from backend.core.auth.deps import User
from backend.core.errors import Forbidden, NotFound

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


# ── Confirmation ──────────────────────────────────────────────────────────────


def _already(run_id: int) -> dict:
    return {"status": "already_resolved", "current": db.must(history.get_tool_run(run_id))["status"]}


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
    out = execute.run_tool(
        user,
        spec,
        json.loads(run["args"]),
        source=run["source"],
        run_id=run["id"],
        conversation_id=run["conversation_id"],
    )
    if out["status"] == "already_resolved":
        return _already(run["id"])
    if out["tainted"]:
        history.mark_tainted(run["conversation_id"])
    if out["status"] == "done":
        return {"status": "done", "result": out["result"]}
    return {"status": out["status"], "error": out["error"]}
