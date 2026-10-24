from backend.core import clock

RESET_TABLES = ["example_widgets"]  # every real table the app owns, in creation order
EXPORT = {
    "example_widgets": {
        "entity": "example.widget",
        "columns": ["id", "name", "color", "owner_user_id", "person_id", "is_private", "created_at", "updated_at"],
    },
}


def seed(conn) -> None:
    """Data the app needs on every install (runs on each boot, so idempotent). None here."""


def sample(conn) -> None:
    """Demo data for PREVIEW_MODE (runs on each preview boot, so idempotent): one public and one
    private widget owned by the first admin."""
    admin = conn.execute("SELECT id FROM core_users WHERE role = 'admin' ORDER BY id LIMIT 1").fetchone()
    if admin is None or conn.execute("SELECT 1 FROM example_widgets LIMIT 1").fetchone():
        return
    now = clock.now_iso()
    conn.executemany(
        """INSERT INTO example_widgets (name, color, owner_user_id, is_private, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [("Sprocket", "teal", admin[0], 0, now, now), ("Secret gear", "plum", admin[0], 1, now, now)],
    )
