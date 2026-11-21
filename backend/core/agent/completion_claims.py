"""The completion-claim guard (agent.md §5, "Completion claims").

An `end_of_turn` hook reads the final reply for sentences that claim something was sent, filed,
posted or created. A claim no tool run of this turn could back (a write or external effect that
ran, or may have, since the user's message) gets a correction note, saved and streamed after the
reply; the reply itself is not rewritten. Deliberately narrow: questions, negations, future or
conditional phrasing, back-references, quoted drafts, code and talk of approval are never claims,
so every doubt leaves the text alone.

The guards and sentence rules follow the maintainer's cake_os `completion_claims.py` (docs/PROVENANCE.md).
"""

from __future__ import annotations

import logging
import re

from backend.core.agent import deferred, history, turn_hooks
from backend.core.agent.aio import in_thread
from backend.core.agent.turn_hooks import TurnState

logger = logging.getLogger(__name__)

_FP = r"\bI(?:'ve| have)?(?: just| now| also)? "
_LEAD = r"^[\s*_]*"
_LABEL = r"\b(?![^.\n]{0,25}:)"  # "Sent to: x" is a label, not a claim
_RECORD = (
    r"(?:contact|person|people|organization|company|deal|todo|to-do|task|reminder|note|record|project|"
    r"ticket|issue|entry|event)s?"
)
_I = re.IGNORECASE
CLAIMS: dict[str, list[re.Pattern]] = {
    "sent": [
        re.compile(_FP + r"(?:sent|emailed|messaged|texted|forwarded)\b", _I),
        re.compile(r"\b(?:has|have) been (?:sent|emailed|forwarded)\b", _I),
        re.compile(r"\b(?:message|email|invite)(?:'s| is| was| has been) sent\b", _I),
        re.compile(_LEAD + r"(?:Sent|Emailed|Messaged)" + _LABEL),
    ],
    "filed": [
        re.compile(_FP + r"filed\b", _I),
        re.compile(r"\b(?:has|have) been filed\b", _I),
        re.compile(_LEAD + r"Filed" + _LABEL),
    ],
    "posted": [
        re.compile(_FP + r"posted\b", _I),
        re.compile(r"\b(?:note|comment)(?:'s| is| was| has been) (?:posted|added)\b", _I),
        re.compile(_LEAD + r"Posted" + _LABEL),
    ],
    "created": [
        re.compile(_FP + r"(?:created|added|saved|scheduled|set up|logged)\b[^.!?\n]{0,60}?\b" + _RECORD + r"\b", _I),
        re.compile(r"\b" + _RECORD + r"\s(?:has|have) been (?:created|added|saved|scheduled)\b", _I),
    ],
}
_NEGATION = re.compile(r"\b(?:not|never|no|nothing|cannot|unable)\b|n't\b", _I)
_FUTURE = re.compile(
    r"\b(?:will|going to|want me to|shall|should|could|would|can|once|if|when|after|until|before|let me|"
    r"ready to|about to|try to|need to)\b|'ll\b",
    _I,
)
_BACK = re.compile(r"\b(?:earlier|yesterday|last (?:time|week|night|turn)|ago|already|previously)\b", _I)
_APPROVAL = re.compile(r"approv|pending|waiting for|confirm", _I)
_QUOTED = re.compile(r'"[^"\n]*"|“[^”\n]*”')
_SENTENCE = re.compile(r"[^.!?\n]*(?:[.!?](?=\s|$)|$)")
_SEND_TOOL = re.compile(r"send|mail|notify|message|sms|reply|forward", _I)
NOTE = "*(Correction: this reply says something was {verbs}, but no tool in this turn confirms it. Check before relying on it.)*"

# simplification: English phrases, a fixed list of record nouns and the final reply only; a fork's own
# record names and claims made in earlier rounds are missed (a missed claim, never a false one);
# upgrade: nouns from the entity registry, every round's text.


def _sentences(text: str):
    fenced = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced or line.lstrip().startswith(">"):
            continue
        line = _QUOTED.sub(lambda m: " " * len(m.group()), line)  # a quoted draft is not a claim
        yield from (s for s in _SENTENCE.findall(line) if s.strip())


def claims(text: str) -> list[str]:
    """The kinds claimed in `text`, in the order first found."""
    found: list[str] = []
    for sentence in _sentences(text):
        if sentence.rstrip().endswith("?") or _APPROVAL.search(sentence):
            continue
        for kind, patterns in CLAIMS.items():
            if kind in found:
                continue
            for pattern in patterns:
                m = pattern.search(sentence)
                if m is None:
                    continue
                before = sentence[max(0, m.start() - 40) : m.start()] + m.group()[:25]
                around = sentence[max(0, m.start() - 40) : m.end() + 60]
                if not (_NEGATION.search(before) or _FUTURE.search(before) or _BACK.search(around)):
                    found.append(kind)
                    break
    return found


def _backing(state: TurnState) -> tuple[bool, bool]:
    """(any write or effect ran, a send-like one ran) since the user's message; a tool no longer
    offered counts (never accuse on a doubt)."""
    wrote = sent = False
    for run in history.runs_since_user(state.conversation_id):
        if run["status"] not in history.RAN or run["tool"] == deferred.FIND_TOOLS:
            continue
        spec = state.by_name.get(run["tool"])
        if spec is None or spec.writes or spec.external_effect:
            wrote = True
            sent = sent or spec is None or spec.external_effect or bool(_SEND_TOOL.search(run["tool"]))
    return wrote, sent


async def end_of_turn(state: TurnState) -> list[dict] | None:
    if state.error is not None or not state.last_text.strip():
        return None
    found = claims(state.last_text)
    if not found:
        return None
    wrote, sent = await in_thread(_backing, state)
    unbacked = [k for k in found if not (sent if k == "sent" else wrote)]
    if not unbacked:
        return None
    note = NOTE.format(verbs=" or ".join(unbacked))
    logger.info("completion claim without a run: %s in conversation %s", unbacked, state.conversation_id)
    try:
        await in_thread(
            history.save_message, state.conversation_id, "assistant", {"text": note, "model": state.provider.model}
        )
    except Exception:
        logger.warning("could not save the correction note", exc_info=True)
    return [{"type": "text", "text": "\n\n" + note}]


turn_hooks.register("end_of_turn", end_of_turn)
