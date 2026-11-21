"""Loop guards (agent.md §5, "Loop guards").

A tool call that keeps returning the same thing is a loop: the same (tool, args, result) three
times in a row, the last four calls alternating X, Y, X, Y, or the same reply text (at least
`TEXT_MIN_CHARS`) three rounds in a row. Each detection is a strike, at most one per tool round,
and appends a notice to that result so the model sees it; continuing to repeat after a notice is
the next strike. The third strike sets `state.halt`: the rest of the round is refused and the turn
ends with the closing note. A different call or result breaks the streak, so re-reading after a
change never counts.
"""

from __future__ import annotations

import hashlib
import json

from backend.core.agent import result_cap, turn_hooks
from backend.core.agent.turn_hooks import TurnState

# The cap must see the handler's text, so the notice goes on after it: result_cap registers first.
assert result_cap.on_tool_result in turn_hooks.REGISTERED["on_tool_result"]

MAX_STRIKES = 3
TEXT_MIN_CHARS = 80
HALT_REASON = "it kept repeating the same steps"
NOTICE = (
    "\n\n[Loop notice {n} of {max}: {what}. Do not repeat it: change the arguments, use another tool, "
    "or answer with what you have. The turn ends at notice {max}.]"
)
SAME_CALL = "the same call has returned the same result three times in a row"
CYCLE = "the last four calls alternate between the same two calls with the same results"
SAME_TEXT = "you have written the same text three rounds in a row"

# simplification: text repetition means the whole reply repeated across rounds; a single reply looping
# inside itself runs to the length limit and gets that note; upgrade: a stream watcher.


def _key(name: str, args, outcome) -> str:
    try:
        text = json.dumps([name, args, outcome], sort_keys=True, default=str)
    except TypeError:  # mixed str and int keys cannot be sorted: key order as returned
        text = json.dumps([name, args, outcome], default=str)
    return hashlib.sha256(text.encode()).hexdigest()


def observe(state: TurnState, name: str, args, outcome) -> str:
    """Record one settled call; the notice to append ("" when none). Also called by `call_repair`
    for unknown tools, so a model stuck on a wrong name is stopped the same way."""
    st = state.scratch.setdefault(__name__, {"seen": [], "texts": [], "strikes": 0, "struck": -1, "texted": -1})
    st["seen"].append(_key(name, args, outcome))
    if st["texted"] != state.iteration:  # the round's text, once, at its first call
        st["texted"] = state.iteration
        st["texts"].append(" ".join(state.last_text.split()))
        text_repeat = (
            len(st["texts"]) >= 3 and len(set(st["texts"][-3:])) == 1 and len(st["texts"][-1]) >= TEXT_MIN_CHARS
        )
    else:
        text_repeat = False
    seen = st["seen"]
    what = (
        SAME_CALL
        if len(seen) >= 3 and len(set(seen[-3:])) == 1
        else CYCLE
        if len(seen) >= 4 and seen[-1] == seen[-3] and seen[-2] == seen[-4] and seen[-1] != seen[-2]
        else SAME_TEXT
        if text_repeat
        else None
    )
    if what is None or st["struck"] == state.iteration:
        return ""
    st["struck"] = state.iteration
    st["strikes"] += 1
    if st["strikes"] >= MAX_STRIKES:
        state.halt = HALT_REASON
    return NOTICE.format(n=st["strikes"], max=MAX_STRIKES, what=what)


def on_tool_result(state: TurnState, call: dict, run: dict) -> str | None:
    # The handler's own value, not `content`: an untrusted result gets a fresh fence nonce each time,
    # and another hook may have rewritten the content.
    notice = observe(state, call["name"], call.get("args") or {}, [run["status"], run["result"]])
    return run["content"] + notice if notice else None


turn_hooks.register("on_tool_result", on_tool_result)
