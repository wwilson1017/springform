"""Change lists (agent.md §6, "Change lists and Undo"): the field changes of one bulk tool run
(`ToolSpec.change_list`), read from `core_change_log` by the server, never from the model.

- A call that needs a card is staged: `execute.dry_run` runs it and rolls it back, and `stage`
  stores the rows it would write beside its pending run. Approve re-runs it for real and
  `record_applied_in` refuses the whole run when a listed record changed since.
- A call that runs at once records its rows as applied.
- `undo` puts every record back to its old values through the entity's own `revert_in`, once, for
  the run's own user, skipping a record changed since the apply. It is a REST route, never a tool.
"""

from __future__ import annotations

import json
from collections import defaultdict

from backend.core import clock, db, entities
from backend.core.agent import history
from backend.core.auth.deps import User
from backend.core.errors import AppError, Conflict, NotFound

CHANGED_BEFORE_APPLY = "These records changed since the card was shown, so nothing was changed. Ask again."
CHANGED_SINCE_APPLY = "changed since it was applied"
NOTHING_TO_CHANGE = "Nothing to change: this call would not change any record."
CANNOT_UNDO = "this kind of record cannot be undone"
GONE = "it is gone, or you can no longer see it"
NOT_ALLOWED = "you may not change it"
UNDO_NOTE = (
    "[The user undid this change list afterwards: {reverted} records were put back to their old values, "
    "{skipped} were left as they are. Do not redo it unless they ask.]"
)


def mark_in(conn: db.Conn) -> int:
    """The newest change-log id: rows after it are what a write since then reported."""
    return conn.execute("SELECT coalesce(max(id), 0) FROM core_change_log").fetchone()[0]


def rows_since_in(conn: db.Conn, mark: int) -> list[dict]:
    """The change-log rows after `mark`, in order. SQLite has one writer, so inside a transaction
    these are that transaction's own."""
    return [
        {"entity_type": r[0], "entity_id": r[1], "field": r[2], "old": json.loads(r[3]), "new": json.loads(r[4])}
        for r in conn.execute(
            "SELECT entity, entity_id, field, old, new FROM core_change_log WHERE id > ? ORDER BY id", (mark,)
        )
    ]


def notes_of(result) -> list[str]:
    """What a change-list tool's result says beyond its rows: its `errors` (records it will not
    change) and `notes` (effects the change log does not show), as text."""
    if not isinstance(result, dict):
        return []
    out = []
    for key in ("errors", "notes"):
        items = result.get(key)
        for item in items if isinstance(items, list) else []:
            out.append(item if isinstance(item, str) else json.dumps(item, default=str))
    return out


