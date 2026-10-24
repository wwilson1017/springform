from backend.core import db
from backend.core.memory import context_files


def on_startup() -> None:
    """Seed Whisk's default context files when missing; an admin's edits are never overwritten."""
    with db.transaction() as conn:
        context_files.seed_defaults_in(conn)
