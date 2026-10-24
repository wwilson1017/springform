"""Todos: per-user GTD with private and team rows. Lifted from todo-gtd's service.py
(docs/PROVENANCE.md), where one list was the account; here every row has an owner and a visibility.

Who sees what (entities.py gives core the same rule):
- a private row (todo, project or area) is its owner's alone: read, write, complete;
- a team row is every active member's to view, edit, complete and reassign;
- admins see team rows and their own, never another person's private ones.
`visible(alias)` is that rule in SQL. Making a row private is its owner's call; giving a row to
someone else, or deleting it, is its owner's or an admin's. A private row's assignee is nobody
or its owner.

The hierarchy rule (`_guard_in`): a child sits only under a parent that everyone who sees the
child can see. A team child needs a team parent or none; a private child needs a team parent or a
private one of the same owner. Checked from the child on create, move, owner and visibility
change, and from the parent when it goes private or changes hands.

The change feed: each write stamps the row in todos_journal once per audience it was in before
and is in after (0 = the team, else the owner) and moves that audience's head in todos_sync, so
a team edit advances every member's feed and a private edit only its owner's. `changes()` reads
the team's and the caller's journal: a row the caller can still see comes back whole, any other
is a tombstone.

"Today" is the user's calendar date in their own timezone, else the install's. Every write has
an `_in(conn, …)` form; the plain form opens the transaction.
"""

from __future__ import annotations

import datetime
import json
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from backend.apps.todos.common import (
    AREA_FIELDS,
    AREA_STATUSES,
    FINISHED,
    ITEM_FIELDS,
    MAX_BULK,
    MAX_SHORT_CHARS,
    MAX_TEXT_CHARS,
    PROJECT_FIELDS,
    PROJECT_STATUSES,
    REVIEW_EVERY_DAYS,
    REVIEW_STALE_DAYS,
    REVIEW_UPCOMING_DAYS,
    SOURCES,
    TODO_STATUSES,
    VISIBILITIES,
    check_fields,
    choice,
    flag,
    next_due,
    ref,
    required_text,
    validate_due,
    validate_notes,
    validate_people,
    validate_repeat,
    validate_short,
    validate_tags,
)
from backend.core import clock, db, entities, localtime, settings
from backend.core.errors import Conflict, Forbidden, Invalid, NotFound
from backend.core.timeline import api as timeline

if TYPE_CHECKING:
    from backend.core.auth.deps import User

ENTITY = "todos.item"
TABLES = {"item": "todos_items", "project": "todos_projects", "area": "todos_areas"}
KIND_OF = {table: kind for kind, table in TABLES.items()}
NOUNS = {"item": "todo", "project": "project", "area": "area"}
PLURAL = {"item": "items", "project": "projects", "area": "areas"}
_ALIAS = {"item": "t", "project": "p", "area": "a"}
_PARENTS = {"item": (("project_id", "project"), ("area_id", "area")), "project": (("area_id", "area"),), "area": ()}
_CHILDREN = {
    "item": (),
    "project": (("todos_items", "project_id"),),
    "area": (("todos_projects", "area_id"), ("todos_items", "area_id")),
}


def visible(alias: str) -> str:
    """The read rule in SQL; bind the user's id."""
    return f"({alias}.visibility = 'team' OR {alias}.owner_user_id = ?)"


# A user's work: their private todos, team todos assigned to them, and the team's unassigned
# ones. Today, the review and the badge read this; bind the user's id twice.
WORK = (
    "((t.visibility = 'private' AND t.owner_user_id = ?)"
    " OR (t.visibility = 'team' AND (t.assignee_user_id = ? OR t.assignee_user_id IS NULL)))"
)
# Not waiting on a revisit date; bind today. A todo deferred to a later `revisit_on` is off the
# working lists (list, Today, counts, the review's copies of those) until that day. Record views,
# search, a project's open count and the review's `upcoming` still see it.
NOT_DEFERRED = "(t.revisit_on IS NULL OR t.revisit_on <= ?)"

_EFFECTIVE_AREA = "COALESCE(t.area_id, p.area_id)"  # a todo shows its project's area unless it has its own
_SELECT = {
    "item": f"""SELECT t.*, p.name AS project_name, {_EFFECTIVE_AREA} AS effective_area_id, a.name AS area_name,
                       o.name AS owner_name, s.name AS assignee_name
                  FROM todos_items t
                  LEFT JOIN todos_projects p ON p.id = t.project_id
                  LEFT JOIN todos_areas a ON a.id = {_EFFECTIVE_AREA}
                  LEFT JOIN core_users o ON o.id = t.owner_user_id
                  LEFT JOIN core_users s ON s.id = t.assignee_user_id""",
    # open_count counts only the todos this user can see; bind the user's id first.
    "project": f"""SELECT p.*, a.name AS area_name,
                          (SELECT count(*) FROM todos_items t WHERE t.project_id = p.id
                              AND t.status NOT IN ('done', 'dropped') AND {visible('t')}) AS open_count
                     FROM todos_projects p LEFT JOIN todos_areas a ON a.id = p.area_id""",
    "area": "SELECT a.* FROM todos_areas a",
}


# ── Shared helpers ────────────────────────────────────────────────────────────


def zone(user: User) -> ZoneInfo:
    if user.tz:
        try:
            return ZoneInfo(user.tz)
        except (ValueError, KeyError):  # ZoneInfoNotFoundError is a KeyError
            pass
    return localtime.tz()


def today(user: User) -> datetime.date:
    return clock.now().astimezone(zone(user)).date()


def default_visibility() -> str:
    value = settings.get_setting("todos.default_visibility")
    return value if value in VISIBILITIES else "private"


def _write(fn, *args, **kwargs):
    with db.transaction() as conn:
        return fn(conn, *args, **kwargs)


