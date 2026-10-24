from backend.core import clock, db
from backend.core.scheduler import Job
from backend.core.timeline import api as timeline

SYSTEM_USER_ID = 0


def tidy(cancel) -> None:
    """Lower-case widget colours, attributed to the system principal."""
    with db.transaction() as conn:
        for row in conn.execute(
            "SELECT * FROM example_widgets WHERE color IS NOT NULL AND color != lower(trim(color))"
        ).fetchall():
            before = dict(row)
            conn.execute(
                "UPDATE example_widgets SET color = lower(trim(color)), updated_at = ? WHERE id = ?",
                (clock.now_iso(), row["id"]),
            )
            after = dict(conn.execute("SELECT * FROM example_widgets WHERE id = ?", (row["id"],)).fetchone())
            timeline.record_changes_in(conn, "example.widget", row["id"], before, after, SYSTEM_USER_ID)


JOBS = [Job(name="example.tidy", fn=tidy, every=3600)]
