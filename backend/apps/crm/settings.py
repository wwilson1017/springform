"""CRM settings (core_settings keys `crm.*`) and typed readers for them."""

from backend.core import settings

DEFAULTS = {
    "crm.stale_days": 14,  # an open deal untouched this long needs a touch (badge, Today, analytics)
    "crm.touch_count_enabled": True,  # the crm.touch_count job asks the light model to count touches
    "crm.default_currency": "USD",  # a new deal's currency when the caller does not say
}


def stale_days() -> int:
    value = settings.get_setting("crm.stale_days")
    return value if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 365 else 14


def touch_count_enabled() -> bool:
    return settings.get_setting("crm.touch_count_enabled") is not False


def default_currency() -> str:
    value = settings.get_setting("crm.default_currency")
    return value if isinstance(value, str) and len(value) == 3 else "USD"


def current() -> dict:
    return {"stale_days": stale_days(), "touch_count_enabled": touch_count_enabled(), "default_currency": default_currency()}


def update(user, fields: dict) -> dict:
    """Admin only (the route's guard). Unknown keys never reach here (the route's model)."""
    from backend.core import db

    with db.transaction() as conn:
        for key, value in fields.items():
            settings.set_setting_in(conn, f"crm.{key}", value, user.id)
    return current()