def _shape(kind: str, row) -> dict:
    d = dict(row)
    if kind == "item":
        d["tags"], d["people"] = json.loads(d["tags"] or "[]"), json.loads(d["people"] or "[]")
        d["star"], d["auto_star_on_due"] = bool(d["star"]), bool(d["auto_star_on_due"])
    return d


def _rows_in(conn: db.Conn, user: User, kind: str, where: str = "1", params=(), tail: str = "") -> list[dict]:
    """Rows of `kind` the user can see that match `where`."""
    lead = (user.id,) if kind == "project" else ()
    sql = f"{_SELECT[kind]} WHERE {visible(_ALIAS[kind])} AND ({where}) {tail}"
    return [_shape(kind, r) for r in conn.execute(sql, (*lead, user.id, *params))]


def _fetch_in(conn: db.Conn, user: User, kind: str, row_id: int) -> dict:
    """One row, whoever can see it: what a writer gets back after giving a row away."""
    lead = (user.id,) if kind == "project" else ()
    return _shape(kind, conn.execute(f"{_SELECT[kind]} WHERE {_ALIAS[kind]}.id = ?", (*lead, row_id)).fetchone())


def _raw_in(conn: db.Conn, kind: str, row_id: int) -> dict | None:
    row = conn.execute(f"SELECT * FROM {TABLES[kind]} WHERE id = ?", (row_id,)).fetchone()
    return dict(row) if row else None


def _readable(user: User, row: dict) -> bool:
    return row["visibility"] == "team" or row["owner_user_id"] == user.id


def _insert_in(conn: db.Conn, table: str, row: dict) -> int:
    cols = ", ".join(row)
    return conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({', '.join('?' * len(row))})", tuple(row.values())).lastrowid


def _save_in(conn: db.Conn, kind: str, row: dict) -> None:
    cols = [k for k in row if k not in ("id", "rev", "created_at", "source")]
    conn.execute(
        f"UPDATE {TABLES[kind]} SET {', '.join(f'{k} = ?' for k in cols)} WHERE id = ?",
        (*(row[k] for k in cols), row["id"]),
    )


def _human_in(conn: db.Conn, user_id, field: str) -> int:
    """An active person: admin or member, never the system principal."""
    uid = ref(user_id, field)
    if uid is None or not conn.execute(
        "SELECT 1 FROM core_users WHERE id = ? AND is_active = 1 AND role IN ('admin', 'member')", (uid,)
    ).fetchone():
        raise Invalid(f"{field}: no such active user")
    return uid


def _set_shared(row: dict, fields: dict) -> None:
    if "visibility" in fields:
        row["visibility"] = choice(fields["visibility"], VISIBILITIES, "visibility")
    if "owner_user_id" in fields:
        if (owner := ref(fields["owner_user_id"], "owner_user_id")) is None:
            raise Invalid("owner_user_id cannot be empty")
        row["owner_user_id"] = owner
    if "assignee_user_id" in fields:
        row["assignee_user_id"] = ref(fields["assignee_user_id"], "assignee_user_id")


def _guard_in(conn: db.Conn, user: User, kind: str, before: dict | None, after: dict) -> None:
    """May `user` turn `before` into `after` (None before: a create), and does the result keep the
    hierarchy rule? Raises Forbidden (403) or Invalid (422)."""
    noun, owner, vis = NOUNS[kind], after["owner_user_id"], after["visibility"]
    if before is None:
        if owner != user.id and vis != "team" and not user.is_admin:
            raise Forbidden(f"Only an admin can make a private {noun} for someone else.")
        moved = owner != user.id
    else:
        moved = owner != before["owner_user_id"]
        if moved and user.id != before["owner_user_id"] and not user.is_admin:
            raise Forbidden(f"Only the owner or an admin can give this {noun} to someone else.")
        if vis == "private" and before["visibility"] == "team" and user.id != before["owner_user_id"]:
            raise Forbidden(f"Only the owner can make this {noun} private.")
    if moved or vis == "private":
        _human_in(conn, owner, "owner_user_id")
    assignee = after["assignee_user_id"]
    if assignee is not None and (before is None or assignee != before["assignee_user_id"]):
        _human_in(conn, assignee, "assignee_user_id")
    if vis == "private" and assignee not in (None, owner):
        raise Invalid(f"A private {noun} can only be assigned to its owner.")

    widened = before is None or vis != before["visibility"] or moved
    for field, pkind in _PARENTS[kind]:
        if after[field] is not None and (widened or after[field] != before[field]):
            _check_parent_in(conn, user, kind, after, field, pkind)
    if before is not None and widened and vis == "private":
        for table, field in _CHILDREN[kind]:
            if conn.execute(
                f"SELECT 1 FROM {table} WHERE {field} = ? AND NOT (visibility = 'private' AND owner_user_id = ?) LIMIT 1",
                (after["id"], owner),
            ).fetchone():
                held = "todos" if kind == "project" else "projects or todos"
                raise Invalid(f"This {noun} holds team or someone else's {held}; move them out before it goes private or changes hands.")


def _check_parent_in(conn: db.Conn, user: User, kind: str, child: dict, field: str, pkind: str) -> None:
    parent = _raw_in(conn, pkind, child[field])
    if parent is None or not _readable(user, parent):
        raise Invalid(f"{field}: no such {pkind}")
    if parent["visibility"] == "team" or (
        child["visibility"] == "private" and parent["owner_user_id"] == child["owner_user_id"]
    ):
        return
    noun = NOUNS[kind]
    if child["visibility"] == "team":
        raise Invalid(f"A team {noun} can only sit in a team {pkind}.")
    raise Invalid(f"A private {noun} can only sit in a team {pkind} or one of its owner's private {pkind}s.")


def _check_deleter(user: User, row: dict, noun: str) -> None:
    if row["owner_user_id"] != user.id and not user.is_admin:
        raise Forbidden(f"Only the owner or an admin can delete this {noun}.")


def _audience(row: dict) -> int:
    return 0 if row["visibility"] == "team" else row["owner_user_id"]


