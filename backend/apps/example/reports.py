from collections import Counter

from backend.core import db, entities
from backend.core.reports.registry import Report


def widgets_by_color(params: dict, user) -> tuple[list[str], list[list]]:
    """Counts only the widgets this user may read."""
    conn = db.get_conn()
    entity = entities.get("example.widget")
    counts = Counter(
        row["color"] or "" for row in conn.execute("SELECT id, color FROM example_widgets")
        if entity.can_read(user, conn, row["id"])
    )
    return ["color", "widgets"], [[color, n] for color, n in sorted(counts.items())]


REPORTS = [Report(key="example.widgets_by_color", label="Widgets by colour", app="example", run=widgets_by_color)]
