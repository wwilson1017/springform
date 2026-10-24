"""PREVIEW_MODE=1: a demo install with a role picker over sample data.

Seeds two accounts with no password (the picker, `POST /api/auth/preview`, is the only way in)
and, when they are first created, each app's `sample(conn)`. Refuses to start when real secrets
are set, so a preview can never hold a real business's keys.
"""

import os

from backend.core import db, settings
from backend.core.auth import service

EMAILS = {"admin": "preview-admin@example.com", "member": "preview-member@example.com"}
REAL_SECRETS = ("ENCRYPTION_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "RESEND_API_KEY")


def check_startup() -> None:
    if settings.preview_mode() and (found := [k for k in REAL_SECRETS if os.environ.get(k)]):
        raise RuntimeError(f"PREVIEW_MODE=1 refuses to start with real secrets set: {', '.join(found)}")


def seed_in(conn: db.Conn) -> None:
    from backend.core import registry

    created = False
    for role, email in EMAILS.items():
        if not conn.execute("SELECT 1 FROM core_users WHERE email = ?", (email,)).fetchone():
            service.create_user_in(conn, email, f"Preview {role}", role)
            created = True
    if created:
        for app in registry.installed():
            app.modules["seed"].sample(conn)


def seed() -> None:
    if settings.preview_mode():
        with db.transaction() as conn:
            seed_in(conn)