def _stamp_in(conn: db.Conn, kind: str, row_id: int, *states: dict) -> int:
    """Record a change to one row for every audience among `states` (before, then after, so the
    row's rev is its current audience's), and move each audience's head. Returns the rev."""
    rev = 0
    for audience in dict.fromkeys(_audience(s) for s in states):
        rev = conn.execute(
            "INSERT OR REPLACE INTO todos_journal (kind, row_id, audience) VALUES (?, ?, ?)", (kind, row_id, audience)
        ).lastrowid
        # The team row is made by the first stamp after install or an app reset; its floor marks that.
        conn.execute("INSERT INTO todos_sync (user_id, floor) VALUES (0, ?) ON CONFLICT (user_id) DO NOTHING", (rev - 1,))
        conn.execute(
            "INSERT INTO todos_sync (user_id, rev) VALUES (?, ?) ON CONFLICT (user_id) DO UPDATE SET rev = excluded.rev",
            (audience, rev),
        )
    conn.execute(f"UPDATE {TABLES[kind]} SET rev = ? WHERE id = ?", (rev, row_id))
    return rev


def _check_link_in(conn: db.Conn, user: User, row: dict) -> None:
    if (row["entity_type"] is None) != (row["entity_id"] is None):
        raise Invalid("entity_type and entity_id are set together")
    if row["entity_type"] is not None:
        try:
            entities.authorize(user, conn, row["entity_type"], row["entity_id"], "read")
        except NotFound:
            raise Invalid("entity: no such record") from None


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# ── Todos ─────────────────────────────────────────────────────────────────────


def create_item_in(
    conn: db.Conn,
    user: User,
    title: str,
    *,
    notes: str = "",
    project_id: int | None = None,
    area_id: int | None = None,
    context: str = "",
    tags: list[str] | None = None,
    people: list[str] | None = None,
    status: str = "inbox",
    star=False,
    due_date: str | None = None,
    revisit_on: str | None = None,
    repeat: str = "",
    auto_star_on_due=False,
    visibility: str | None = None,
    owner_user_id: int | None = None,
    assignee_user_id: int | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    source: str = "ui",
) -> dict:
    """Validate and insert one todo. Returns it, even to an admin who made a private todo for
    someone else and cannot read it afterwards."""
    now = clock.now_iso()
    status = choice(status, TODO_STATUSES, "status")
    row = {
        "title": required_text(title, "title", "title is required", MAX_TEXT_CHARS),
        "owner_user_id": ref(owner_user_id, "owner_user_id") or user.id,
        "visibility": choice(visibility or default_visibility(), VISIBILITIES, "visibility"),
        "assignee_user_id": ref(assignee_user_id, "assignee_user_id"),
        "notes": validate_notes(notes),
        "project_id": ref(project_id, "project_id"),
        "area_id": ref(area_id, "area_id"),
        "context": validate_short(context, "context"),
        "tags": validate_tags(tags),
        "people": validate_people(people),
        "status": status,
        "star": flag(star, "star"),
        "due_date": validate_due(due_date),
        "revisit_on": validate_due(revisit_on, "revisit_on"),
        "repeat": validate_repeat(repeat),
        "auto_star_on_due": flag(auto_star_on_due, "auto_star_on_due"),
        "entity_type": entity_type or None,
        "entity_id": ref(entity_id, "entity_id"),
        "source": choice(source, SOURCES, "source"),
        "created_at": now,
        "updated_at": now,
        "completed_at": now if status == "done" else None,
    }
    _guard_in(conn, user, "item", None, row)
    _check_link_in(conn, user, row)
    item_id = _insert_in(conn, "todos_items", row)
    _stamp_in(conn, "item", item_id, row)
    return _fetch_in(conn, user, "item", item_id)


def create_item(user: User, title: str, **fields) -> dict:
    return _write(create_item_in, user, title, **fields)


def get_item_in(conn: db.Conn, user: User, item_id: int) -> dict:
    entities.authorize(user, conn, ENTITY, item_id, "read")
    return _fetch_in(conn, user, "item", item_id)


def get_item(user: User, item_id: int) -> dict:
    return get_item_in(db.get_conn(), user, item_id)


def _apply_update_in(conn: db.Conn, user: User, item_id: int, fields: dict) -> bool:
    """Apply a validated update to one todo; False when the user cannot see it. Completing a
    repeating todo spawns its next occurrence in the same transaction, so two completes
    serialize and only the first spawns."""
    try:
        entities.authorize(user, conn, ENTITY, item_id, "write")
    except NotFound:
        return False
    before = _raw_in(conn, "item", item_id)
    after = dict(before)
    now = clock.now_iso()
    if "title" in fields:
        after["title"] = required_text(fields["title"], "title", "title cannot be empty", MAX_TEXT_CHARS)
    if "notes" in fields:
        after["notes"] = validate_notes(fields["notes"])
    for key in ("project_id", "area_id", "entity_id"):
        if key in fields:
            after[key] = ref(fields[key], key)
    if "entity_type" in fields:
        after["entity_type"] = fields["entity_type"] or None
    if "context" in fields:
        after["context"] = validate_short(fields["context"], "context")
    if "tags" in fields:
        after["tags"] = validate_tags(fields["tags"])
    if "people" in fields:
        after["people"] = validate_people(fields["people"])
    for key in ("star", "auto_star_on_due"):
        if key in fields:
            after[key] = flag(fields[key], key)
    for key in ("due_date", "revisit_on"):
        if key in fields:
            after[key] = validate_due(fields[key], key)
    if "repeat" in fields:
        after["repeat"] = validate_repeat(fields["repeat"])
    _set_shared(after, fields)
    just_completed = False
    if "status" in fields:
        after["status"] = choice(fields["status"], TODO_STATUSES, "status")
        if after["status"] != "done":
            after["completed_at"] = None
        elif before["status"] != "done":
            after["completed_at"], just_completed = now, True
    _guard_in(conn, user, "item", before, after)
    if (after["entity_type"], after["entity_id"]) != (before["entity_type"], before["entity_id"]):
        _check_link_in(conn, user, after)
    after["updated_at"] = now
    _save_in(conn, "item", after)
    _stamp_in(conn, "item", item_id, before, after)
    tracked = [{k: v for k, v in r.items() if k != "rev"} for r in (before, after)]
    timeline.record_changes_in(conn, ENTITY, item_id, *tracked, user.id)
    if just_completed:
        _spawn_next_occurrence_in(conn, user, after, before["status"])
    return True


