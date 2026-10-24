"""Run one tool call as a user and record it in `core_agent_tool_runs`: the one execution path for
the chat loop's ungated calls, the approval step (`engine.confirm`) and inbound MCP.

- A local write (`handler_in`) runs in ONE transaction: start the run, authorize every
  `targets(args)` record for write, run `handler_in`, resolve the run `done`. A failure rolls all
  of it back and records `error`.
- Everything else (`handler`: reads, external effects) is started (`executing`, targets
  authorized) in one transaction, run outside any transaction with a timeout, and resolved in
  another. An external effect that fails is `uncertain`, since it may have happened; a crash
  leaves `executing`, which startup turns into `interrupted`.

Given `run_id` (an approved pending run), the run is claimed (pending -> executing) instead of
inserted, and one somebody else claimed first comes back `already_resolved` without running.
"""

from __future__ import annotations

import concurrent.futures
import json

from backend.core import db, entities
from backend.core.agent import delimiters, history
from backend.core.agent.spec import ToolSpec, tool_def_sha256
from backend.core.auth.deps import User
from backend.core.errors import AppError

TOOL_TIMEOUT = 30  # seconds for a handler that runs outside a transaction


def error_text(e: Exception) -> str:
    if isinstance(e, AppError):
        return e.detail
    if isinstance(e, concurrent.futures.TimeoutError):
        return f"Timed out after {TOOL_TIMEOUT}s."
    return f"{type(e).__name__}: {e}"[:500]


def dump(spec: ToolSpec, result) -> tuple[str, bool]:
    """(stored result JSON, tainted). An untrusted result is stored fenced, as a JSON string."""
    text = json.dumps(result, default=str)
    if spec.untrusted_source:
        return json.dumps(delimiters.wrap_untrusted_external(spec.name, text)), True
    return text, False


def _authorize_targets_in(conn: db.Conn, spec: ToolSpec, user: User, args: dict) -> None:
    for entity_type, entity_id in spec.targets(args) if spec.targets else []:
        entities.authorize(user, conn, entity_type, int(entity_id), "write")


def _call_with_timeout(spec: ToolSpec, user: User, args: dict):
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(spec.handler, user, args).result(timeout=TOOL_TIMEOUT)
    finally:
        pool.shutdown(wait=False)  # a timed-out handler keeps its thread; its result is dropped


def _outcome(run_id: int, status: str, result=None, stored: str | None = None, error: str | None = None,
             tainted: bool = False) -> dict:
    return {"id": run_id, "status": status, "result": {"error": error} if error else result,
            "stored": stored, "error": error, "tainted": tainted}


def run_tool(user: User, spec: ToolSpec, args: dict, *, source: str, run_id: int | None = None, **record) -> dict:
    """Run `spec` with `args` as `user`. `record` carries the chat columns (conversation_id,
    message_id, tool_use_id) of a new run. Sync (call through asyncio.to_thread from async code).
    Returns {id, status, result, stored, error, tainted}; status is done, error, uncertain, or
    already_resolved (only with run_id)."""

    def start_in(conn: db.Conn) -> int | None:
        if run_id is not None:
            return run_id if history.claim_in(conn, run_id) else None
        return history.insert_tool_run_in(
            conn, **record, tool=spec.name, args=args, user_id=user.id, source=source,
            tool_def_sha256=tool_def_sha256(spec), status="executing",
        )

    def refused(e: Exception) -> dict:  # nothing ran, or it rolled back
        error = error_text(e)
        if run_id is None:
            rid = history.insert_tool_run(
                **record, tool=spec.name, args=args, user_id=user.id, source=source,
                tool_def_sha256=tool_def_sha256(spec), status="error", error=error,
            )
            return _outcome(rid, "error", error=error)
        if history.resolve(run_id, "error", error=error, resolved_by=user.id):
            return _outcome(run_id, "error", error=error)
        return _outcome(run_id, "already_resolved")

    try:
        with db.transaction() as conn:
            rid = start_in(conn)
            if rid is not None:
                _authorize_targets_in(conn, spec, user, args)
                if spec.handler_in is not None:
                    result = spec.handler_in(conn, user, args)
                    stored, tainted = dump(spec, result)
                    history.resolve_in(conn, rid, "done", result=stored, resolved_by=user.id, expect="executing")
    except Exception as e:
        return refused(e)
    if rid is None:
        return _outcome(run_id, "already_resolved")
    if spec.handler_in is not None:
        return _outcome(rid, "done", result, stored, tainted=tainted)

    try:
        result = _call_with_timeout(spec, user, args)
        stored, tainted = dump(spec, result)
    except Exception as e:
        status = "uncertain" if spec.external_effect else "error"
        history.resolve(rid, status, error=error_text(e), resolved_by=user.id, expect="executing")
        return _outcome(rid, status, error=error_text(e))
    history.resolve(rid, "done", result=stored, resolved_by=user.id, expect="executing")
    return _outcome(rid, "done", result, stored, tainted=tainted)
