from collections import Counter

from backend.core import db, entities
from backend.core.reports.registry import Report


def open_team_by_assignee(params: dict, user) -> tuple[list[str], list[list]]:
    """Open team todos per assignee, counting only the todos this user may read."""
    conn = db.get_conn()
    entity = entities.get("todos.item")
    rows = conn.execute(
        """SELECT t.id, u.name FROM todos_items t LEFT JOIN core_users u ON u.id = t.assignee_user_id
            WHERE t.visibility = 'team' AND t.status NOT IN ('done', 'dropped')"""
    )
    counts = Counter(name or "Unassigned" for item_id, name in rows if entity.can_read(user, conn, item_id))
    return ["assignee", "open"], [[name, n] for name, n in sorted(counts.items())]


REPORTS = [Report(key="todos.open_team_by_assignee", label="Open team todos by assignee", app="todos", run=open_team_by_assignee)]