def _spawn_next_occurrence_in(conn: db.Conn, user: User, todo: dict, prior_status: str) -> None:
    """Completing a repeating todo creates its next occurrence: the same fields (visibility,
    owner, assignee and record link included), due date advanced, star cleared. Reads the
    post-update row, so edits saved with the completion carry and clearing `repeat` while
    completing does not spawn.

    The one exception to the cleared star is the opt-in `auto_star_on_due`: when the new
    occurrence is due today, i.e. this one was completed exactly one interval late, it comes
    back starred. The revisit date belongs to the finished occurrence and is not copied."""
    if not todo["repeat"]:
        return
    day = today(user)  # one clock read, shared with the auto-star comparison
    due = next_due(todo["repeat"], todo["due_date"], day)
    now = clock.now_iso()
    keep = ("owner_user_id", "visibility", "assignee_user_id", "title", "notes", "project_id", "area_id", "context",
            "tags", "people", "repeat", "auto_star_on_due", "entity_type", "entity_id", "source")  # fmt: skip
    row = {k: todo[k] for k in keep}
    row.update(
        status=prior_status if prior_status not in FINISHED else "next_action",
        star=int(bool(todo["auto_star_on_due"]) and due == day.isoformat()),
        due_date=due,
        created_at=now,
        updated_at=now,
    )
    _stamp_in(conn, "item", _insert_in(conn, "todos_items", row), row)


def update_item_in(conn: db.Conn, user: User, item_id: int, fields: dict) -> dict:
    """Change the fields given; an explicit None clears a field that may be empty."""
    check_fields(fields, ITEM_FIELDS)
    if not _apply_update_in(conn, user, item_id, fields):
        raise NotFound("Todo not found")
    return _fetch_in(conn, user, "item", item_id)


def update_item(user: User, item_id: int, fields: dict) -> dict:
    return _write(update_item_in, user, item_id, fields)


def complete_in(conn: db.Conn, user: User, item_id: int) -> dict:
    if not _apply_update_in(conn, user, item_id, {"status": "done"}):
        raise NotFound("Todo not found")
    return _fetch_in(conn, user, "item", item_id)


def complete(user: User, item_id: int) -> dict:
    return _write(complete_in, user, item_id)


def bulk_update_in(conn: db.Conn, user: User, ids: list[int], fields: dict) -> dict:
    """The same update on many todos, all or nothing: a bad field or a refused change rolls the
    batch back. One update per id, so each repeating todo in a bulk complete spawns its own next
    occurrence. Ids the user cannot see are reported in `not_found`."""
    check_fields(fields, ITEM_FIELDS)
    if not ids:
        raise Invalid("ids is required")
    if len(ids) > MAX_BULK:
        raise Invalid(f"too many ids (max {MAX_BULK})")
    try:
        id_list = sorted({int(i) for i in ids})
    except (TypeError, ValueError):
        raise Invalid("ids must be integers") from None
    updated: list[int] = []
    not_found: list[int] = []
    for item_id in id_list:
        (updated if _apply_update_in(conn, user, item_id, fields) else not_found).append(item_id)
    return {"updated": updated, "not_found": not_found}


def bulk_update(user: User, ids: list[int], fields: dict) -> dict:
    return _write(bulk_update_in, user, ids, fields)


def delete_item_in(conn: db.Conn, user: User, item_id: int) -> None:
    """Delete a todo for good (archiving is status 'dropped'): the owner's or an admin's call.
    Core's delete subscribers take its timeline and files; hooks.py writes the tombstone."""
    entities.authorize(user, conn, ENTITY, item_id, "write")
    _check_deleter(user, _raw_in(conn, "item", item_id), "todo")
    entities.delete_record_in(conn, ENTITY, item_id)


def delete_item(user: User, item_id: int) -> None:
    _write(delete_item_in, user, item_id)


