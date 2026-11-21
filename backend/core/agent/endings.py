"""Honest endings (agent.md §5, "Honest endings").

When a turn ends without a full reply (cut off for length, refused, empty, stopped at the round
limit or the write budget, or a provider failure after tools ran), an `end_of_turn` hook saves a
note as an assistant row and streams it as `text`, so a reloaded thread shows the same. After a
tool ran it never says "send it again": a write may already have happened.
"""

from __future__ import annotations

import logging

from backend.core.agent import deferred, history, turn_hooks
from backend.core.agent.aio import in_thread
from backend.core.agent.turn_hooks import TurnState

logger = logging.getLogger(__name__)

# Note texts after the maintainer's CakeCRM `_unfinished_reason` / `_unfinished_note` (docs/PROVENANCE.md).
REASONS = {
    "max_tokens": "it hit the length limit for a single response",
    "model_context_window_exceeded": "it hit the length limit for a single response",
    "refusal": "the model declined to answer",
    "empty": "the model ended without writing a reply",
    "error": "the AI service returned an error",
    "budget": "it reached the limit of writes for one turn",
}
STEPS = ", after {n} tool call{s} (last: {tool}). Some steps may already have run; check the results above before asking again"
INCOMPLETE = "*(This reply is incomplete: {reason}{steps}.)*"
NO_REPLY = "*(No complete reply: {reason}{steps}.)*"
AGAIN = ". Please send your message again"


def reason(state: TurnState) -> str | None:
    """Why this turn ended without a full reply, as a clause; None when it did not."""
    if state.error is not None:
        return REASONS["error"]
    if state.halt:
        return state.halt
    if state.terminated:
        return REASONS["budget"]
    if state.pending:
        return None  # the Approve card is the message
    if state.stop_reason in REASONS:
        return REASONS[state.stop_reason]
    return None if state.last_text.strip() else REASONS["empty"]


async def end_of_turn(state: TurnState) -> list[dict] | None:
    why = reason(state)
    if why is None:
        return None
    ran = [
        r
        for r in await in_thread(history.runs_since_user, state.conversation_id)
        if r["status"] in history.RAN and r["tool"] != deferred.FIND_TOOLS
    ]
    if state.error is not None and not ran:
        return None  # nothing ran: the error event says it all
    steps = STEPS.format(n=len(ran), s="" if len(ran) == 1 else "s", tool=ran[-1]["tool"]) if ran else ""
    partial = state.last_text.strip()
    note = (INCOMPLETE if partial else NO_REPLY).format(reason=why, steps=steps or ("" if partial else AGAIN))
    # On an error ending the partial text was streamed but never saved: it goes in with the note.
    saved = f"{state.last_text}\n\n{note}" if state.error is not None and partial else note
    try:
        await in_thread(
            history.save_message, state.conversation_id, "assistant", {"text": saved, "model": state.provider.model}
        )
    except Exception:
        logger.warning("could not save the closing note", exc_info=True)
    return [{"type": "text", "text": ("\n\n" if partial else "") + note}]


turn_hooks.register("end_of_turn", end_of_turn)
