"""Todos: constants, validation and recurrence math. Imports nothing from this app.

Lifted from todo-gtd's common.py (docs/PROVENANCE.md). Validation errors are core's `Invalid`
(422), raised at the service layer because bulk updates and Whisk tools pass untyped dicts.
"""

from __future__ import annotations

import calendar
import datetime
import json
import re

from backend.core.errors import Invalid

TODO_STATUSES = ("inbox", "next_action", "waiting_for", "delegated", "someday_maybe", "done", "dropped")
FINISHED = ("done", "dropped")
PROJECT_STATUSES = ("active", "someday", "completed", "dropped")
AREA_STATUSES = ("active", "dropped")
VISIBILITIES = ("private", "team")
SOURCES = ("ui", "agent", "app")  # who created the row: the web app, Whisk or MCP, another app (api.py)

MAX_TEXT_CHARS = 20_000
MAX_SHORT_CHARS = 500
MAX_TAGS = 50
MAX_BULK = 500

# Weekly review: an open, committed todo untouched this long is "stale"; dated ones this far
# ahead are "upcoming"; a review is due this long after the last one.
REVIEW_STALE_DAYS = 14
REVIEW_UPCOMING_DAYS = 14
REVIEW_EVERY_DAYS = 7

# '' means no repeat. 'every:N' (N days) is validated by _EVERY_RE, not the tuple.
REPEAT_OPTIONS = ("", "daily", "weekdays", "weekly", "monthly", "yearly")
_EVERY_RE = re.compile(r"^every:([1-9][0-9]{0,3})$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_SHARED = {"visibility", "owner_user_id", "assignee_user_id"}
ITEM_FIELDS = frozenset({
    "title", "notes", "project_id", "area_id", "context", "tags", "people", "status", "star", "due_date",
    "revisit_on", "repeat", "auto_star_on_due", "entity_type", "entity_id", *_SHARED,
})  # fmt: skip
PROJECT_FIELDS = frozenset({"name", "notes", "status", "purpose", "outcome", "area_id", *_SHARED})
AREA_FIELDS = frozenset({"name", "notes", "status", *_SHARED})


def check_fields(fields: dict, valid: frozenset) -> None:
    if not fields:
        raise Invalid("No fields to update")
    if unknown := set(fields) - valid:
        raise Invalid(f"Unknown fields: {', '.join(sorted(unknown))}. Valid: {', '.join(sorted(valid))}")


def choice(value, choices: tuple, label: str) -> str:
    if value not in choices:
        raise Invalid(f"Invalid {label} '{value}'. Valid: {', '.join(choices)}")
    return value


def flag(value, field: str) -> int:
    """A boolean as 0/1. Bulk fields are an untyped dict, so "false" must not read as true."""
    if value is None or value in (0, 1):  # True == 1, False == 0
        return 1 if value else 0
    raise Invalid(f"{field} must be true or false")


def ref(value, field: str) -> int | None:
    """An optional id: None, '' and 0 clear it."""
    if value in (None, "", 0):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise Invalid(f"{field} must be an integer, got {value!r}") from None


def required_text(value, field: str, empty: str, limit: int = MAX_SHORT_CHARS) -> str:
    if value is not None and not isinstance(value, str):
        raise Invalid(f"{field} must be a string")
    text = (value or "").strip()
    if not text:
        raise Invalid(empty)
    if len(text) > limit:
        raise Invalid(f"{field} too long (max {limit} characters)")
    return text


def validate_due(value, field: str = "due_date") -> str | None:
    """A date-only field (`due_date`, `revisit_on`): YYYY-MM-DD or None."""
    if value in (None, ""):
        return None
    due = str(value).strip()
    if not _DATE_RE.match(due):
        raise Invalid(f"{field} must be YYYY-MM-DD, got '{value}'")
    try:
        # Shape alone lets '2026-13-40' through; dates compare as text, so it must be real.
        datetime.date.fromisoformat(due)
    except ValueError:
        raise Invalid(f"{field} is not a real calendar date: '{value}'") from None
    return due


def validate_repeat(repeat) -> str:
    r = str(repeat or "").strip().lower()
    if r == "none":
        r = ""
    if r in REPEAT_OPTIONS or _EVERY_RE.match(r):
        return r
    raise Invalid(
        f"Invalid repeat '{repeat}'. Valid: daily, weekdays, weekly, monthly, yearly, every:N (N days), or empty for none"
    )


def validate_tags(tags, field: str = "tags", item: str = "tag") -> str:
    """A list of short strings (`tags`, `people`), stored as JSON text."""
    if tags is None:
        tags = []
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise Invalid(f"{field} must be a list of strings")
    cleaned = [t.strip() for t in tags if t.strip()]
    if len(cleaned) > MAX_TAGS:
        raise Invalid(f"too many {field} (max {MAX_TAGS})")
    if any(len(t) > MAX_SHORT_CHARS for t in cleaned):
        raise Invalid(f"{item} too long (max {MAX_SHORT_CHARS} characters)")
    # ensure_ascii=False so search's LIKE over the stored text matches non-ASCII values.
    return json.dumps(cleaned, ensure_ascii=False)


def validate_people(people) -> str:
    return validate_tags(people, "people", "person")


def validate_notes(notes, field: str = "notes") -> str:
    text = str(notes or "")
    if len(text) > MAX_TEXT_CHARS:
        raise Invalid(f"{field} too long (max {MAX_TEXT_CHARS} characters)")
    return text


def validate_short(value, field: str) -> str:
    text = str(value or "").strip()
    if len(text) > MAX_SHORT_CHARS:
        raise Invalid(f"{field} too long (max {MAX_SHORT_CHARS} characters)")
    return text


def _advance(repeat: str, base: datetime.date) -> datetime.date:
    """One repeat interval after `base`, clamping month-end and Feb-29 overflow."""
    if repeat == "daily":
        return base + datetime.timedelta(days=1)
    if repeat == "weekdays":
        nxt = base + datetime.timedelta(days=1)
        while nxt.weekday() >= 5:  # 5=Sat, 6=Sun
            nxt += datetime.timedelta(days=1)
        return nxt
    if repeat == "weekly":
        return base + datetime.timedelta(days=7)
    if repeat == "monthly":
        y, m = (base.year, base.month + 1) if base.month < 12 else (base.year + 1, 1)
        return base.replace(year=y, month=m, day=min(base.day, calendar.monthrange(y, m)[1]))
    if repeat == "yearly":
        y = base.year + 1
        return base.replace(year=y, day=min(base.day, calendar.monthrange(y, base.month)[1]))
    if m := _EVERY_RE.match(repeat):
        return base + datetime.timedelta(days=int(m.group(1)))
    raise Invalid(f"Invalid repeat '{repeat}'")


def next_due(repeat: str, due_date: str | datetime.date | None, today: datetime.date) -> str:
    """Due date of a repeating todo's next occurrence.

    Advances from the old due date; re-anchors to `today` only when even the advanced date is
    already past, so completing late never spawns an overdue copy. `today` is the caller's single
    clock read: the spawn compares the result against it too (auto-star).

    # simplification: next-due derives from the previous occurrence with month-end clamping, so a
    # monthly Jan-31 repeat drifts to the 28th after February; store an anchor day if that matters.
    """
    if isinstance(due_date, datetime.date):
        base = due_date
    else:
        try:
            base = datetime.date.fromisoformat(due_date) if due_date else today
        except ValueError:
            base = today
    try:
        nxt = _advance(repeat, base)
        if nxt < today:
            nxt = _advance(repeat, today)
    except Invalid:
        raise
    except (OverflowError, ValueError):  # past date.max
        raise Invalid("The next due date is out of range. Clear the repeat first.") from None
    return nxt.isoformat()
