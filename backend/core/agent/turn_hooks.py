"""Hook points in Whisk's turn loop (agent.md §5, "Hook points").

Five named points, each a list of callables run in registration order. A core module registers
at import (`turn_hooks.register("before_tool", fn)`) and is imported on the `# hook modules` line
in `turns.py`. A hook is `def` or `async def`; it runs on the event loop, so a `def` hook must not
block (database work goes through `aio.in_thread`). A hook that raises ends the turn with the
generic `error` event. Tests swap a list with `monkeypatch.setitem(turn_hooks.REGISTERED, point, [fn])`.

This is not `hooks.py`: a core package's `hooks.py` `HOOKS` dict is entity-event subscriptions
(`registry.install`).
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from backend.core.agent.providers.base import AIProvider
from backend.core.agent.spec import ToolSpec
from backend.core.agent.write_budget import BudgetState
from backend.core.auth.deps import User

POINTS = ("before_model_call", "on_provider_error", "before_tool", "on_tool_result", "end_of_turn")
REGISTERED: dict[str, list[Callable]] = {p: [] for p in POINTS}
MAX_PROVIDER_FAILURES = 3  # per model call: the third failure ends the turn whatever a hook answers


def register(point: str, fn: Callable) -> None:
    """Add `fn` to a point. An unknown point raises (a typo stops boot); a repeat is ignored."""
    if point not in REGISTERED:
        raise ValueError(f"unknown turn hook point {point!r}; one of {POINTS}")
    if fn not in REGISTERED[point]:
        REGISTERED[point].append(fn)


@dataclass(frozen=True)
class Retry:
    """Call the same provider again after `delay` seconds (capped at 30)."""

    delay: float = 0.0


@dataclass(frozen=True)
class Fallback:
    """Use `provider` for the rest of the turn. The messages are rebuilt from the saved
    conversation for it, so in-memory edits made earlier in this turn are dropped."""

    provider: AIProvider


@dataclass(frozen=True)
class Fail:
    """End the turn with `error`: `message`, or the provider's own text when None."""

    message: str | None = None


@dataclass(frozen=True)
class ProviderFailure:
    message: str  # the provider's error text, capped at 500 characters
    attempt: int  # 1 for the first failure of this model call
    status: int | None = None  # the HTTP status, when the provider got one
    retry_after: float | None = None  # seconds, from a Retry-After header
    code: str | None = None  # the provider's error code or type ("overloaded_error", "context_length_exceeded")


@dataclass
class TurnState:
    """One turn's working state, passed to every hook. Fields are added, never renamed.

    Hooks may change `messages`, `system` and `scratch`, and set `halt` to end the turn after this
    tool round; everything else is read-only by convention."""

    user: User
    agent: dict  # the core_agents row
    provider: AIProvider  # replaced only by a Fallback
    conversation_id: int
    turn_id: int
    messages: list[dict] = field(default_factory=list)  # provider-native: what the next model call sends
    system: str | tuple[str, str] = ""
    iteration: int = 0  # 0-based loop iteration
    usage: dict = field(default_factory=dict)  # the last completed model call's usage
    tainted: bool = False
    budget: BudgetState = field(default_factory=BudgetState)
    by_name: dict[str, ToolSpec] = field(default_factory=dict)  # tools offered this turn
    loaded: set[str] = field(default_factory=set)  # tool names the model can call now
    deferred_specs: list[ToolSpec] = field(default_factory=list)
    pending: bool = False  # a call of this iteration waits for approval
    terminated: bool = False  # the write budget ended the turn
    scratch: dict = field(default_factory=dict)  # hooks' own per-turn storage, keyed by module name
    last_text: str = ""  # the latest model call's text, also when the call failed (then never saved)
    stop_reason: str | None = (
        None  # the latest completed call's ("end_turn", "max_tokens", "refusal"…); None after a failure
    )
    error: str | None = None  # the error text, set before end_of_turn on an error ending
    halt: str | None = None  # why the turn was cut short, as a clause for the closing note (a hook, the round limit)


async def _call(fn: Callable, *args: Any) -> Any:
    out = fn(*args)
    return await out if inspect.isawaitable(out) else out


async def before_model_call(state: TurnState) -> None:
    for fn in REGISTERED["before_model_call"]:
        await _call(fn, state)


async def on_provider_error(state: TurnState, err: ProviderFailure) -> Retry | Fallback | Fail:
    """The first non-None answer wins; none at all is `Fail()` (today's behaviour)."""
    for fn in REGISTERED["on_provider_error"]:
        if (action := await _call(fn, state, err)) is not None:
            return action
    return Fail()


async def before_tool(state: TurnState, call: dict) -> str | None:
    """The first non-None string refuses the call with that text. A hook may replace `call["args"]`
    (the run, the Approve card and the handler get the new args; the model's history keeps its own)."""
    for fn in REGISTERED["before_tool"]:
        if (refusal := await _call(fn, state, call)) is not None:
            return refusal
    return None


async def on_tool_result(state: TurnState, call: dict, run: dict) -> str:
    """Chained: each non-None return replaces what the model is shown (`run["content"]`)."""
    content = run["content"]
    for fn in REGISTERED["on_tool_result"]:
        if (new := await _call(fn, state, call, {**run, "content": content})) is not None:
            content = new
    return content


async def end_of_turn(state: TurnState) -> list[dict]:
    """Events to emit, in order, just before the terminal event (`done`, or `error` with `state.error` set)."""
    events: list[dict] = []
    for fn in REGISTERED["end_of_turn"]:
        events.extend(await _call(fn, state) or [])
    return events