def list_items(
    user: User,
    status: str | None = None,
    project_id: int | None = None,
    area_id: int | None = None,
    context: str | None = None,
    tag: str | None = None,
    person: str | None = None,
    starred: bool | None = None,
    due_before: str | None = None,
    due_after: str | None = None,
    search: str | None = None,
    assignee_user_id: int | None = None,
    visibility: str | None = None,
    mine: bool = False,
    include_deferred: bool = False,
    limit: int | None = 100,
    offset: int = 0,
) -> list[dict]:
    """Todos the user can see. `mine` narrows to their work (WORK). Every ordering ends in t.id,
    so paging by offset over an unchanged list neither skips nor repeats a row."""
    where: list[str] = ["1"]
    params: list = []

    def add(clause: str, *values) -> None:
        where.append(clause)
        params.extend(values)

    if status:
        add("t.status = ?", choice(status, TODO_STATUSES, "status"))
    if project_id is not None:
        add("t.project_id = ?", project_id)
    if area_id is not None:
        add(f"{_EFFECTIVE_AREA} = ?", area_id)
    if context:
        add("lower(t.context) = lower(?)", context.strip())
    if tag:
        add("EXISTS (SELECT 1 FROM json_each(t.tags) WHERE value = ?)", tag)
    if person:
        add("EXISTS (SELECT 1 FROM json_each(t.people) WHERE value = ?)", person)
    if starred is not None:
        add("t.star = ?", 1 if starred else 0)
    if due_before:
        add("t.due_date IS NOT NULL AND t.due_date <= ?", validate_due(due_before, "due_before"))
    if due_after:
        add("t.due_date IS NOT NULL AND t.due_date >= ?", validate_due(due_after, "due_after"))
    if assignee_user_id is not None:
        add("t.assignee_user_id = ?", assignee_user_id)
    if visibility:
        add("t.visibility = ?", choice(visibility, VISIBILITIES, "visibility"))
    if mine:
        add(WORK, user.id, user.id)
    if search:
        if len(search) > MAX_SHORT_CHARS:
            raise Invalid(f"Search too long (max {MAX_SHORT_CHARS} characters)")
        # simplification: LIKE folds case for ASCII only; move to FTS5 if accents matter
        esc = f"%{_escape_like(search)}%"
        cols = ("t.title", "t.notes", "t.context", "t.tags", "t.people", "p.name")
        add("(" + " OR ".join(f"{c} LIKE ? ESCAPE '\\'" for c in cols) + ")", *[esc] * len(cols))
    elif not include_deferred:
        # A search still finds a deferred todo: that is how it is reached before its day.
        add(f"(t.status IN ('done', 'dropped') OR {NOT_DEFERRED})", today(user).isoformat())
    if status in FINISHED:  # newest finished first, or the window would freeze on the oldest
        order = "ORDER BY COALESCE(t.completed_at, t.updated_at) DESC, t.id DESC"
    elif search and not status:  # open before finished, so a repeat's live copy wins the window
        order = "ORDER BY (t.status IN ('done', 'dropped')) ASC, t.id DESC"
    else:
        order = "ORDER BY t.created_at ASC, t.id ASC"
    n = 100 if limit is None else int(limit)
    params += [max(1, min(n, 500)), max(0, int(offset or 0))]
    return _rows_in(db.get_conn(), user, "item", " AND ".join(where), params, f"{order} LIMIT ? OFFSET ?")


def today_view(user: User) -> list[dict]:
    """The daily home screen: the user's open work that is starred, due today or overdue, or
    whose revisit date has arrived, by their own calendar. A todo whose revisit date is still
    ahead stays hidden even when starred or due: "bring it back on X" means not before X.

    # simplification: an arrived revisit date keeps the todo on Today until it is completed or
    # the date is cleared; no auto-move to the inbox, no sweep job
    """
    day = today(user).isoformat()
    return _rows_in(
        db.get_conn(), user, "item",
        f"""t.status NOT IN ('done', 'dropped') AND {WORK} AND {NOT_DEFERRED}
            AND (t.star = 1 OR (t.due_date IS NOT NULL AND t.due_date <= ?) OR (t.revisit_on IS NOT NULL AND t.revisit_on <= ?))""",
        (user.id, user.id, day, day, day),
        "ORDER BY t.due_date ASC NULLS LAST, t.created_at ASC, t.id ASC",
    )  # fmt: skip


def list_for_record_in(conn: db.Conn, user: User, entity_type: str, entity_id: int, include_done: bool = False) -> list[dict]:
    """Team todos and the user's private ones linked to a record the user may read."""
    entities.authorize(user, conn, entity_type, entity_id, "read")
    done = "" if include_done else " AND t.status NOT IN ('done', 'dropped')"
    return _rows_in(conn, user, "item", f"t.entity_type = ? AND t.entity_id = ?{done}", (entity_type, entity_id),
                    "ORDER BY t.created_at, t.id")  # fmt: skip


def list_for_record(user: User, entity_type: str, entity_id: int, include_done: bool = False) -> list[dict]:
    return list_for_record_in(db.get_conn(), user, entity_type, entity_id, include_done)


def badge(user: User) -> dict:
    """The launcher tile: the user's inbox (private, or team assigned to them) plus the team's
    unassigned inbox, leaving out todos deferred to a later day."""
    n = db.get_conn().execute(
        f"SELECT count(*) FROM todos_items t WHERE t.status = 'inbox' AND {WORK} AND {NOT_DEFERRED}",
        (user.id, user.id, today(user).isoformat()),
    ).fetchone()[0]
    return {"count": n, "label": "Inbox"}


def rename_context_in(conn: db.Conn, user: User, old: str, new: str, *, merge: bool = False) -> dict:
    """Rename a context on every todo the user can see that carries it, finished ones included.
    Into a context that already exists the two would merge, which cannot be told apart after,
    so that waits for merge=True (409 until then). `updated_at` stays (the review's stale list
    reads it as "last touched"), but each row is stamped so a sync sees the rename."""
    old, new = validate_short(old, "context"), validate_short(new, "new name")
    if not old:
        raise Invalid("context is required")
    if not new:
        raise Invalid("new name cannot be empty")
    if old == new:
        raise Invalid(f'The context is already named "{new}"')
    rows = conn.execute(f"SELECT * FROM todos_items t WHERE {visible('t')} AND t.context = ?", (user.id, old)).fetchall()
    if not rows:
        raise NotFound("No todo you can see has that context")
    merged = conn.execute(
        f"SELECT 1 FROM todos_items t WHERE {visible('t')} AND t.context = ? LIMIT 1", (user.id, new)
    ).fetchone() is not None
    if merged and not merge:
        raise Conflict(f'You already have a context named "{new}". Merging moves every "{old}" to-do into it.')
    for row in rows:
        conn.execute("UPDATE todos_items SET context = ? WHERE id = ?", (new, row["id"]))
        _stamp_in(conn, "item", row["id"], dict(row))
    return {"old": old, "new": new, "updated": len(rows), "merged": merged}


def rename_context(user: User, old: str, new: str, *, merge: bool = False) -> dict:
    return _write(rename_context_in, user, old, new, merge=merge)


# ── Projects and areas ────────────────────────────────────────────────────────


def _container_in(conn: db.Conn, user: User, kind: str, row_id: int) -> dict:
    """The raw row of a project or area the user can see, else NotFound."""
    row = _raw_in(conn, kind, row_id)
    if row is None or not _readable(user, row):
        raise NotFound(f"{NOUNS[kind].capitalize()} not found")
    return row


