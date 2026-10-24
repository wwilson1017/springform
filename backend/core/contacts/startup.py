from backend.core import db, settings
from backend.core.contacts import seed


def on_startup() -> None:
    """PREVIEW_MODE: sample contacts, once (seed.sample skips when any exist)."""
    if settings.preview_mode():
        with db.transaction() as conn:
            seed.sample(conn)
