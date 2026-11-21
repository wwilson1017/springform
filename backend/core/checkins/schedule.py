"""Check-in schedules, one text each (agent.md §5): `every:<minutes>`, `daily@HH:MM` or
`weekly:<mon..sun>@HH:MM`, read in the install timezone. Pure: no I/O, no clock."""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from backend.core.errors import Invalid
from backend.core.reminders import recurrence

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MIN_EVERY, MAX_EVERY = 15, 7 * 24 * 60  # minutes
_HHMM = r"((?:[01]\d|2[0-3]):[0-5]\d)"
_RE = re.compile(rf"^(?:every:(\d{{1,5}})|daily@{_HHMM}|weekly:({'|'.join(DAYS)})@{_HHMM})$")
HELP = (
    "The schedule must be every 15 minutes to 7 days (every:60), daily at a time (daily@09:00) or "
    "weekly on a day at a time (weekly:mon@09:00)."
)


def parse(text: str) -> tuple[str, int, time]:
    """("every", minutes, 00:00) | ("daily", 0, time) | ("weekly", weekday 0-6, time)."""
    m = _RE.match((text or "").strip().lower())
    if m is None:
        raise Invalid(HELP)
    every, daily, day, weekly = m.groups()
    if every is not None:
        if not MIN_EVERY <= int(every) <= MAX_EVERY:
            raise Invalid(HELP)
        return "every", int(every), time()
    if daily is not None:
        return "daily", 0, time.fromisoformat(daily)
    return "weekly", DAYS.index(day), time.fromisoformat(weekly)


def normalize(text: str) -> str:
    """The text that is stored: validated, stripped and lower-case."""
    parse(text)
    return text.strip().lower()


def next_run(text: str, after: datetime, zone: ZoneInfo) -> datetime:
    """The first slot strictly after `after` (aware): a missed backlog is skipped, never replayed."""
    kind, n, at = parse(text)
    if kind == "every":
        return after + timedelta(minutes=n)
    day = after.astimezone(zone).date()
    if kind == "weekly":
        day -= timedelta(days=(day.weekday() - n) % 7)  # the latest such weekday anchors the series
    return recurrence.next_due(kind, day, at, after=after, zone=zone)[1]
