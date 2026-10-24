"""The settings an admin may change through `/api/core/settings`: core keys with their types and
defaults, plus every app key (`<slug>.*`, from the app's settings.py DEFAULTS, any JSON value).

Core defaults live here rather than in `settings.DEFAULTS`; read a core key with `get(key)`.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

from backend.core import settings
from backend.core.errors import Invalid

DEFAULT_WARNING = (
    "Your request becomes an issue in this install's GitHub repository, where the people who maintain it "
    "can read it. Leave out passwords, card numbers and private customer details."
)
_REPO = re.compile(r"^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$")


@dataclass(frozen=True)
class Key:
    default: Any
    check: Callable[[Any], Any]  # returns the cleaned value or raises ValueError with a reason
    secret: bool = False


def _text(max_len: int, *, required: bool = False, pattern: re.Pattern | None = None) -> Callable[[Any], str]:
    def check(value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("must be text")
        value = value.strip()
        if required and not value:
            raise ValueError("cannot be empty")
        if len(value) > max_len:
            raise ValueError(f"must be at most {max_len} characters")
        if pattern and value and not pattern.match(value):
            raise ValueError("is not in the expected format")
        return value

    return check


def _timezone(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("must be an IANA timezone such as America/Chicago")
    try:
        ZoneInfo(value.strip())
    except (KeyError, ValueError):  # ZoneInfoNotFoundError is a KeyError
        raise ValueError(f"{value!r} is not an IANA timezone such as America/Chicago") from None
    return value.strip()


def _positive_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("must be a whole number above zero")
    return value


def _bool(value: Any) -> bool:
    if not isinstance(value, bool):
        raise ValueError("must be true or false")
    return value


CORE_KEYS: dict[str, Key] = {
    "workspace.name": Key("Springform", _text(80, required=True)),
    "timezone": Key("UTC", _timezone),
    "requests.warning_text": Key(DEFAULT_WARNING, _text(2000)),
    "github.repo": Key("", _text(140, pattern=_REPO)),  # owner/name
    "github.token": Key(None, _text(500, required=True), secret=True),  # fine-grained token, issues read/write
    "files.max_bytes": Key(25 * 1024 * 1024, _positive_int),
    "agent.nightly_enabled": Key(False, _bool),  # off: the nightly run spends AI credits
    "auth.require_totp_for_google": Key(False, _bool),
}


def known() -> dict[str, Key]:
    """Every key the settings API accepts: app keys from the registered DEFAULTS, then core."""
    app_keys = {k: Key(v, lambda value: value) for k, v in settings.DEFAULTS.items() if k not in CORE_KEYS}
    return app_keys | CORE_KEYS


def clean(key: str, value: Any) -> Any:
    spec = known().get(key)
    if spec is None:
        raise Invalid(f"unknown setting {key!r}")
    try:
        return spec.check(value)
    except ValueError as e:
        raise Invalid(f"{key}: {e}") from None


def get(key: str) -> Any:
    """A setting's value, or its default (core keys included)."""
    spec = known().get(key)
    return settings.get_setting(key, spec.default if spec else None)
