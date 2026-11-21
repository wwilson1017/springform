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
import logging

from backend.core import db
from backend.core.agent import approval_rules, execute, history, registry as tool_registry
from backend.core.agent.spec import ROUTINE, ToolSpec, tool_def_sha256
from backend.core.auth.deps import User
from backend.core.errors import Forbidden, NotFound

logger = logging.getLogger(__name__)

# ── Tool plumbing shared by the loop and confirm ──────────────────────────────


def chat_tools(user: User, source: tool_registry.Source = "chat") -> list[ToolSpec]:
    reg = tool_registry.current()
    allowed = {s.name for s in reg.for_source(source)}
    return [s for s in reg.for_user(user) if s.name in allowed]


def needs_confirmation(spec: ToolSpec, args: dict, tainted: bool) -> bool:
    """always_confirm; an untrusted read (web search, page read) once the turn is tainted; or a write
    unless it is routine, local, the turn is clean and these args do not hide a record. Fails closed
    when hides_when itself fails."""
    if spec.always_confirm:
        return True
    if not spec.writes:  # an untrusted read reaches outside: once tainted, its args could carry data out
        return tainted and spec.untrusted_source
    if spec.external_effect or tainted or spec.confirm_tier != ROUTINE:
        return True
    try:
        return bool(spec.hides_when and spec.hides_when(args))
    except Exception:
        return True


def rule_eligible(spec: ToolSpec, args: dict, tainted: bool) -> bool:
    """May a saved always-allow rule skip this call's card, and may its card offer to save one: a
    local write that changes records inside the install, in a clean turn. Never an always-ask tool
    (so never a remote one), an outside effect, a destructive write, or a call whose `hides_when`
    fired (or raised)."""
    # simplification: remote tools are never eligible (there is no trusted-server setting for the
    # issue's "except trusted-server reads" to bind to); upgrade: a trusted flag per MCP server.
    if tainted or not spec.writes or spec.always_confirm or spec.remote or spec.external_effect or spec.destructive:
        return False
    try:
        return not (spec.hides_when and spec.hides_when(args))
    except Exception:
        return False


def rule_skips(user_id: int, agent_id: int, spec: ToolSpec, args: dict, tainted: bool) -> bool:
    """A live rule covers this call. Fails closed: a lookup that raises keeps the card."""
    try:
        return rule_eligible(spec, args, tainted) and approval_rules.live(user_id, agent_id, spec.name)
    except Exception:
        logger.warning("approval rule lookup failed; keeping the card", exc_info=True)
        return False


def card_extras(spec: ToolSpec, args: dict, tainted: bool) -> dict:
    """What an Approve card needs beyond the run, on the `confirm` event and the conversation read."""
    return {"can_always_allow": rule_eligible(spec, args, tainted)}


# ── Confirmation ──────────────────────────────────────────────────────────────


def _already(run_id: int) -> dict:
    return {"status": "already_resolved", "current": db.must(history.get_tool_run(run_id))["status"]}


def _finish(run_id: int, status: str, user: User, error: str | None = None, deny_reason: str | None = None) -> dict:
    if not history.resolve(run_id, status, error=error, resolved_by=user.id, deny_reason=deny_reason):
        return _already(run_id)
    return {"status": status, **({"error": error} if error else {})}


def confirm(
    user: User, tool_run_id: int, decision: str, *, reason: str | None = None, always_allow: bool = False
) -> dict:
    """Approve or deny a pending tool run. Idempotent: a second call returns
    {"status": "already_resolved", "current": <status>} and nothing runs twice. A deny may carry
    `reason` (the model reads it). An approve with `always_allow` saves a rule for the tool once it
    ran `done`, only if `rule_eligible` holds for the conversation now; the answer then carries
    `rule_saved`.

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
        reason = " ".join((reason or "").split())[: history.MAX_DENY_REASON] or None
        return _finish(run["id"], "denied", user, deny_reason=reason)

    spec = tool_registry.get(run["tool"])
    if spec is None or spec.name not in {s.name for s in chat_tools(user)}:
        return _finish(run["id"], "error", user, "This tool is no longer available to you.")
    if tool_def_sha256(spec) != run["tool_def_sha256"]:
        return _finish(run["id"], "stale", user)
    args = json.loads(run["args"])
    conv = db.one("SELECT agent_id, tainted FROM core_agent_conversations WHERE id = ?", (run["conversation_id"],))
    wanted = always_allow and conv is not None and rule_eligible(spec, args, bool(conv["tainted"]))
    out = execute.run_tool(
        user,
        spec,
        args,
        source=run["source"],
        run_id=run["id"],
        conversation_id=run["conversation_id"],
    )
    if out["status"] == "already_resolved":
        return _already(run["id"])
    if out["tainted"]:
        history.mark_tainted(run["conversation_id"])
    if out["status"] == "done":
        done = {"status": "done", "result": out["result"]}
        return (
            {**done, "rule_saved": wanted and _save_rule(user, db.must(conv)["agent_id"], spec)}
            if always_allow
            else done
        )
    return {"status": out["status"], "error": out["error"]}


def _save_rule(user: User, agent_id: int, spec: ToolSpec) -> bool:
    """The run already happened, so a failure to save only answers False."""
    try:
        approval_rules.create(user.id, agent_id, spec.name)
        return True
    except Exception:
        logger.warning("could not save the always-allow rule", exc_info=True)
        return False
