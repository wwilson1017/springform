"""PREVIEW_MODE=1: a demo install with a role picker over sample data.

Seeds two accounts with a random password nobody knows (the picker, `POST /api/auth/preview`, is
the only way in; the hash makes them count as signed-up accounts, not pending invites, so the
last-admin guard sees the preview admin) and runs each app's idempotent `sample(conn)` on every
preview boot, after core's sample directory (people and organizations), which app samples
build on. Refuses to start when real
secrets are present, so a preview can never hold a real business's keys.
"""

import os
import secrets

from backend.core import db, settings
from backend.core.auth import service
from backend.core.contacts import seed as contacts_seed

EMAILS = {"admin": "preview-admin@example.com", "member": "preview-member@example.com"}
REAL_SECRETS = ("ENCRYPTION_KEY", "RESEND_API_KEY")
# Secrets the install generates for itself are not a business's keys: the web-push VAPID private
# key (notifications/push.py PRIVATE_KEY) appears the first time anyone turns push on.
GENERATED_SECRETS = ("notifications.vapid_private_key",)


def check_startup() -> None:
    """Runs after migrations: a secret stored in core_settings counts too. Empty env values are unset."""
    if not settings.preview_mode():
        return
    found = [k for k in REAL_SECRETS if os.environ.get(k)]
    marks = ", ".join("?" * len(GENERATED_SECRETS))
    if db.one(f"SELECT 1 AS x FROM core_settings WHERE is_secret = 1 AND key NOT IN ({marks}) LIMIT 1", GENERATED_SECRETS):
        found.append("a secret in core_settings")
    if found:
        raise RuntimeError(f"PREVIEW_MODE=1 refuses to start with real secrets present: {', '.join(found)}")


def seed_in(conn: db.Conn) -> None:
    from backend.core import registry

    for role, email in EMAILS.items():
        if not conn.execute("SELECT 1 FROM core_users WHERE email = ?", (email,)).fetchone():
            service.create_user_in(conn, email, f"Preview {role}", role, secrets.token_urlsafe(32))
    contacts_seed.sample(conn)  # core samples first: app samples hang their records off them
    for app in registry.installed():
        app.modules["seed"].sample(conn)


def seed() -> None:
    if settings.preview_mode():
        with db.transaction() as conn:
            seed_in(conn)