def stage(rows: list[dict], notes: list[str], mark: int, **run) -> int:
    """The pending run and its list in one transaction, so a staged run never lacks its rows."""
    with db.transaction() as conn:
        run_id = history.insert_tool_run_in(conn, **run, status="pending")
        conn.execute(
            """INSERT INTO core_agent_change_lists (tool_run_id, user_id, rows, notes, created_at, staged_mark)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (run_id, run["user_id"], json.dumps(rows), json.dumps(notes), clock.now_iso(), mark),
        )
        return run_id


def _shape(rows: list[dict]) -> list[tuple]:
    # new values are not compared: a derived stamp such as completed_at differs by the clock
    return sorted((r["entity_type"], r["entity_id"], r["field"], json.dumps(r["old"], sort_keys=True)) for r in rows)


def record_applied_in(conn: db.Conn, run_id: int, user_id: int, mark: int, result) -> None:
    """After a change-list tool's handler ran in `conn` (from `mark`): keep its rows as applied.
    A staged run is refused (Conflict, so the caller's transaction rolls back) when a listed
    record has a change-log row since it was staged, or the run changed other rows than listed."""
    rows = rows_since_in(conn, mark)
    staged = conn.execute(
        "SELECT rows, staged_mark FROM core_agent_change_lists WHERE tool_run_id = ?", (run_id,)
    ).fetchone()
    now, last = clock.now_iso(), mark_in(conn)
    if staged is None:
        if rows:
            conn.execute(
                """INSERT INTO core_agent_change_lists
                       (tool_run_id, user_id, rows, notes, created_at, applied_at, last_change_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (run_id, user_id, json.dumps(rows), json.dumps(notes_of(result)), now, now, last),
            )
        return
    listed = json.loads(staged["rows"])
    keys = {(r["entity_type"], r["entity_id"]) for r in listed}
    since = conn.execute(
        "SELECT entity, entity_id FROM core_change_log WHERE id > ? AND id <= ?", (staged["staged_mark"], mark)
    )
    if any((r[0], r[1]) in keys for r in since) or _shape(rows) != _shape(listed):
        raise Conflict(CHANGED_BEFORE_APPLY)
    conn.execute(
        "UPDATE core_agent_change_lists SET rows = ?, notes = ?, applied_at = ?, last_change_id = ? WHERE tool_run_id = ?",
        (json.dumps(rows), json.dumps(notes_of(result)), now, last, run_id),
    )


def exists(run_id: int) -> bool:
    return db.one("SELECT 1 FROM core_agent_change_lists WHERE tool_run_id = ?", (run_id,)) is not None


def run_ids_for(conversation_id: int) -> set[int]:
    return {
        r["tool_run_id"]
        for r in db.rows(
            """SELECT l.tool_run_id FROM core_agent_change_lists l
                 JOIN core_agent_tool_runs t ON t.id = l.tool_run_id WHERE t.conversation_id = ?""",
            (conversation_id,),
        )
    }


def _status(row) -> str:
    if row["undone_at"]:
        return "undone"
    if row["applied_at"]:
        return "applied"
    return "staged" if row["run_status"] == "pending" else "not_applied"  # denied, stale, error


def get_in(conn: db.Conn, user: User, run_id: int) -> dict | None:
    """The `ChangeList` of the user's own run; None for a missing list or another user's. Only
    records the user can read now are shown; the rest are counted in `hidden`."""
    row = conn.execute(
        """SELECT l.*, t.status AS run_status FROM core_agent_change_lists l
             JOIN core_agent_tool_runs t ON t.id = l.tool_run_id WHERE l.tool_run_id = ? AND l.user_id = ?""",
        (run_id, user.id),
    ).fetchone()
    if row is None:
        return None
    rows = json.loads(row["rows"])
    undo = json.loads(row["undo_result"]) if row["undo_result"] else None
    wanted = defaultdict(set)
    for r in [*rows, *(undo["skipped"] if undo else [])]:
        wanted[r["entity_type"]].add(r["entity_id"])
    titles: dict[str, dict[int, str]] = {}
    for entity_type, ids in wanted.items():
        try:
            titles[entity_type] = entities.titles_for(user, conn, entity_type, ids)
        except NotFound:  # an entity type no longer registered
            titles[entity_type] = {}

    def shown(items: list[dict]) -> list[dict]:
        return [
            {**r, "title": titles[r["entity_type"]][r["entity_id"]]}
            for r in items
            if r["entity_id"] in titles[r["entity_type"]]
        ]

    visible = shown(rows)
    skipped = shown(undo["skipped"]) if undo else []
    return {
        "tool_run_id": run_id,
        "status": _status(row),
        "rows": visible,
        "notes": json.loads(row["notes"]),
        "hidden": len(rows) - len(visible),
        "reverted": undo["reverted"] if undo else None,
        "skipped": skipped,
    }


def get(user: User, run_id: int) -> dict | None:
    return get_in(db.get_conn(), user, run_id)


def undo(user: User, run_id: int) -> dict:
    """Put back the old values of the user's own applied list, in one transaction. A record with a
    change-log row since the apply is left alone; a record its entity refuses is skipped with the
    reason (each record in its own SAVEPOINT, so a refusal after a partial write keeps none of it)."""
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT * FROM core_agent_change_lists WHERE tool_run_id = ? AND user_id = ?", (run_id, user.id)
        ).fetchone()
        if row is None:
            raise NotFound("change_list_not_found")
        if row["undone_at"]:
            raise Conflict("already_undone")
        if not row["applied_at"]:
            raise Conflict("not_applied")
        olds: dict[tuple[str, int], dict] = {}
        for r in json.loads(row["rows"]):
            olds.setdefault((r["entity_type"], r["entity_id"]), {}).setdefault(r["field"], r["old"])
        # simplification: any later change to a record skips the whole record, not just the fields
        # this list wrote; upgrade: compare per field.
        changed = {
            key
            for key in olds
            if conn.execute(
                "SELECT 1 FROM core_change_log WHERE entity = ? AND entity_id = ? AND id > ? LIMIT 1",
                (*key, row["last_change_id"]),
            ).fetchone()
        }  # all checked before any revert writes, so one revert's own rows never skip another record
        skipped = [
            {"entity_type": t, "entity_id": i, "reason": CHANGED_SINCE_APPLY} for t, i in olds if (t, i) in changed
        ]
        reverted = 0
        for (entity_type, entity_id), old in olds.items():
            if (entity_type, entity_id) in changed:
                continue
            conn.execute("SAVEPOINT undo_record")
            try:
                entity = entities.authorize(user, conn, entity_type, entity_id, "write")
                if entity.revert_in is None:
                    raise Conflict(CANNOT_UNDO)
                # simplification: Undo restores field values, not derived stamps (a todo put back to
                # done gets a new completed_at); upgrade: log and restore the stamps.
                entity.revert_in(conn, user, entity_id, old)
            except AppError as e:
                conn.execute("ROLLBACK TO undo_record")
                reason = GONE if isinstance(e, NotFound) else e.detail if e.detail != e.default else NOT_ALLOWED
                skipped.append({"entity_type": entity_type, "entity_id": entity_id, "reason": reason})
            else:
                reverted += 1
            conn.execute("RELEASE undo_record")
        conn.execute(
            "UPDATE core_agent_change_lists SET undone_at = ?, undo_result = ? WHERE tool_run_id = ?",
            (clock.now_iso(), json.dumps({"reverted": reverted, "skipped": skipped}), run_id),
        )
        conn.execute(
            "UPDATE core_agent_tool_runs SET undo_note = ? WHERE id = ?",
            (UNDO_NOTE.format(reverted=reverted, skipped=len(skipped)), run_id),
        )
        return db.must(get_in(conn, user, run_id))
