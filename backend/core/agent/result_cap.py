"""Big tool results reach the model as their start and end plus a handle (agent.md §5, "Result cap").

A result over `CAP_CHARS` keeps its head and tail, cut at line breaks, with a notice naming the
handle `r<tool run id>`; `core_read_result` pages or greps the rest for `READABLE_HOURS`. A JSON
list of like records (or such lists inside an object) becomes CSV first, which often brings it under
the cap on its own. The full text is the tool run's own stored result, so nothing extra is stored:
the `on_tool_result` hook caps this turn's view, and `assembly` applies the same pure function to
every later turn, a Fallback rebuild and a tool that ran after approval (which never passes the hook).
"""

from __future__ import annotations

import csv
import io
import json
import re

from backend.core import clock
from backend.core.agent import delimiters, history, turn_hooks
from backend.core.agent.aio import in_thread
from backend.core.agent.spec import calling_conversation
from backend.core.auth.deps import User
from backend.core.errors import Invalid, NotFound

CAP_CHARS = 25_000
HEAD_CHARS = 15_000
TAIL_CHARS = 5_000
READ_CHARS = 20_000  # one core_read_result page, under the cap so a page is never capped itself
READABLE_HOURS = 24
GREP_MAX_MATCHES = 50
GREP_CONTEXT_CHARS = 150
GREP_MAX_CHARS = 200
CSV_MIN_ROWS = 3
CSV_MIN_FIELDS = 3
CSV_KEY_SHARE = 0.9
CSV_MAX_CHARS = 2_000_000
CSV_MAX_CELLS = 200_000  # rows x columns: rows that each add their own keys would blow the table up
_HANDLE_RE = re.compile(r"r(\d+)")
_FENCE_RE = re.compile(
    rf'(<{delimiters.UNTRUSTED_EXTERNAL_TAG} id="([0-9a-f]+)"[^>]*>\n)(.*)(\n</{delimiters.UNTRUSTED_EXTERNAL_TAG} id="\2">)',
    re.DOTALL,
)


# ── CSV for lists of like records ─────────────────────────────────────────────


def _uniform_keys(items) -> list[str] | None:
    """The CSV header when `items` is a list of like records, else None."""
    if not isinstance(items, list) or len(items) < CSV_MIN_ROWS or not all(isinstance(i, dict) for i in items):
        return None
    counts: dict[str, int] = {}
    for item in items:
        for key in item:
            counts[key] = counts.get(key, 0) + 1
    if sum(1 for n in counts.values() if n >= CSV_KEY_SHARE * len(items)) < CSV_MIN_FIELDS:
        return None
    first = list(items[0])
    header = first + sorted(k for k in counts if k not in items[0])
    return header if len(items) * len(header) <= CSV_MAX_CELLS else None


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float | str):
        return str(value)
    return json.dumps(value, separators=(",", ":"), default=str)


