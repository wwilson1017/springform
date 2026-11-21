"""The turn loop (ported from CakeCRM `assistant/engine.py`; agent.md §5).

`TurnRunner(state, emit).run()` drives one turn and hands every event to `emit` (a dict, not SSE
text): compact if needed, assemble the history from the database, then loop: call the provider,
forward text and tool events, persist the iteration, settle the step's tool calls
(`dispatch.run_calls`: lookups together first, then the model's order), and go again until the
model stops or a write waits for approval. It emits exactly one terminal event (`done` or `error`),
last, and raises only on cancel or a bug. `detached.py` owns the task, numbers the events and
streams them. The hook points it calls are in `turn_hooks.py`.

Tools offered are `for_user(user)` ∩ `for_source("chat")`. Results of `untrusted_source` tools
taint the conversation: from then on every write confirms. Never a provider call inside
`transaction()`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from backend.core.agent import (
    assembly,
    call_repair,
    compaction,
    completion_claims,
    context_shrink,
    deferred,
    delimiters,
    dispatch,
    endings,
    errors,
    history,
    intents,
    loop_guard,
    result_cap,
    turn_hooks,
)
from backend.core.agent.aio import in_thread
from backend.core.agent.engine import chat_tools
from backend.core.agent.providers.windows import cache_inclusive_input_tokens, context_usage_event
from backend.core.agent.spec import calling_tainted
from backend.core.agent.turn_hooks import Fallback, ProviderFailure, Retry, TurnState
from backend.core.agent.usage import metered

# hook modules: a module that registers turn hooks is imported here.
HOOK_MODULES = (result_cap, context_shrink, errors, endings, loop_guard, call_repair, completion_claims, intents)

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 20
CONTINUATION_ACK = "Please continue based on the results shown above."
LAST_ANSWER = (
    "You have reached the limit of tool calls for this turn. Do not call any more tools. Answer now "
    "with what you found and what you did, and say plainly what is still unfinished."
)


def _last_user_text(messages: list[dict]) -> str | None:
    """The newest genuinely typed user text (memory matching never uses fenced or synthetic text)."""
    for m in reversed(messages):
        if m.get("role") != "user":
            continue
        content = m.get("content")
        texts = (
            [content]
            if isinstance(content, str)
            else [b.get("text") for b in content if isinstance(b, dict) and b.get("type") == "text"]
            if isinstance(content, list)
            else []
        )
        for text in reversed(texts):
            text = delimiters.strip_conversation_summary(text or "").strip()
            if text and text != CONTINUATION_ACK and delimiters.UNTRUSTED_EXTERNAL_MARKER not in text:
                return text
    return None


class TurnRunner:
    def __init__(self, state: TurnState, emit: Callable[[dict], None], *, title: str | None = None):
        self.state, self.emit, self.title = state, emit, title

    async def run(self) -> None:
        s, emit = self.state, self.emit
        cid = s.conversation_id
        emit({"type": "conversation_id", "id": cid})
        if self.title:
            emit({"type": "title_update", "conversation_id": cid, "title": self.title})
        if await compaction.maybe_compact(s.provider, cid):
            emit({"type": "compacted", "conversation_id": cid})

        s.messages = await self._assemble()
        if not s.messages:
            emit({"type": "error", "error": "No conversation content to send."})
            return
        row = await in_thread(history.compaction_state, cid)
        s.tainted = bool(row and row["tainted"]) or assembly.has_untrusted(s.messages)
        query = _last_user_text(s.messages)

        from backend.core import registry as app_registry  # imports this package; resolve at call time

        specs = chat_tools(s.user)
        s.by_name = {spec.name: spec for spec in specs}
        active, s.deferred_specs, catalog = deferred.split(
            specs, {a.slug: a.manifest.name for a in app_registry.installed()}
        )
        s.loaded = {spec.name for spec in active}
        s.system = await in_thread(
            assembly.system_prompt, s.agent, s.user, query=query, catalog=catalog, context=s.context
        )

        for i in range(MAX_ITERATIONS):
            s.iteration = i
            out = await self._model_call()
            if isinstance(out, str):
                return await self._end(out)
            text, stop = out["text"], out.get("stop_reason")
            calls = (out.get("tool_calls") or []) if stop == "tool_use" else []  # a cut-off call is not a call
            for c in [] if calls else out.get("tool_calls") or []:  # settle the streamed card of each one
                emit({"type": "tool_end", "tool": c["name"], "tool_use_id": c["id"], "tool_run_id": None,
                      "status": "error", "result": {"error": "Not run: the reply was cut off."}, "elapsed_ms": 0})  # fmt: skip
            usage, native = s.usage, out.get("assistant_content")
            if meter := context_usage_event(usage, s.provider.context_window):
                emit(meter)

            persisted = [{"tool": c["name"], "tool_use_id": c["id"], "args": c.get("args") or {}} for c in calls]
            message_id = None
            if text or persisted:
                content = {"text": text, "model": s.provider.model, **({"tool_calls": persisted} if persisted else {})}
                try:
                    message_id = await in_thread(
                        history.save_message,
                        cid,
                        "assistant",
                        content,
                        tokens_in=cache_inclusive_input_tokens(usage),
                        tokens_out=usage.get("output_tokens"),
                    )
                except Exception:
                    logger.warning("could not save the assistant iteration", exc_info=True)
                    if persisted:  # never run or confirm a tool call that is not recorded
                        return await self._end("Failed to save the assistant turn.")

            if stop != "tool_use" or not calls:
                if s.steers:  # the user wrote while this reply streamed: answer that too
                    if text:  # as the saved row reads back (assembly)
                        s.messages = assembly.coalesce([*s.messages, {"role": "assistant", "content": text}])
                    continue
                return await self._end()

            s.pending = False
            results = await dispatch.run_calls(s, emit, calls, message_id)
            s.messages = s.messages + s.provider.build_tool_turn(text, calls, results, native=native)
            if s.terminated or s.halt:
                return await self._end()
            if s.pending:
                return await self._end(await self._wrap_up())
        s.halt = f"it reached the limit of {MAX_ITERATIONS} tool rounds"
        await self._end(await self._wrap_up(LAST_ANSWER))  # one last call to answer with what it has

    async def _assemble(self) -> list[dict]:
        msgs = await in_thread(assembly.assemble_messages, self.state.provider, self.state.conversation_id)
        if msgs and msgs[-1]["role"] == "assistant":  # a resumed turn can end on the wrap-up narration
            msgs.append({"role": "user", "content": CONTINUATION_ACK})
        return msgs

    def _tools(self) -> list[dict]:
        s = self.state
        tools = [spec.provider_def() for spec in s.by_name.values() if spec.name in s.loaded]
        return tools + ([deferred.FIND_TOOLS_DEF] if s.deferred_specs else [])

    async def _model_call(self, *, narrate: bool = False, nudge: str | None = None) -> dict | str:
        """One model call with its hooks: the `_turn_complete` event plus `text`, or the error text.
        A narration call forwards only text; `nudge` is a user line appended for this call only (and
        again after a Fallback rebuild). Only a failure before anything reached the client is
        offered to `on_provider_error`."""
        s, failures = self.state, 0
        if nudge:
            s.messages = assembly.coalesce([*s.messages, {"role": "user", "content": nudge}])
        while True:
            if not narrate:  # every attempt, retries included; a narration's tool calls are ignored, so it takes none
                await self._take_steers()
            await turn_hooks.before_model_call(s)
            text, sent, failure = "", False, None
            calling_tainted.set(s.tainted)
            stream = s.provider.stream_turn(s.messages, self._tools(), s.system)
            async for event in metered(stream, s.provider, "chat", s.conversation_id):
                etype = event.get("type")
                if etype == "text":
                    text, sent = text + event["text"], True
                    self.emit({"type": "text", "text": event["text"]})
                elif etype == "tool_start" and not narrate:
                    sent = True
                    self.emit({"type": "tool_start", "tool": event["tool"], "tool_use_id": event["tool_use_id"]})
                elif etype == "tool_args" and not narrate:
                    sent = True
                    spec = s.by_name.get(event["tool"])
                    self.emit(
                        {
                            "type": "tool_args",
                            "tool": event["tool"],
                            "tool_use_id": event["tool_use_id"],
                            "args": event.get("args", {}),
                            "description": spec.description if spec else "",
                        }
                    )
                elif etype == "untrusted" and not s.tainted:  # the provider's own web search (Anthropic)
                    s.tainted = True
                    await in_thread(history.mark_tainted, s.conversation_id)
                elif etype == "error":
                    failure = event
                    break
                elif etype == "_turn_complete":
                    s.usage = event.get("usage") or {}
                    s.last_text, s.stop_reason = text, event.get("stop_reason")
                    return {**event, "text": text}
            s.last_text, s.stop_reason = text, None
            if failure is None:
                return "The model response ended unexpectedly."
            error = str(failure.get("error") or "Provider error")[:500]
            failures += 1
            if sent or failures >= turn_hooks.MAX_PROVIDER_FAILURES:
                return error
            action = await turn_hooks.on_provider_error(
                s,
                ProviderFailure(
                    error, failures, failure.get("status"), failure.get("retry_after"), failure.get("code")
                ),
            )
            if isinstance(action, Retry):
                await asyncio.sleep(min(action.delay, 30))
            elif isinstance(action, Fallback):
                s.provider = action.provider
                s.messages = await self._assemble()
                if nudge:
                    s.messages = assembly.coalesce([*s.messages, {"role": "user", "content": nudge}])
            else:
                return action.message or error

    async def _take_steers(self) -> None:
        """Steering (agent.md §5): before a model call that can act (not a narration), each message the
        user sent while the turn ran is saved as a user row and shown to the model after the step's
        results, so every call still has its result. A message still queued when the turn ends is
        saved by `detached` instead, and the client continues the conversation to answer it."""
        s = self.state
        while s.steers:
            text = s.steers.pop(0)
            await in_thread(history.save_message, s.conversation_id, "user", {"text": text})
            s.messages = assembly.coalesce([*s.messages, {"role": "user", "content": text}])
            self.emit({"type": "steer", "text": text})

    async def _wrap_up(self, nudge: str | None = None) -> str | None:
        """One narration turn so the model says what is waiting for approval, or (with `nudge`) gives
        its last answer at the round limit; the error text or None. Tools are still passed (Anthropic
        rejects tool_use history without them); any tool call it makes is ignored."""
        # simplification: the last answer passes the tools and ignores any call; upgrade: tool_choice
        # "none" through stream_turn if a model keeps calling.
        s = self.state
        out = await self._model_call(narrate=True, nudge=nudge)
        if isinstance(out, str):
            return out
        usage = s.usage
        if meter := context_usage_event(usage, s.provider.context_window, meter_only=True):
            self.emit(meter)
        if out["text"].strip():
            await in_thread(
                history.save_message,
                s.conversation_id,
                "assistant",
                {"text": out["text"], "model": s.provider.model},
                tokens_in=cache_inclusive_input_tokens(usage),
            )
        return None

    async def _end(self, error: str | None = None) -> None:
        """The exits that settle memory: `end_of_turn` events (on `done` and on `error`, with
        `state.error` set), `after_turn`, then the terminal event."""
        s = self.state
        s.error = error
        for event in await turn_hooks.end_of_turn(s):
            self.emit(event)
        await in_thread(assembly.after_turn, s.conversation_id)
        self.emit({"type": "error", "error": error} if error else {"type": "done", "model": s.provider.model})