def _check_name_in(conn: db.Conn, kind: str, row: dict) -> None:
    """Names are unique among the team's rows, and among each owner's private ones."""
    scope, params = ("visibility = 'team'", ()) if row["visibility"] == "team" else (
        "visibility = 'private' AND owner_user_id = ?", (row["owner_user_id"],))  # fmt: skip
    if conn.execute(
        f"SELECT 1 FROM {TABLES[kind]} WHERE lower(name) = lower(?) AND id != ? AND {scope}",
        (row["name"], row.get("id", 0), *params),
    ).fetchone():
        raise Invalid(f'{NOUNS[kind].capitalize()} "{row["name"]}" already exists')


def _new_container(user: User, name: str, notes: str, visibility: str | None, assignee_user_id) -> dict:
    now = clock.now_iso()
    return {
        "name": required_text(name, "name", "name is required"),
        "notes": validate_notes(notes),
        "owner_user_id": user.id,
        "visibility": choice(visibility or default_visibility(), VISIBILITIES, "visibility"),
        "assignee_user_id": ref(assignee_user_id, "assignee_user_id"),
        "created_at": now,
        "updated_at": now,
    }


def _add_container_in(conn: db.Conn, user: User, kind: str, row: dict) -> dict:
    _guard_in(conn, user, kind, None, row)
    _check_name_in(conn, kind, row)
    row_id = _insert_in(conn, TABLES[kind], row)
    _stamp_in(conn, kind, row_id, row)
    return _fetch_in(conn, user, kind, row_id)


def create_project_in(
    conn: db.Conn, user: User, name: str, *, notes: str = "", status: str = "active", purpose: str = "",
    outcome: str = "", area_id: int | None = None, visibility: str | None = None, assignee_user_id: int | None = None,
) -> dict:  # fmt: skip
    row = _new_container(user, name, notes, visibility, assignee_user_id)
    row.update(
        status=choice(status, PROJECT_STATUSES, "project status"),
        purpose=validate_notes(purpose, "purpose"),
        outcome=validate_notes(outcome, "outcome"),
        area_id=ref(area_id, "area_id"),
    )
    return _add_container_in(conn, user, "project", row)


def create_project(user: User, name: str, **fields) -> dict:
    return _write(create_project_in, user, name, **fields)


def create_area_in(
    conn: db.Conn, user: User, name: str, *, notes: str = "", visibility: str | None = None,
    assignee_user_id: int | None = None,
) -> dict:  # fmt: skip
    return _add_container_in(conn, user, "area", _new_container(user, name, notes, visibility, assignee_user_id))


def create_area(user: User, name: str, **fields) -> dict:
    return _write(create_area_in, user, name, **fields)


def get_container(user: User, kind: str, row_id: int) -> dict:
    conn = db.get_conn()
    _container_in(conn, user, kind, row_id)
    return _fetch_in(conn, user, kind, row_id)


def list_projects(user: User, status: str | None = None, area_id: int | None = None) -> list[dict]:
    where, params = ["1"], []
    if status:
        where.append("p.status = ?")
        params.append(choice(status, PROJECT_STATUSES, "project status"))
    if area_id is not None:
        where.append("p.area_id = ?")
        params.append(area_id)
    return _rows_in(db.get_conn(), user, "project", " AND ".join(where), params, "ORDER BY lower(p.name), p.id")


def list_areas(user: User, status: str | None = None) -> list[dict]:
    where, params = ("a.status = ?", (choice(status, AREA_STATUSES, "area status"),)) if status else ("1", ())
    return _rows_in(db.get_conn(), user, "area", where, params, "ORDER BY lower(a.name), a.id")


def update_container_in(conn: db.Conn, user: User, kind: str, row_id: int, fields: dict) -> dict:
    """Change a project or an area. Archive with status 'dropped'; what sits in it stays put."""
    check_fields(fields, PROJECT_FIELDS if kind == "project" else AREA_FIELDS)
    before = _container_in(conn, user, kind, row_id)
    after = dict(before)
    if "name" in fields:
        after["name"] = required_text(fields["name"], "name", "name cannot be empty")
    for key in ("notes", "purpose", "outcome"):
        if key in fields:
            after[key] = validate_notes(fields[key], key)
    if "status" in fields:
        statuses = PROJECT_STATUSES if kind == "project" else AREA_STATUSES
        after["status"] = choice(fields["status"], statuses, f"{kind} status")
    if "area_id" in fields:
        after["area_id"] = ref(fields["area_id"], "area_id")
    _set_shared(after, fields)
    _guard_in(conn, user, kind, before, after)
    if any(after[k] != before[k] for k in ("name", "visibility", "owner_user_id")):
        _check_name_in(conn, kind, after)
    after["updated_at"] = clock.now_iso()
    _save_in(conn, kind, after)
    _stamp_in(conn, kind, row_id, before, after)
    return _fetch_in(conn, user, kind, row_id)


def update_container(user: User, kind: str, row_id: int, fields: dict) -> dict:
    return _write(update_container_in, user, kind, row_id, fields)


def delete_container_in(conn: db.Conn, user: User, kind: str, row_id: int) -> None:
    """Delete a project or an area for good (archiving is status 'dropped'): the owner's or an
    admin's call. What sat in it stays, loose."""
    row = _container_in(conn, user, kind, row_id)
    _check_deleter(user, row, NOUNS[kind])
    now = clock.now_iso()
    for table, field in _CHILDREN[kind]:
        for child in conn.execute(f"SELECT * FROM {table} WHERE {field} = ?", (row_id,)).fetchall():
            conn.execute(f"UPDATE {table} SET {field} = NULL, updated_at = ? WHERE id = ?", (now, child["id"]))
            _stamp_in(conn, KIND_OF[table], child["id"], dict(child))
    _stamp_in(conn, kind, row_id, row)
    conn.execute(f"DELETE FROM {TABLES[kind]} WHERE id = ?", (row_id,))


