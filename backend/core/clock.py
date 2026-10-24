"""The single timestamp writer. Canonical form: `YYYY-MM-DDTHH:MM:SSZ` (UTC, second precision).

Canonical strings sort chronologically, so SQL compares them as text against bounds computed
here. SQL never reads the database's own clock (test_db greps for it).
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

FORMAT = "%Y-%m-%dT%H:%M:%SZ"
logger = logging.getLogger(__name__)


def now() -> datetime:
    """The current instant, aware UTC, truncated to the second (frozen in tests)."""
    if _frozen is not None:
        return _frozen
    return datetime.now(UTC).replace(microsecond=0)


def now_iso() -> str:
    return to_iso(now())


def to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("to_iso needs an aware datetime")
    return dt.astimezone(UTC).strftime(FORMAT)


def parse(value: str) -> datetime:
    """A canonical string back to an aware UTC datetime."""
    return datetime.strptime(value, FORMAT).replace(tzinfo=UTC)


def ago(seconds: float) -> str:
    """Canonical string for `seconds` before now: the bound for "older than" queries."""
    return to_iso(now() - timedelta(seconds=seconds))


def later(seconds: float) -> str:
    return to_iso(now() + timedelta(seconds=seconds))


def normalize(value: str | datetime, tz: str | ZoneInfo | None = None) -> str:
    """A user-supplied instant in canonical form. Values without an offset are read in `tz`,
    which defaults to the install timezone."""
    if isinstance(value, str):
        text = value.strip()
        try:
            dt = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text)
        except ValueError:
            raise ValueError(f"Not a date-time: {value!r}") from None
    else:
        dt = value
    if dt.tzinfo is None:
        if tz is None:
            from backend.core.localtime import tz as install_tz

            zone = install_tz()
        else:
            zone = ZoneInfo(tz) if isinstance(tz, str) else tz
        dt = dt.replace(tzinfo=zone)
    return to_iso(dt.replace(microsecond=0))


def freeze(iso: str | None) -> None:
    """Test hook: pin now() to a canonical instant, or unpin with None."""
    global _frozen
    _frozen = parse(iso) if iso else None


def _from_env() -> datetime | None:
    """`SPRINGFORM_FREEZE_CLOCK=<iso>` pins the clock for Playwright, honoured only in PREVIEW_MODE.
    Reads the env directly: `settings` imports this module, so `settings.preview_mode()` is not yet defined."""
    value = os.environ.get("SPRINGFORM_FREEZE_CLOCK", "").strip()
    if not value:
        return None
    if os.environ.get("PREVIEW_MODE") != "1":
        logger.warning("SPRINGFORM_FREEZE_CLOCK is ignored outside PREVIEW_MODE; the clock runs normally")
        return None
    frozen = parse(normalize(value, "UTC"))
    logger.warning("SPRINGFORM_FREEZE_CLOCK: the clock is frozen at %s", to_iso(frozen))
    return frozen


_frozen: datetime | None = _from_env()
