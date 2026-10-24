"""Process configuration (environment) and install settings (`core_settings`).

Environment: DATA_DIR, PUBLIC_URL, SECRET_KEY, PREVIEW_MODE, TRUST_PROXY, ENCRYPTION_KEY
(secrets.py) and SPRINGFORM_REQUIRE_SQLITE (db.py). Read on each call, so tests can change them.

Install settings are JSON values keyed by name. Core keys are bare (`timezone`); an app's keys
start with `<slug>.` and their defaults come from the app's settings.py `DEFAULTS`. A secret
setting is stored encrypted.
"""

from __future__ import annotations

import functools
import json
import os
import secrets as _stdlib_secrets
from pathlib import Path
from typing import Any

from backend.core import db, secrets
from backend.core.clock import now_iso

_CORE_DEFAULTS: dict[str, Any] = {"timezone": "UTC"}
DEFAULTS: dict[str, Any] = dict(_CORE_DEFAULTS)


def data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR") or "./data")


def public_url() -> str:
    return (os.environ.get("PUBLIC_URL") or "http://localhost:8000").rstrip("/")


def preview_mode() -> bool:
    return os.environ.get("PREVIEW_MODE") == "1"


def trust_proxy() -> bool:
    return os.environ.get("TRUST_PROXY") == "1"


@functools.cache
def _secret_key(data_dir_: str, env_value: str) -> str:
    return secrets.persisted("SECRET_KEY", ".secret-key", lambda: _stdlib_secrets.token_urlsafe(48), lambda v: len(v) >= 32)


def secret_key() -> str:
    """The session signing key: SECRET_KEY, else `<data>/.secret-key`, generated on first use."""
    return _secret_key(str(db.data_dir()), os.environ.get("SECRET_KEY", ""))


def register_defaults(slug: str, defaults: dict[str, Any]) -> None:
    for key, value in defaults.items():
        if not key.startswith(f"{slug}."):
            raise ValueError(f"App '{slug}' setting {key!r} must start with '{slug}.'")
        if key in DEFAULTS:
            raise ValueError(f"Setting {key!r} is declared twice")
        DEFAULTS[key] = value


def clear_defaults() -> None:
    DEFAULTS.clear()
    DEFAULTS.update(_CORE_DEFAULTS)


def get_setting(key: str, default: Any = None) -> Any:
    row = db.one("SELECT value, is_secret FROM core_settings WHERE key = ?", (key,))
    if row is None:
        return DEFAULTS.get(key, default)
    raw = secrets.decrypt(row["value"]) if row["is_secret"] else row["value"]
    return json.loads(raw) if raw else default


def set_setting_in(conn: db.Conn, key: str, value: Any, user_id: int | None, is_secret: bool = False) -> None:
    raw = json.dumps(value)
    conn.execute(
        """INSERT INTO core_settings (key, value, is_secret, updated_at, updated_by) VALUES (?, ?, ?, ?, ?)
           ON CONFLICT (key) DO UPDATE SET value = excluded.value, is_secret = excluded.is_secret,
                                           updated_at = excluded.updated_at, updated_by = excluded.updated_by""",
        (key, secrets.encrypt(raw) if is_secret else raw, int(is_secret), now_iso(), user_id),
    )


def set_setting(key: str, value: Any, user_id: int | None, is_secret: bool = False) -> None:
    with db.transaction() as conn:
        set_setting_in(conn, key, value, user_id, is_secret)