def delete_container(user: User, kind: str, row_id: int) -> None:
    _write(delete_container_in, user, kind, row_id)


# ── Views ─────────────────────────────────────────────────────────────────────


def filters(user: User) -> dict:
    """What the pickers offer, from the todos the user can see: contexts, tags, people, active
    areas, per-status counts (every status, zeros included; open ones leave out deferred todos,
    as the lists do), the user's timezone, the active members (the assignee picker) and the
    default visibility a new row gets (members cannot read settings, and the form starts there)."""
    conn = db.get_conn()
    vis = visible("t")

    def distinct(column: str) -> list[str]:
        sql = f"SELECT DISTINCT j.value FROM todos_items t, json_each(t.{column}) j WHERE {vis}"
        return sorted({r[0] for r in conn.execute(sql, (user.id,)) if isinstance(r[0], str) and r[0]}, key=str.lower)

    counts = dict.fromkeys(TODO_STATUSES, 0)
    for status, n in conn.execute(
        f"SELECT t.status, count(*) FROM todos_items t WHERE {vis} AND (t.status IN ('done', 'dropped') OR {NOT_DEFERRED}) GROUP BY t.status",
        (user.id, today(user).isoformat()),
    ):  # fmt: skip
        counts[status] = n
    contexts = conn.execute(
        f"SELECT DISTINCT t.context FROM todos_items t WHERE {vis} AND t.context != '' ORDER BY lower(t.context)", (user.id,)
    )
    members = conn.execute(
        "SELECT id, name FROM core_users WHERE is_active = 1 AND role IN ('admin', 'member') ORDER BY lower(name), id"
    )
    return {
        "contexts": [r[0] for r in contexts],
        "tags": distinct("tags"),
        "people": distinct("people"),
        "areas": [{"id": a["id"], "name": a["name"]} for a in list_areas(user, "active")],
        "status_counts": counts,
        "tz": zone(user).key,
        "members": [dict(r) for r in members],
        "default_visibility": default_visibility(),
    }


def review_status(user: User) -> dict:
    """Whether a weekly review is due (none in the last week, counting from the account's
    creation) and how many of the user's calendar days since the last one."""
    row = db.one("SELECT last_review_at FROM todos_sync WHERE user_id = ?", (user.id,))
    last = row["last_review_at"] if row else None
    since = last or db.one("SELECT created_at FROM core_users WHERE id = ?", (user.id,))["created_at"]
    days = None
    if last:
        days = max(0, (today(user) - clock.parse(last).astimezone(zone(user)).date()).days)
    return {"review_due": since < clock.ago(REVIEW_EVERY_DAYS * 86400), "days_since_review": days, "last_review_at": last}


def mark_review_done(user: User) -> dict:
    with db.transaction() as conn:
        conn.execute(
            """INSERT INTO todos_sync (user_id, last_review_at) VALUES (?, ?)
               ON CONFLICT (user_id) DO UPDATE SET last_review_at = excluded.last_review_at""",
            (user.id, clock.now_iso()),
        )
    return review_status(user)


def review(user: User, limit: int = 100) -> dict:
    """What a weekly review walks through, over the user's work (WORK). Read-only. Each todo
    section holds at most `limit` rows, oldest first, with the full count beside it."""
    conn = db.get_conn()
    day = today(user)
    iso = day.isoformat()
    upcoming_until = (day + datetime.timedelta(days=REVIEW_UPCOMING_DAYS)).isoformat()
    cap = max(1, min(int(limit), 500))

    def section(where: str, *params) -> dict:
        clause, args = f"{WORK} AND {where}", (user.id, user.id, *params)
        count = conn.execute(f"SELECT count(*) FROM todos_items t WHERE {clause}", args).fetchone()[0]
        rows = conn.execute(f"{_SELECT['item']} WHERE {clause} ORDER BY t.created_at ASC, t.id ASC LIMIT ?", (*args, cap))
        return {"count": count, "items": [_shape("item", r) for r in rows]}

    def working(where: str, *params) -> dict:
        """The review's copy of a working list: it leaves out deferred todos too (see `upcoming`)."""
        return section(f"{where} AND {NOT_DEFERRED}", *params, iso)

    open_ = "t.status NOT IN ('done', 'dropped')"
    return {
        "today": iso,
        **review_status(user),
        "inbox": working("t.status = 'inbox'"),
        "completed_last_week": section("t.status = 'done' AND t.completed_at >= ?", clock.ago(7 * 86400)),
        "dated_today_or_overdue": working(
            f"{open_} AND ((t.due_date IS NOT NULL AND t.due_date <= ?) OR (t.revisit_on IS NOT NULL AND t.revisit_on <= ?))",
            iso, iso,
        ),  # fmt: skip
        "projects_without_next_action": _rows_in(
            conn, user, "project",
            f"p.status = 'active' AND NOT EXISTS (SELECT 1 FROM todos_items n WHERE n.project_id = p.id AND n.status = 'next_action' AND {visible('n')})",
            (user.id,), "ORDER BY lower(p.name), p.id",
        ),  # fmt: skip
        "waiting_for": working("t.status IN ('waiting_for', 'delegated')"),
        "routines": section(f"{open_} AND t.repeat != ''"),
        "upcoming": section(
            f"{open_} AND ((t.due_date > ? AND t.due_date <= ?) OR (t.revisit_on > ? AND t.revisit_on <= ?))",
            iso, upcoming_until, iso, upcoming_until,
        ),  # fmt: skip
        "stale": working(
            "t.status IN ('next_action', 'waiting_for', 'delegated') AND t.updated_at < ?",
            clock.ago(REVIEW_STALE_DAYS * 86400),
        ),
        "areas": list_areas(user, "active"),
    }


# ── The change feed ───────────────────────────────────────────────────────────


