"""Requests: a member files a change request; it becomes a GitHub issue labelled `request` and
`app:<slug>`, and `core_requests` mirrors it for the board.

GitHub calls run outside any transaction; the row is written after the issue exists. The board
lists only requests filed here, and `refresh` syncs their state, title and updated_at.
`core_requests.app` is NULL for core; the API says "core".
"""

from __future__ import annotations

import json
import threading
from typing import TYPE_CHECKING

from backend.core import clock, db, pagination, registry, settings
from backend.core.errors import Conflict, Invalid, NotFound
from backend.core.platform import keys
from backend.core.requests import github

if TYPE_CHECKING:
    from backend.core.auth.deps import User

LABEL = "request"
MAX_TITLE = 200
MAX_DESCRIPTION = 10_000
_SELECT = """SELECT r.id, r.issue_number, r.issue_url, r.state, r.title, r.app, r.description, r.labels,
                    r.created_by, u.name AS requested_by_name, r.created_at, r.updated_at
               FROM core_requests r LEFT JOIN core_users u ON u.id = r.created_by"""


def _row(r) -> dict:
    return {
        "id": r["id"], "issue_number": r["issue_number"], "url": r["issue_url"], "state": r["state"],
        "title": r["title"], "app": r["app"] or "core", "description": r["description"],
        "labels": json.loads(r["labels"]),
        "requested_by": {"id": r["created_by"], "name": r["requested_by_name"]} if r["created_by"] is not None else None,
        "created_at": r["created_at"], "updated_at": r["updated_at"],
    }  # fmt: skip


def _credentials() -> tuple[str, str] | None:
    repo, token = keys.get("github.repo"), settings.get_setting("github.token")
    return (repo, token) if repo and token else None


def config() -> dict:
    return {
        "configured": _credentials() is not None,
        "warning_text": keys.get("requests.warning_text"),
        "repo": keys.get("github.repo") or None,
    }


def _app_name(slug: str) -> str:
    if slug == "core":
        return "Core platform"
    try:
        return registry.get_app(slug).manifest.name
    except NotFound:
        raise Invalid(f"app: {slug!r} is not an installed app") from None


def record_in(conn: db.Conn, user_id: int, app: str, description: str, issue: dict) -> dict:
    """Store the issue GitHub just created."""
    now = clock.now_iso()
    cur = conn.execute(
        """INSERT INTO core_requests (title, app, description, issue_number, issue_url, state, labels, created_by,
                                      created_at, updated_at, synced_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            issue["title"],
            None if app == "core" else app,
            description,
            issue["number"],
            issue["html_url"],
            issue.get("state", "open"),
            json.dumps([lb["name"] for lb in issue.get("labels", [])]),
            user_id,
            now,
            clock.normalize(issue["updated_at"]) if issue.get("updated_at") else now,
            now,
        ),
    )
    return _row(conn.execute(f"{_SELECT} WHERE r.id = ?", (cur.lastrowid,)).fetchone())


def create(user: User, title: str, app: str, description: str) -> dict:
    title, app, description = (title or "").strip(), (app or "core").strip(), (description or "").strip()
    if not title or len(title) > MAX_TITLE:
        raise Invalid(f"title: must be 1-{MAX_TITLE} characters")
    if len(description) > MAX_DESCRIPTION:
        raise Invalid(f"description: must be at most {MAX_DESCRIPTION} characters")
    app_name = _app_name(app)
    credentials = _credentials()
    if credentials is None:
        raise Conflict("github_not_configured")
    body = f"**Requested by:** {user.name or user.email}\n**App:** {app_name} (`{app}`)\n\n{description or '_No description._'}"
    issue = github.create_issue(*credentials, title, body, [LABEL, f"app:{app}"])
    with db.transaction() as conn:
        return record_in(conn, user.id, app, description, issue)


def list_requests(state: str = "open", limit: int | None = None, offset: int | None = None) -> list[dict]:
    """Newest first. `state` is open, closed or all."""
    limit, offset = pagination.window(limit, offset)
    where, params = ("", ()) if state == "all" else ("WHERE r.state = ?", (state,))
    rows = db.get_conn().execute(
        f"{_SELECT} {where} ORDER BY r.created_at DESC, r.id DESC LIMIT ? OFFSET ?", (*params, limit, offset)
    )
    return [_row(r) for r in rows]


def refresh_in(conn: db.Conn, issues: list[dict], synced_at: str) -> int:
    """Apply GitHub's state, title and updated_at to the stored rows; returns how many changed."""
    changed = 0
    for issue in issues:
        updated_at = clock.normalize(issue["updated_at"])
        changed += conn.execute(
            """UPDATE core_requests SET state = ?, title = ?, updated_at = ?
                WHERE issue_number = ? AND (state != ? OR title != ? OR updated_at != ?)""",
            (issue["state"], issue["title"], updated_at, issue["number"], issue["state"], issue["title"], updated_at),
        ).rowcount
    conn.execute("UPDATE core_requests SET synced_at = ? WHERE issue_number IS NOT NULL", (synced_at,))
    return changed


def refresh(cancel: threading.Event | None = None) -> int:
    """Sync the board from GitHub: one paginated list call, then one write."""
    credentials = _credentials()
    if credentials is None:
        raise Conflict("github_not_configured")
    started = clock.now_iso()
    issues = github.list_issues(*credentials, LABEL, cancel)
    with db.transaction() as conn:
        return refresh_in(conn, issues, started)