def _csv_block(key: str, items: list[dict], header: list[str]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    writer.writerows([_cell(item.get(k)) for k in header] for item in items)
    return f"[CSV: {key}, {len(items)} rows x {len(header)} fields]\n{out.getvalue()}"


def _as_csv(text: str) -> str | None:
    """`text` with its lists of like records as CSV blocks; None when nothing qualifies or it is not shorter."""
    if len(text) > CSV_MAX_CHARS:
        return None
    try:
        value = json.loads(text)
    except (ValueError, RecursionError):  # not JSON, or nested past the parser's depth
        return None
    if header := _uniform_keys(value):
        out = _csv_block("result", value, header)
    elif isinstance(value, dict) and any(_uniform_keys(v) for v in value.values()):
        lines, blocks = [], []
        for key, v in value.items():
            if header := _uniform_keys(v):
                blocks.append(_csv_block(key, v, header))
            elif isinstance(v, dict | list):
                lines.append(f"{key}: {json.dumps(v, separators=(',', ':'), default=str)}")
            else:
                lines.append(f"{key}: {_cell(v)}")
        out = "\n".join(lines + blocks)
    else:
        return None
    return out if len(out) < len(text) else None


def full_text(content: str) -> str:
    """The text a handle addresses: `content` itself, or with its record lists as CSV when it is
    over the cap. An untrusted result is converted inside its fence, which keeps its tags."""
    if len(content) <= CAP_CHARS:
        return content
    if fence := _FENCE_RE.fullmatch(content):
        inner = _as_csv(fence.group(3))
        return fence.group(1) + inner + fence.group(4) if inner else content
    return _as_csv(content) or content


# ── The cap ───────────────────────────────────────────────────────────────────


def capped(content, run_id: int):
    """What the model is shown for a result: unchanged when it fits (or as CSV when that alone
    fits), else head + tail at line breaks and the notice. Deterministic, so every turn shows the
    same bytes; capping twice changes nothing."""
    if not isinstance(content, str) or len(content) <= CAP_CHARS:
        return content
    text = full_text(content)
    if len(text) <= CAP_CHARS:
        return text
    head = text[:HEAD_CHARS]
    if (cut := head.rfind("\n")) >= HEAD_CHARS // 2:
        head = head[: cut + 1]
    tail = text[-TAIL_CHARS:]
    if 0 <= (cut := tail.find("\n")) < TAIL_CHARS // 2:
        tail = tail[cut + 1 :]
    omitted = len(text) - len(head) - len(tail)
    return (
        f"{head}\n[... {omitted} characters omitted ...]\n{tail}\n\n"
        f"[Result capped: {len(text)} characters, the first {len(head)} and the last {len(tail)} shown. "
        f'Read the rest with core_read_result(handle="r{run_id}", offset={len(head)}), or search it with grep. '
        f"Available for {READABLE_HOURS} hours.]"
    )


async def on_tool_result(state, call: dict, run: dict) -> str | None:
    if run["status"] == "done" and isinstance(run["content"], str) and len(run["content"]) > CAP_CHARS:
        return await in_thread(capped, run["content"], run["id"])  # parsing megabytes stays off the event loop
    return None


turn_hooks.register("on_tool_result", on_tool_result)


# ── core_read_result ──────────────────────────────────────────────────────────


def read(user: User, handle: str, *, offset: int | None = None, grep: str | None = None) -> str:
    """A page of a capped result (`offset`, characters from the start) or the matches of `grep`
    (a case-insensitive literal) with their offsets. Only the run's user, from the conversation it
    ran in, within READABLE_HOURS of it."""
    m = _HANDLE_RE.fullmatch((handle or "").strip())
    run = history.get_tool_run(int(m.group(1))) if m else None
    if (
        run is None
        or run["user_id"] != user.id
        or run["status"] != "done"
        or run["conversation_id"] is None
        or run["conversation_id"] != calling_conversation.get()
    ):
        raise NotFound("No stored result for that handle in this conversation.")
    if (run["resolved_at"] or run["requested_at"]) < clock.ago(READABLE_HOURS * 3600):
        raise NotFound(f"That result is more than {READABLE_HOURS} hours old. Run the tool again.")
    content = history.model_content(run)
    text = full_text(content)
    if grep:
        out = _grep(handle, text, grep)
    else:
        start = int(offset or 0)
        if start < 0:
            raise Invalid("offset must be 0 or more")
        end = min(start + READ_CHARS, len(text))
        more = f"continue with offset={end}" if end < len(text) else "end of result"
        out = f"[{handle}: characters {start}-{end} of {len(text)}; {more}]\n{text[start:end]}"
    if content.startswith(delimiters.UNTRUSTED_EXTERNAL_MARKER):  # a slice has lost its fence
        out = delimiters.wrap_untrusted_external(run["tool"], out)
    return out


def _fold(text: str) -> str:
    """Lowercase that keeps every offset: a character whose lowercase is longer (like "İ") stays as it is."""
    if len(low := text.lower()) == len(text):
        return low
    return "".join(c if len(c.lower()) != 1 else c.lower() for c in text)


def _grep(handle: str, text: str, needle: str) -> str:
    # simplification: a case-insensitive literal, not a pattern (a model-written regex over megabytes
    # can backtrack past the tool timeout); upgrade: a bounded regex.
    if len(needle) > GREP_MAX_CHARS:
        raise Invalid(f"grep takes at most {GREP_MAX_CHARS} characters")
    hay, low = _fold(text), _fold(needle)
    lines, total, shown_to, at = [], 0, -1, hay.find(low) if low else -1
    while at >= 0 and len(lines) < GREP_MAX_MATCHES:  # str.find is linear; a case-insensitive regex is not
        total += 1
        if at >= shown_to:  # a match inside the last context is counted, not repeated
            lo, shown_to = max(0, at - GREP_CONTEXT_CHARS), at + len(low) + GREP_CONTEXT_CHARS
            lines.append(f"@{at}: " + " ".join(text[lo:shown_to].split()))
        at = hay.find(low, at + len(low))
    if at >= 0:
        total += hay.count(low, at)  # the rest, counted in C (same non-overlapping steps)
    shown = f", {len(lines)} shown" if total > len(lines) else ""
    return "\n".join([f'[{handle}: {total} matches for "{needle}"{shown}]', *lines])