def changes(user: User, since_rev: int = 0, limit: int = 500, head_only: bool = False) -> dict:
    """What changed for this user after `since_rev`, oldest first: the rows they can see, whole,
    and tombstones ({id, rev}) for rows that left their view (went private, changed hands,
    deleted). Send `next_since_rev` next time; `more` means call again at once. A tombstone may
    name a row the caller never had; ignore it. `reset` means the cursor predates an app reset or
    is ahead of this database: everything comes back, and the caller drops its copy first.
    `head_only` answers with the current cursor in `next_since_rev` and nothing else, for a client
    that has just loaded its lists and polls from now on.

    # simplification: tombstones are kept for good (one journal row per row and audience); prune
    # old ones and raise the floor if the journal ever grows large.
    """
    if since_rev < 0:
        raise Invalid("since_rev must be 0 or more")
    if not 1 <= limit <= 500:
        raise Invalid("limit must be between 1 and 500")
    conn = db.get_conn()
    heads = {r["user_id"]: r for r in conn.execute("SELECT * FROM todos_sync WHERE user_id IN (0, ?)", (user.id,))}
    # Read first and used as the ceiling, so a write landing mid-call waits whole for the next one.
    head = max((r["rev"] for r in heads.values()), default=0)
    team = heads.get(0)
    reset = not head_only and (since_rev > head or (since_rev > 0 and (team is None or since_rev <= team["floor"])))
    found = [] if head_only else conn.execute(
        """SELECT kind, row_id, max(rev) AS rev FROM todos_journal
            WHERE audience IN (0, ?) AND rev > ? AND rev <= ?
            GROUP BY kind, row_id ORDER BY rev LIMIT ?""",
        (user.id, 0 if reset else since_rev, head, limit + 1),
    ).fetchall()
    more = len(found) > limit
    found = found[:limit]
    out: dict = {
        "since_rev": since_rev,
        "next_since_rev": found[-1]["rev"] if more else head,
        "more": more,
        "reset": reset,
        "changed": bool(found),
        "items": [], "projects": [], "areas": [],
        "removed": {"items": [], "projects": [], "areas": []},
    }  # fmt: skip
    for kind in TABLES:
        entries = [e for e in found if e["kind"] == kind]
        if not entries:
            continue
        ids = json.dumps([e["row_id"] for e in entries])
        seen = {r["id"]: r for r in _rows_in(conn, user, kind, f"{_ALIAS[kind]}.id IN (SELECT value FROM json_each(?))", (ids,))}
        for e in entries:
            if e["row_id"] in seen:
                out[PLURAL[kind]].append(seen[e["row_id"]])
            else:
                out["removed"][PLURAL[kind]].append({"id": e["row_id"], "rev": e["rev"]})
    return out


# ── Links, owners and deactivation ────────────────────────────────────────────


def relink_in(conn: db.Conn, entity_type: str, old_id: int, new_id: int | None) -> None:
    """Point todos linked to one record at another (a merge), or at nothing (None: a delete).
    The todos stay; a sync sees each one change."""
    rows = conn.execute("SELECT * FROM todos_items WHERE entity_type = ? AND entity_id = ?", (entity_type, old_id)).fetchall()
    for row in rows:
        conn.execute(
            "UPDATE todos_items SET entity_type = ?, entity_id = ?, updated_at = ? WHERE id = ?",
            (entity_type if new_id is not None else None, new_id, clock.now_iso(), row["id"]),
        )
        _stamp_in(conn, "item", row["id"], dict(row))


def forget_in(conn: db.Conn, entity_type: str, entity_id: int) -> None:
    """A record is being deleted (on_entity_deleted): a todo leaves a tombstone, and todos linked
    to the record lose the link."""
    if entity_type == ENTITY and (row := _raw_in(conn, "item", entity_id)):
        _stamp_in(conn, "item", entity_id, row)
    relink_in(conn, entity_type, entity_id, None)


def transfer_in(conn: db.Conn, admin: User, from_user_id: int, to_user_id: int) -> dict:
    """Give one person's private areas, projects and todos to another (an admin's tool, after a
    deactivation). Assignments to the old owner follow; team rows stay where they are. Names are
    not re-checked for clashes. The caller has checked that `admin` is one."""
    from_user_id = ref(from_user_id, "from_user_id")
    if from_user_id is None or not conn.execute(
        "SELECT 1 FROM core_users WHERE id = ? AND role IN ('admin', 'member')", (from_user_id,)
    ).fetchone():
        raise Invalid("from_user_id: no such user")
    to_user_id = _human_in(conn, to_user_id, "to_user_id")
    if from_user_id == to_user_id:
        raise Invalid("Pick two different people.")
    now, moved = clock.now_iso(), {}
    for kind, table in TABLES.items():
        rows = conn.execute(f"SELECT * FROM {table} WHERE visibility = 'private' AND owner_user_id = ?", (from_user_id,))
        rows = [dict(r) for r in rows]
        for before in rows:
            after = {**before, "owner_user_id": to_user_id, "updated_at": now}
            if before["assignee_user_id"] == from_user_id:
                after["assignee_user_id"] = to_user_id
            _save_in(conn, kind, after)
            _stamp_in(conn, kind, before["id"], before, after)
            if kind == "item":
                timeline.record_changes_in(conn, ENTITY, before["id"], before, after, admin.id)
        moved[PLURAL[kind]] = len(rows)
    return moved


def transfer(admin: User, from_user_id: int, to_user_id: int) -> dict:
    return _write(transfer_in, admin, from_user_id, to_user_id)


def hide_private_for_in(conn: db.Conn, user_id: int) -> dict:
    """Deactivation's hook. Nothing needs writing: only an owner reads their private rows and an
    inactive user reads nothing, so deactivation already hides them, and team rows stay as they
    are. Returns what is now out of everyone's sight: what `transfer` would move."""
    return {
        PLURAL[kind]: conn.execute(
            f"SELECT count(*) FROM {table} WHERE visibility = 'private' AND owner_user_id = ?", (user_id,)
        ).fetchone()[0]
        for kind, table in TABLES.items()
    }
