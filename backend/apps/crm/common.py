"""CRM constants and small validators shared by the services. Imports nothing from this app."""

from __future__ import annotations

import re
from datetime import date

from backend.core.errors import Invalid

ENTITY = "crm.deal"
STAGES = ("lead", "qualified", "proposal", "negotiation", "won", "lost")
CLOSED_STAGES = ("won", "lost")
OPEN_STAGES = tuple(s for s in STAGES if s not in CLOSED_STAGES)
TEMPERATURES = ("hot", "warm", "cold")

LIVE = "d.archived_at IS NULL"
OPEN = "d.stage NOT IN ('won', 'lost')"

MAX_TITLE = 200
MAX_TEXT = 20_000
MAX_REASON = 500
BULK_MOVE_MAX = 200

_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def day(value, field: str) -> str | None:
    """A YYYY-MM-DD string, or None for None/''. A real calendar date, never a datetime."""
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str) or not _DAY.match(value):
        raise Invalid(f"{field} must be a YYYY-MM-DD date, got {value!r}")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise Invalid(f"{field} is not a real calendar date: {value!r}") from None
    return value


def fts_match(q: str | None) -> str | None:
    """An FTS5 query from user text: every word must match as a prefix. Quoting keeps FTS
    syntax out of user input; unicode61 folds case and accents on both sides."""
    return " ".join(f'"{t}"*' for t in re.findall(r"\w+", q or "")) or None
