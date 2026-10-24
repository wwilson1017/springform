"""Settings, workspace, apps admin, jobs and the change log, behind the routes in router.py.

Writers come as `fn(...)` (own transaction) and `fn_in(conn, ...)`. Change-log rows are copies
of record data, so every row is checked against the record's current `can_read` when listed.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from backend.core import VERSION, db, entities, pagination, registry, scheduler, settings
from backend.core.errors import Invalid, NotFound
from backend.core.platform import keys

if TYPE_CHECKING:
    from backend.core.auth.deps import User

# ── Settings and workspace ────────────────────────────────────────────────────


def settings_view() -> dict:
    """`values` and `defaults` for plain keys; `secrets` says only whether a secret is set."""
    spec = keys.known()
    stored = {r["key"]: r for r in db.rows("SELECT key, value, is_secret FROM core_settings")}
    values, secrets_, defaults = {}, {}, {}
    for key in sorted(set(spec) | set(stored)):
        k, row = spec.get(key), stored.get(key)
        if (k and k.secret) or (row and row["is_secret"]):
            secrets_[key] = bool(row and row["value"])
            continue
        values[key] = settings.get_setting(key, k.default if k else None)
        if k:
            defaults[key] = k.default
    return {"values": values, "secrets": secrets_, "defaults": defaults}


def update_settings_in(conn: db.Conn, user_id: int, values: dict[str, Any]) -> None:
    """Validate every key first, so one bad value writes nothing."""
    cleaned = {key: keys.clean(key, value) for key, value in values.items()}
    spec = keys.known()
    for key, value in cleaned.items():
        settings.set_setting_in(conn, key, value, user_id, is_secret=spec[key].secret)


def update_settings(user_id: int, values: dict[str, Any]) -> dict:
    with db.transaction() as conn:
        update_settings_in(conn, user_id, values)
    return settings_view()


def reset_setting_in(conn: db.Conn, key: str) -> None:
    if key not in keys.known():
        raise Invalid(f"unknown setting {key!r}")
    conn.execute("DELETE FROM core_settings WHERE key = ?", (key,))


def reset_setting(key: str) -> dict:
    with db.transaction() as conn:
        reset_setting_in(conn, key)
    return settings_view()


def workspace() -> dict:
    return {
        "name": keys.get("workspace.name"),
        "timezone": keys.get("timezone"),
        "version": VERSION,
        "preview": settings.preview_mode(),
    }


# ── Apps: hide and order ──────────────────────────────────────────────────────


def set_hidden_in(conn: db.Conn, slug: str, hidden: bool) -> None:
    registry.get_app(slug)  # 404 for an app that is not installed
    conn.execute(
        """INSERT INTO core_apps_state (slug, hidden) VALUES (?, ?)
           ON CONFLICT (slug) DO UPDATE SET hidden = excluded.hidden""",
        (slug, int(hidden)),
    )


def set_hidden(slug: str, hidden: bool) -> None:
    with db.transaction() as conn:
        set_hidden_in(conn, slug, hidden)


def set_order_in(conn: db.Conn, slugs: list[str]) -> None:
    """Listed apps take positions 0..n-1; unlisted apps fall back to their manifest order, after them."""
    installed = {a.slug for a in registry.installed()}
    if unknown := [s for s in slugs if s not in installed]:
        raise Invalid(f"not installed: {', '.join(unknown)}")
    if len(set(slugs)) != len(slugs):
        raise Invalid("an app is listed twice")
    conn.execute("UPDATE core_apps_state SET position = NULL")
    for position, slug in enumerate(slugs):
        conn.execute(
            """INSERT INTO core_apps_state (slug, position) VALUES (?, ?)
               ON CONFLICT (slug) DO UPDATE SET position = excluded.position""",
            (slug, position),
        )


def set_order(slugs: list[str]) -> None:
    with db.transaction() as conn:
        set_order_in(conn, slugs)


# ── Jobs ──────────────────────────────────────────────────────────────────────

_RUN_COLUMNS = "id, job, app, trigger, status, scheduled_for, started_at, finished_at, error"


def jobs_list() -> list[dict]:
    """Registered jobs with their latest run. `in_flight` is read from core_job_runs (a run row
    with no finish); a manual run still waiting for a scheduler slot is not yet in flight there."""
    latest = {
        r["job"]: r
        for r in db.rows(
            f"SELECT {_RUN_COLUMNS} FROM core_job_runs WHERE id IN (SELECT max(id) FROM core_job_runs GROUP BY job)"
        )
    }
    running = {
        r["job"]
        for r in db.rows(
            "SELECT DISTINCT job FROM core_job_runs WHERE status IN ('running', 'timed_out') AND finished_at IS NULL"
        )
    }
    out = []
    for name, job in sorted(scheduler.jobs().items()):
        last = latest.get(name)
        out.append({
            "name": name, "app": job.app, "every": job.every, "at": job.at, "timeout": job.timeout,
            "last_run": {k: last[k] for k in ("status", "started_at", "finished_at", "error")} if last else None,
            "in_flight": name in running,
        })  # fmt: skip
    return out


def job_runs(job: str | None = None, limit: int | None = None) -> list[dict]:
    """Newest first."""
    limit, _ = pagination.window(limit)
    where, params = ("WHERE job = ?", (job,)) if job else ("", ())
    return db.rows(f"SELECT {_RUN_COLUMNS} FROM core_job_runs {where} ORDER BY id DESC LIMIT ?", (*params, limit))


def dead_outbox(limit: int | None = None) -> list[dict]:
    """Outbox rows that failed for good. The payload is left out: it can hold record data."""
    limit, _ = pagination.window(limit)
    return db.rows(
        """SELECT id, hook, attempts, last_error, created_at, dead_at FROM core_outbox
            WHERE dead_at IS NOT NULL ORDER BY id DESC LIMIT ?""",
        (limit,),
    )


# ── Change log ────────────────────────────────────────────────────────────────

_SCAN_BATCH = 200
_CHANGELOG_SELECT = """SELECT c.id, c.at, c.user_id, u.name AS user_name, c.app, c.entity, c.entity_id, c.field,
                              c.old, c.new, c.reason, c.deleted_at
                         FROM core_change_log c LEFT JOIN core_users u ON u.id = c.user_id"""


def _access(user: User, conn: db.Conn, entity_type: str, entity_id: int, deleted_at: str | None) -> str:
    """ "live" (readable record), "gone" (deleted record or uninstalled type: admins only), or "hidden"."""
    known = any(e.type == entity_type for e in entities.all_entities())
    if deleted_at or not known or not entities.exists(conn, entity_type, entity_id):
        return "gone" if user.is_admin else "hidden"
    try:
        entities.authorize(user, conn, entity_type, entity_id, "read")
    except NotFound:
        return "hidden"
    return "live"


def changelog_list(
    user: User,
    *,
    app: str | None = None,
    user_id: int | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    before: int | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Newest first. `before` is the id cursor: pass the last row's id to get the next page.
    Rows the caller may not read are skipped, and the scan continues until the page is full."""
    # simplification: a caller who can read little of a large log scans it all in one request;
    # upgrade path: cap the scan and return an explicit next cursor with the page.
    limit, _ = pagination.window(limit)
    conn = db.get_conn()
    filters = [("c.app", app), ("c.user_id", user_id), ("c.entity", entity_type), ("c.entity_id", entity_id)]
    where = [f"{col} = ?" for col, value in filters if value is not None]
    params = [value for _, value in filters if value is not None]
    access: dict[tuple[str, int], str] = {}
    page: list[tuple[dict, str]] = []
    cursor = before
    while len(page) < limit:
        conds = where + (["c.id < ?"] if cursor is not None else [])
        batch = conn.execute(
            f"{_CHANGELOG_SELECT} {'WHERE ' + ' AND '.join(conds) if conds else ''} ORDER BY c.id DESC LIMIT ?",
            (*params, *([cursor] if cursor is not None else []), _SCAN_BATCH),
        ).fetchall()
        for row in batch:
            key = (row["entity"], row["entity_id"])
            if key not in access:
                access[key] = _access(user, conn, *key, row["deleted_at"])
            if access[key] != "hidden":
                page.append((dict(row), access[key]))
                if len(page) == limit:
                    break
        if len(batch) < _SCAN_BATCH:
            break
        cursor = batch[-1]["id"]

    titles: dict[str, dict[int, str]] = {}
    for entity_type_ in {r["entity"] for r, a in page if a == "live"}:
        ids = [r["entity_id"] for r, a in page if a == "live" and r["entity"] == entity_type_]
        titles[entity_type_] = entities.titles_for(user, conn, entity_type_, ids)
    return [
        {
            "id": r["id"], "at": r["at"],
            "user": {"id": r["user_id"], "name": r["user_name"]} if r["user_id"] is not None else None,
            "app": r["app"], "entity_type": r["entity"], "entity_id": r["entity_id"],
            "title": titles.get(r["entity"], {}).get(r["entity_id"]),
            "url": entities.url_for(r["entity"], r["entity_id"]) if a == "live" else None,
            "field": r["field"],
            "old": json.loads(r["old"]) if r["old"] is not None else None,
            "new": json.loads(r["new"]) if r["new"] is not None else None,
            "reason": r["reason"], "deleted_at": r["deleted_at"],
        }
        for r, a in page
    ]  # fmt: skip
