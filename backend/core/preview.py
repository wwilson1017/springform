"""PREVIEW_MODE=1: a demo install with a role picker over sample data.

Seeds two accounts with no password (the picker, `POST /api/auth/preview`, is the only way in)
and runs each app's idempotent `sample(conn)` on every preview boot. Refuses to start when real
secrets are present, so a preview can never hold a real business's keys.
"""

import os

from backend.core import db, settings
from backend.core.auth import service

EMAILS = {"admin": "preview-admin@example.com", "member": "preview-member@example.com"}
REAL_SECRETS = ("ENCRYPTION_KEY", "RESEND_API_KEY")


def check_startup() -> None:
    """Runs after migrations: a secret stored in core_settings counts too. Empty env values are unset."""
    if not settings.preview_mode():
        return
    found = [k for k in REAL_SECRETS if os.environ.get(k)]
    if db.one("SELECT 1 AS x FROM core_settings WHERE is_secret = 1 LIMIT 1"):
        found.append("a secret in core_settings")
    if found:
        raise RuntimeError(f"PREVIEW_MODE=1 refuses to start with real secrets present: {', '.join(found)}")


def seed_in(conn: db.Conn) -> None:
    from backend.core import registry

    for role, email in EMAILS.items():
        if not conn.execute("SELECT 1 FROM core_users WHERE email = ?", (email,)).fetchone():
            service.create_user_in(conn, email, f"Preview {role}", role)
    for app in registry.installed():
        app.modules["seed"].sample(conn)


def seed() -> None:
    if settings.preview_mode():
        with db.transaction() as conn:
            seed_in(conn)
