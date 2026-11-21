"""Provider errors by class, and what the turn does about each (agent.md §5, "Provider errors and fallback").

`classify` sorts a failed model call into one of `KINDS` from its status, code and text. The
`on_provider_error` hook then: retries a rate limit once per turn after `retry-after` (at most
`RATE_LIMIT_RETRY_CAP_S`); on a context overflow clears older tool results and repeats the same
call once (no finished tool runs again: only the call is repeated); on an overload or outage
switches, for this turn only, to the other enabled provider or else the light model, but never
once a write or external-effect tool has run since the user's message (a second model could
repeat it); and otherwise ends the turn with a plain message naming the model.
"""

from __future__ import annotations

from backend.core.agent import context_shrink, deferred, history, providers, turn_hooks
from backend.core.agent.aio import in_thread
from backend.core.agent.providers import credentials
from backend.core.agent.providers.base import AIProvider
from backend.core.agent.turn_hooks import Fail, Fallback, ProviderFailure, Retry, TurnState

KINDS = ("auth", "billing", "rate_limit", "overloaded", "context_overflow", "model_not_found", "policy", "other")
RATE_LIMIT_RETRY_S = 2.0  # when the provider sends no retry-after
RATE_LIMIT_RETRY_CAP_S = 10.0

_OVERFLOW_TEXT = (
    "prompt is too long",
    "context length",
    "context window",
    "maximum context",
    "input is too long",
    "too many tokens",
)
MESSAGES = {
    "auth": "The AI key for {model} was rejected. An admin can replace it in Settings, AI.",
    "billing": "The AI account behind {model} is out of credit or over its spending limit.",
    "rate_limit": "{model} is rate-limited right now. Try again in a minute.",
    "overloaded": "{model} is overloaded or unreachable right now. Try again in a minute.",
    "context_overflow": "This conversation is too long for {model}. Start a new conversation.",
    "model_not_found": "The AI provider does not know the model {model}. An admin can pick another in Settings, AI.",
    "policy": "{model} declined this request.",
}


def classify(err: ProviderFailure) -> str:
    """One of KINDS; the first rule that matches wins. Billing before rate limit (a spent quota
    comes as a 429), rate limit before overflow (a tokens-per-minute 429 reads like one)."""
    c, m, st = (err.code or "").lower(), err.message.lower(), err.status
    if c in {"insufficient_quota", "billing_error", "billing_not_active", "billing_hard_limit_reached"}:
        return "billing"
    if st == 402 or "credit balance" in m:
        return "billing"
    if st == 429 or c in {"rate_limit_error", "rate_limit_exceeded"}:
        return "rate_limit"
    if st == 413 or c in {"context_length_exceeded", "request_too_large"} or any(t in m for t in _OVERFLOW_TEXT):
        return "context_overflow"
    if c in {"overloaded_error", "api_error", "server_error", "connection_error", "timeout_error"}:
        return "overloaded"
    if st in (408, 500, 502, 503, 504, 529):
        return "overloaded"
    if st in (401, 403) or c in {"authentication_error", "permission_error", "invalid_api_key"}:
        return "auth"
    if st == 404 or c in {"not_found_error", "model_not_found"}:
        return "model_not_found"
    if c in {"content_filter", "content_policy_violation"} or "usage policies" in m:
        return "policy"
    return "other"


def _wrote(state: TurnState) -> bool:
    """A write or external-effect tool ran, or may have, since the user's latest message. A tool no
    longer offered counts as one (never guess a run was harmless)."""
    for run in history.runs_since_user(state.conversation_id):
        if run["status"] not in history.RAN or run["tool"] == deferred.FIND_TOOLS:
            continue
        spec = state.by_name.get(run["tool"])
        if spec is None or spec.writes or spec.external_effect:
            return True
    return False


def _alternative(current: AIProvider) -> AIProvider | None:
    """The other enabled vendor's default model, else this vendor's light model when it differs."""
    for name in credentials.PROVIDERS:
        if name != current.provider_name:
            cand = providers.get_provider(provider=name)
            if cand is not None and cand.provider_name == name:  # usable() falls back to the first usable vendor
                return cand
    cand = providers.get_provider(tier="light", provider=current.provider_name)
    if cand is not None and cand.provider_name == current.provider_name and cand.model != current.model:
        return cand
    return None


async def on_provider_error(state: TurnState, err: ProviderFailure) -> Retry | Fallback | Fail:
    kind, seen = classify(err), state.scratch.setdefault(__name__, {})
    message = MESSAGES.get(kind, "{model}").format(model=state.provider.model)
    if kind == "rate_limit" and not seen.get("rate_retried"):
        seen["rate_retried"] = True
        delay = RATE_LIMIT_RETRY_S if err.retry_after is None else err.retry_after
        return Retry(min(max(delay, 0.0), RATE_LIMIT_RETRY_CAP_S))
    if kind == "context_overflow" and not seen.get("shrunk"):
        seen["shrunk"] = True
        if context_shrink.shrink(state, force=True):
            return Retry(0)
    if kind == "overloaded" and not seen.get("fell_back") and not await in_thread(_wrote, state):
        if (alternative := await in_thread(_alternative, state.provider)) is not None:
            seen["fell_back"] = True  # once per turn, so two failing providers cannot trade it back and forth
            return Fallback(alternative)
    # simplification: an overload is not retried on the same model before falling back or failing;
    # upgrade: one Retry(2) first.
    return Fail(message) if kind != "other" else Fail()


turn_hooks.register("on_provider_error", on_provider_error)
