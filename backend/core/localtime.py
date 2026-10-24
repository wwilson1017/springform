"""The install's local-time convention: one IANA timezone, from the `timezone` setting.

Never use the process-local time instead. Containers run UTC regardless of intent, so
`date.today()` there rolls over mid-evening for a US business. Day bucketing for reports
happens here in Python with zoneinfo; SQL only compares against precomputed UTC bounds.
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from backend.core import clock


def tz() -> ZoneInfo:
    """The install timezone, falling back to UTC on an absent or bogus value.

    Fail-safe rather than fail-fast on purpose: a typo in a setting must not stop the app."""
    try:
        from backend.core.settings import get_setting

        return ZoneInfo(get_setting("timezone") or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def now_local() -> datetime:
    """The current aware datetime in the install timezone."""
    return clock.now().astimezone(tz())


def today_local() -> date:
    return now_local().date()


def local_day_bounds(day: date | None = None) -> tuple[datetime, datetime]:
    """`[start, next_start)` for one local calendar day, as aware instants.

    Built from calendar fields rather than `start + 24h`, so a DST day is honestly 23 or 25
    hours long. The zone is read once: a day whose two ends came from different zones is not
    a day. Pass `day` when the caller already decided which day it is."""
    zone = tz()
    d = day if day is not None else clock.now().astimezone(zone).date()
    start = datetime.combine(d, time.min, tzinfo=zone)
    end = datetime.combine(d + timedelta(days=1), time.min, tzinfo=zone)
    return start, end
