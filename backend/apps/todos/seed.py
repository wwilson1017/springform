import datetime

from backend.apps.todos import service
from backend.core.auth.deps import User

RESET_TABLES = ["todos_areas", "todos_projects", "todos_items", "todos_sync", "todos_journal"]  # creation order
EXPORT = {
    "todos_items": {
        "entity": "todos.item",
        "columns": ["id", "owner_user_id", "title", "status", "due_date", "visibility"],
    },
}


def seed(conn) -> None:
    """Nothing every install needs: the sync rows appear with the first change."""


def sample(conn) -> None:
    """Preview data: a team area and project with shared todos, and a private todo each for the
    first admin and the first member."""
    rows = conn.execute(
        """SELECT id, email, name, role, tz, is_active, token_epoch FROM core_users
            WHERE role IN ('admin', 'member') AND is_active = 1 ORDER BY id DESC"""
    )
    people = {r["role"]: User.from_row(dict(r)) for r in rows}  # the lowest id of each role wins
    admin = people.get("admin")
    if admin is None:
        return
    member = people.get("member", admin)
    soon = (service.today(admin) + datetime.timedelta(days=3)).isoformat()
    area = service.create_area_in(conn, admin, "Operations", visibility="team")
    project = service.create_project_in(
        conn, admin, "Spring clean-up", visibility="team", area_id=area["id"], outcome="The shop is ready for the busy season"
    )
    for user, title, fields in [
        (admin, "Book the window cleaner", {"project_id": project["id"], "status": "next_action", "assignee_user_id": member.id, "due_date": soon}),
        (admin, "Order new aprons", {"project_id": project["id"]}),
        (member, "Check the fridge temperatures", {"status": "next_action", "repeat": "daily", "context": "@shop", "due_date": service.today(member).isoformat()}),
    ]:  # fmt: skip
        service.create_item_in(conn, user, title, visibility="team", **fields)
    service.create_item_in(conn, admin, "Plan the staff party", status="someday_maybe", visibility="private")
    service.create_item_in(conn, member, "Ask about holiday dates", visibility="private")
