"""Deals: the lifecycle lead → qualified → proposal → negotiation → won | lost, stage history,
bulk moves, closed_on, archive/restore and merge. Ported from CakeCRM's crm/service.py deals
section (docs/PROVENANCE.md) onto SQLite and core's directory and record services.

Rules that hold on every write path:
- every edit goes through `_apply_in`: one UPDATE of only the columns that change (a no-op
  write changes nothing, not even updated_at, so a redundant call never resets the staleness
  clock), a `crm_deal_stage_events` row when the stage moves, and `timeline.record_changes_in`
  (timeline field_change row, change log, the CRM's touch/scoring hook, after-commit outbox);
- a move into won settles probability at 100 and records closed_on (the caller's day or the
  install-local today); leaving won clears it; a day given without a move edits a won deal's
  day only; a move into lost settles probability at 0; leaving lost clears lost_reason;
- an archived deal cannot change stage (restore it first); archive needs a reason and does
  not bump updated_at, so an archive → restore round trip is not a touch.

Any active member reads and writes any deal (entities.py). Every function that touches a deal
authorizes it; `fn(...)` opens the transaction, `fn_in(conn, ...)` runs in the caller's.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from pydantic import ValidationError

from backend.apps.crm import scoring, settings as crm_settings
from backend.apps.crm.common import (
    BULK_MOVE_MAX,
    CLOSED_STAGES,
    ENTITY,
    LIVE,
    MAX_REASON,
    OPEN,
    STAGES,
    day,
    fts_match,
)
from backend.apps.crm.models import DealIn, DealPatch
from backend.core import clock, db, entities, localtime
from backend.core.errors import Conflict, Forbidden, Invalid, NotFound
from backend.core.timeline import api as timeline

if TYPE_CHECKING:
    from backend.core.auth.deps import User

# The newest of: any edit, any logged activity, any live note or comment. Archive/restore and
# field changes are timeline rows of other kinds, so they are not touches. Needs `d`.
LAST_ACTIVITY = """(SELECT max(x) FROM (
        SELECT max(a.created_at) AS x FROM crm_activity_log a WHERE a.deal_id = d.id
        UNION ALL
        SELECT max(t.created_at) FROM core_timeline t
         WHERE t.entity_type = 'crm.deal' AND t.entity_id = d.id
           AND t.kind IN ('note', 'comment') AND t.archived_at IS NULL))"""
LAST_TOUCH = f"max(d.updated_at, coalesce({LAST_ACTIVITY}, d.updated_at))"

SELECT = f"""SELECT d.*, p.name AS person_name, o.name AS organization_name, u.name AS owner_name,
                    {LAST_ACTIVITY} AS last_activity_at
               FROM crm_deals d
               LEFT JOIN core_people p ON p.id = d.person_id
               LEFT JOIN core_organizations o ON o.id = d.organization_id
               LEFT JOIN core_users u ON u.id = d.owner_user_id"""

# What a person (the PATCH route, a Whisk tool, another app) may set. lost_reason, closed_on,
# archive columns, scores and touch counts have their own writers.
USER_FIELDS = frozenset(DealPatch.model_fields) - {"closed_on"}
SORTS = {"updated_at", "created_at", "value_cents", "expected_close", "title", "stage", "probability", "lead_score"}
MAX_SEARCH = 100


def _validated(model, fields: dict, *, exclude_unset: bool = True) -> dict:
    """Run raw input (tools, other apps) through the route's model; Invalid on a bad value."""
    try:
        return model(**fields).model_dump(exclude_unset=exclude_unset)
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(p) for p in first["loc"]) or "body"
        raise Invalid(f"{where}: {first['msg']}") from None


def _gate(conn: db.Conn, user: User) -> None:
    """Deal lists: the user may read deals at all (the app's roles; any deal id answers)."""
    if not entities.get(ENTITY).can_read(user, conn, 0):
        raise Forbidden()


def _row_in(conn: db.Conn, deal_id: int) -> dict:
    """The raw table row: what record_changes_in compares (status is derived from stage)."""
    row = dict(conn.execute("SELECT * FROM crm_deals WHERE id = ?", (deal_id,)).fetchone())
    del row["status"]
    return row


def deal_in(conn: db.Conn, deal_id: int) -> dict:
    """The API shape of one deal, unauthorized; callers authorize first."""
    return dict(conn.execute(f"{SELECT} WHERE d.id = ?", (deal_id,)).fetchone())


def get_in(conn: db.Conn, user: User, deal_id: int) -> dict:
    entities.authorize(user, conn, ENTITY, deal_id, "read")
    return deal_in(conn, deal_id)


def get(user: User, deal_id: int) -> dict:
    return get_in(db.get_conn(), user, deal_id)


def detail(user: User, deal_id: int) -> dict:
    """The deal with its recent activity and its stage history."""
    conn = db.get_conn()
    deal = get_in(conn, user, deal_id)
    from backend.apps.crm import activity  # activity imports this module

    deal["activity"] = activity.list_in(conn, user, deal_id=deal_id, limit=20)
    deal["stage_events"] = stage_events_in(conn, user, deal_id)
    return deal


def stage_events_in(conn: db.Conn, user: User, deal_id: int) -> list[dict]:
    entities.authorize(user, conn, ENTITY, deal_id, "read")
    rows = conn.execute(
        """SELECT e.id, e.old_stage, e.new_stage, e.user_id, u.name AS user_name, e.changed_at
             FROM crm_deal_stage_events e LEFT JOIN core_users u ON u.id = e.user_id
            WHERE e.deal_id = ? ORDER BY e.changed_at, e.id""",
        (deal_id,),
    )
    return [dict(r) for r in rows]


# ── Reads ─────────────────────────────────────────────────────────────────────


def board(
    user: User, *, stage: str | None = None, include_archived: bool = False,
    limit: int | None = None, after_id: int | None = None, limit_per_stage: int | None = None,
) -> dict:
    """The pipeline board. Three bounding modes over one condition list:
    - default: every matching deal, newest edit first;
    - keyset page (`limit`, optional `after_id`): ordered by id, the transport for a client
      that sweeps every page and reassembles the board;
    - per-stage window (`limit_per_stage`): the newest N per stage, `deals_truncated` when any
      stage had more (Whisk's cap).
    `stage_summary` and the total cover live open deals only, even with include_archived (an
    archived deal is findable but never money), and are skipped on continuation pages."""
    if after_id is not None and limit is None:
        raise Invalid("after_id requires limit")
    if limit_per_stage is not None and (limit is not None or after_id is not None):
        raise Invalid("limit_per_stage cannot be combined with limit or after_id")
    conn = db.get_conn()
    _gate(conn, user)
    where, params = ([] if include_archived else [LIVE]), []
    if stage:
        where.append("d.stage = ?")
        params.append(stage)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    out: dict = {}
    if limit is not None:
        page_where = where + (["d.id > ?"] if after_id is not None else [])
        rows = conn.execute(
            f"{SELECT} {'WHERE ' + ' AND '.join(page_where) if page_where else ''} ORDER BY d.id LIMIT ?",
            (*params, *([after_id] if after_id is not None else []), limit),
        )
        deals = [dict(r) for r in rows]
    elif limit_per_stage is not None:
        rows = conn.execute(
            f"""SELECT * FROM (SELECT x.*, row_number() OVER (PARTITION BY x.stage ORDER BY x.updated_at DESC, x.id DESC) AS rn
                                 FROM ({SELECT} {clause}) x)
                WHERE rn <= ? ORDER BY updated_at DESC, id DESC""",
            (*params, limit_per_stage + 1),
        )
        deals, truncated = [], False
        for r in rows:
            row = dict(r)
            if row.pop("rn") > limit_per_stage:
                truncated = True
                continue
            deals.append(row)
        out["deals_truncated"] = truncated
    else:
        deals = [dict(r) for r in conn.execute(f"{SELECT} {clause} ORDER BY d.updated_at DESC, d.id DESC", params)]
    out["deals"] = deals
    if after_id is None:
        out["stage_summary"] = stage_summary_in(conn, open_only=True)
        out["total_pipeline_value_cents"] = sum(s["total_value_cents"] for s in out["stage_summary"])
    else:
        out["stage_summary"] = out["total_pipeline_value_cents"] = None
    return out


def stage_summary_in(conn: db.Conn, *, open_only: bool) -> list[dict]:
    """Count and value per stage over live deals, in pipeline order."""
    rows = conn.execute(
        f"""SELECT stage, count(*) AS count, coalesce(sum(value_cents), 0) AS total_value_cents
              FROM crm_deals d WHERE {LIVE} {'AND ' + OPEN if open_only else ''} GROUP BY stage"""
    )
    by_stage = {r["stage"]: dict(r) for r in rows}
    return [by_stage[s] for s in STAGES if s in by_stage]


def search(
    user: User, q: str | None = None, *, stage: str | None = None, person_id: int | None = None,
    organization_id: int | None = None, owner_user_id: int | None = None, sort_by: str = "updated_at",
    sort_dir: str = "desc", limit: int = 25, include_archived: bool = False,
) -> list[dict]:
    """Deals matching every word of `q` (prefix, case- and accent-insensitive) in their own
    title, notes or lost reason, or in the name of their person or organization."""
    conn = db.get_conn()
    _gate(conn, user)
    where, params = ([] if include_archived else [LIVE]), []
    if match := fts_match(q):
        where.append(
            """(d.id IN (SELECT rowid FROM crm_deals_fts WHERE crm_deals_fts MATCH ?)
                OR d.person_id IN (SELECT owner_id FROM core_contacts_fts WHERE core_contacts_fts MATCH ? AND owner_type = 'person')
                OR d.organization_id IN (SELECT owner_id FROM core_contacts_fts
                                          WHERE core_contacts_fts MATCH ? AND owner_type = 'organization'))"""
        )
        params += [match, match, match]
    for column, value in (("stage", stage), ("person_id", person_id), ("organization_id", organization_id), ("owner_user_id", owner_user_id)):
        if value is not None:
            where.append(f"d.{column} = ?")
            params.append(value)
    column = sort_by if sort_by in SORTS else "updated_at"
    direction = "ASC" if str(sort_dir).lower() == "asc" else "DESC"
    nulls = " NULLS LAST" if column in ("expected_close", "lead_score") else ""
    limit = max(1, min(int(limit), MAX_SEARCH))
    rows = conn.execute(
        f"{SELECT} {'WHERE ' + ' AND '.join(where) if where else ''} ORDER BY d.{column} {direction}{nulls}, d.id {direction} LIMIT ?",
        (*params, limit),
    )
    return [dict(r) for r in rows]


def for_record_in(conn: db.Conn, user: User, entity_type: str, entity_id: int, include_archived: bool = False) -> list[dict]:
    """A person's or an organization's deals, open ones first. 404 when the record is not readable."""
    column = {"core.person": "person_id", "core.organization": "organization_id"}.get(entity_type)
    if column is None:
        raise Invalid("deals hang off core.person or core.organization")
    entities.authorize(user, conn, entity_type, entity_id, "read")
    _gate(conn, user)
    rows = conn.execute(
        f"""{SELECT} WHERE d.{column} = ? {'' if include_archived else 'AND ' + LIVE}
             ORDER BY d.stage IN ('won', 'lost'), d.updated_at DESC, d.id DESC""",
        (entity_id,),
    )
    return [dict(r) for r in rows]


def badge(user: User) -> dict:
    """The caller's live open deals that have gone quiet past crm.stale_days."""
    cutoff = clock.ago(crm_settings.stale_days() * 86400)
    n = db.get_conn().execute(
        f"SELECT count(*) FROM crm_deals d WHERE {LIVE} AND {OPEN} AND d.owner_user_id = ? AND {LAST_TOUCH} < ?",
        (user.id, cutoff),
    ).fetchone()[0]
    return {"count": n, "label": "Deals needing a touch"}


# ── Writes ────────────────────────────────────────────────────────────────────


def resolve_closed_on(explicit, today: date) -> str:
    """The day a win records: `explicit` (YYYY-MM-DD, not in the future) or today."""
    value = day(explicit, "closed_on")
    if value is None:
        return today.isoformat()
    if value > today.isoformat():
        raise Invalid(f"closed_on cannot be in the future (today is {today.isoformat()})")
    return value


def _check_links_in(conn: db.Conn, user: User, fields: dict) -> None:
    for column, entity_type in (("person_id", "core.person"), ("organization_id", "core.organization")):
        if fields.get(column) is not None:
            try:
                entities.authorize(user, conn, entity_type, fields[column], "read")
            except NotFound:
                raise Invalid(f"{column}: no such record") from None
    if fields.get("owner_user_id") is not None and not conn.execute(
        "SELECT 1 FROM core_users WHERE id = ? AND role IN ('admin', 'member') AND is_active = 1", (fields["owner_user_id"],)
    ).fetchone():
        raise Invalid("owner_user_id: no such active user")


def classify(old: dict, fields: dict, closed_on, today: date) -> dict:
    """The final column map for an edit of deal `old` (its raw row): the stage rules from the
    module docstring. Pure; raises Conflict for a stage change on an archived deal."""
    out = dict(fields)
    old_stage, new_stage = old["stage"], fields.get("stage", old["stage"])
    if new_stage != old_stage:
        if old["archived_at"] is not None:
            raise Conflict(f"Deal #{old['id']} is archived; restore it before changing its stage")
        if new_stage in CLOSED_STAGES:
            out["probability"] = 100 if new_stage == "won" else 0
        if old_stage == "lost" and "lost_reason" not in out:
            out["lost_reason"] = ""
    if new_stage == "won" and old_stage != "won":
        out["closed_on"] = resolve_closed_on(closed_on, today)
    elif old_stage == "won" and new_stage != "won":
        out["closed_on"] = None
    elif closed_on not in (None, ""):
        if new_stage != "won":
            raise Invalid("closed_on can only be set on a won deal")
        out["closed_on"] = resolve_closed_on(closed_on, today)
    return out


def _apply_in(conn: db.Conn, user: User, old: dict, fields: dict, *, closed_on=None, touch: bool = True) -> bool:
    """Write the changed columns of an authorized edit; False when nothing changed.
    `touch=False` leaves updated_at alone (archive and restore are not touches)."""
    final = classify(old, fields, closed_on, localtime.today_local())
    changed = {k: v for k, v in final.items() if old[k] != v}
    if not changed:
        return False
    now = clock.now_iso()
    if touch:
        changed["updated_at"] = now
    sets = ", ".join(f"{k} = ?" for k in changed)  # keys are crm_deals columns named in this module
    conn.execute(f"UPDATE crm_deals SET {sets} WHERE id = ?", (*changed.values(), old["id"]))
    if "stage" in changed:
        conn.execute(
            "INSERT INTO crm_deal_stage_events (deal_id, old_stage, new_stage, user_id, changed_at) VALUES (?, ?, ?, ?, ?)",
            (old["id"], old["stage"], changed["stage"], user.id, now),
        )
    timeline.record_changes_in(conn, ENTITY, old["id"], old, _row_in(conn, old["id"]), user.id)
    return True


def create_in(conn: db.Conn, user: User, fields: dict) -> dict:
    """A new deal from DealIn fields. Born won: probability 100 and closed_on (default today);
    born lost: probability 0."""
    data = _validated(DealIn, fields, exclude_unset=False)
    if "currency" not in fields:
        data["currency"] = crm_settings.default_currency()
    if not entities.get(ENTITY).can_write(user, conn, 0):
        raise Forbidden()
    _check_links_in(conn, user, data)
    data["expected_close"] = day(data.get("expected_close"), "expected_close")
    closed_on = data.pop("closed_on", None)
    if data["stage"] in CLOSED_STAGES:
        data["probability"] = 100 if data["stage"] == "won" else 0
    if data["stage"] == "won":
        data["closed_on"] = resolve_closed_on(closed_on, localtime.today_local())
    elif closed_on not in (None, ""):
        raise Invalid("closed_on can only be set on a won deal")
    now = clock.now_iso()
    data.update(created_at=now, updated_at=now, touch_dirty=1)
    cols = ", ".join(data)  # DealIn's own fields plus the four set here
    cur = conn.execute(f"INSERT INTO crm_deals ({cols}) VALUES ({', '.join('?' * len(data))})", tuple(data.values()))
    deal_id = cur.lastrowid
    conn.execute(
        "INSERT INTO crm_deal_stage_events (deal_id, old_stage, new_stage, user_id, changed_at) VALUES (?, '', ?, ?, ?)",
        (deal_id, data["stage"], user.id, now),
    )
    scoring.refresh_in(conn, deal_ids=[deal_id], person_ids=[data.get("person_id")])
    return deal_in(conn, deal_id)


def create(user: User, fields: dict) -> dict:
    with db.transaction() as conn:
        return create_in(conn, user, fields)


def update_in(conn: db.Conn, user: User, deal_id: int, fields: dict) -> dict:
    """Edit a deal with DealPatch fields; `closed_on` follows `classify`. Unknown or internal
    fields are refused."""
    data = _validated(DealPatch, fields)
    entities.authorize(user, conn, ENTITY, deal_id, "write")
    closed_on = data.pop("closed_on", None)
    for required in ("title", "stage", "value_cents", "currency", "probability"):
        if required in data and data[required] is None:
            raise Invalid(f"{required} cannot be null")
    _check_links_in(conn, user, data)
    if "expected_close" in data:
        data["expected_close"] = day(data["expected_close"], "expected_close")
    _apply_in(conn, user, _row_in(conn, deal_id), data, closed_on=closed_on)
    return deal_in(conn, deal_id)


def update(user: User, deal_id: int, fields: dict) -> dict:
    with db.transaction() as conn:
        return update_in(conn, user, deal_id, fields)


def mark_won_in(conn: db.Conn, user: User, deal_id: int, closed_on=None) -> dict:
    """Won, probability 100, closed_on = `closed_on` or today. On an already-won deal a day
    edits it and no day changes nothing."""
    entities.authorize(user, conn, ENTITY, deal_id, "write")
    _apply_in(conn, user, _row_in(conn, deal_id), {"stage": "won"}, closed_on=closed_on)
    return deal_in(conn, deal_id)


def mark_won(user: User, deal_id: int, closed_on=None) -> dict:
    with db.transaction() as conn:
        return mark_won_in(conn, user, deal_id, closed_on)


def mark_lost_in(conn: db.Conn, user: User, deal_id: int, reason: str = "") -> dict:
    """Lost, probability 0, the reason stored on the deal (and so on its timeline)."""
    entities.authorize(user, conn, ENTITY, deal_id, "write")
    reason = (reason or "").strip()[:MAX_REASON]
    _apply_in(conn, user, _row_in(conn, deal_id), {"stage": "lost", "lost_reason": reason})
    return deal_in(conn, deal_id)


def mark_lost(user: User, deal_id: int, reason: str = "") -> dict:
    with db.transaction() as conn:
        return mark_lost_in(conn, user, deal_id, reason)


def _refused(msg: str) -> dict:
    return {"ok": False, "updated": 0, "updated_ids": [], "errors": [msg]}


def bulk_move_in(conn: db.Conn, user: User, ids: list[int], stage: str, closed_on=None) -> dict:
    """Move many deals to one stage. Request-level problems refuse the whole call (ok false,
    nothing written); a missing, unwritable or archived deal goes to `errors` and the rest
    move. A deal already in the stage is skipped untouched. `closed_on` applies to deals moving
    into won."""
    if stage not in STAGES:
        return _refused(f"Invalid stage: {stage}")
    ids = list(dict.fromkeys(ids or []))
    if not ids:
        return _refused("No deal ids given")
    if any(isinstance(i, bool) or not isinstance(i, int) or i <= 0 for i in ids):
        return _refused("Deal ids must be positive integers")
    if len(ids) > BULK_MOVE_MAX:
        return _refused(f"Too many deals ({len(ids)}); at most {BULK_MOVE_MAX} per move")
    if stage == "won" and closed_on not in (None, ""):
        try:
            resolve_closed_on(closed_on, localtime.today_local())
        except Invalid as e:
            return _refused(e.detail)
    updated, errors = [], []
    for deal_id in ids:
        try:
            entities.authorize(user, conn, ENTITY, deal_id, "write")
        except NotFound:
            errors.append(f"Deal {deal_id} not found")
            continue
        except Forbidden:
            errors.append(f"Deal {deal_id}: not allowed")
            continue
        old = _row_in(conn, deal_id)
        if old["stage"] == stage:
            continue
        try:
            _apply_in(conn, user, old, {"stage": stage}, closed_on=closed_on if stage == "won" else None)
        except (Conflict, Invalid) as e:
            errors.append(e.detail)
            continue
        updated.append(deal_id)
    return {"ok": True, "updated": len(updated), "updated_ids": updated, "errors": errors}


def bulk_move(user: User, ids: list[int], stage: str, closed_on=None) -> dict:
    with db.transaction() as conn:
        return bulk_move_in(conn, user, ids, stage, closed_on)


def archive_in(conn: db.Conn, user: User, deal_id: int, reason: str) -> dict:
    """Soft-archive with a reason; it leaves every list, board and total. Archiving an archived
    deal changes nothing."""
    entities.authorize(user, conn, ENTITY, deal_id, "write")
    old = _row_in(conn, deal_id)
    if old["archived_at"] is None:
        text = (reason or "").strip()[:MAX_REASON]
        if not text:
            raise Invalid("A reason is required to archive a deal")
        fields = {"archived_at": clock.now_iso(), "archived_by": user.id, "archived_reason": text}
        _apply_in(conn, user, old, fields, touch=False)
    return deal_in(conn, deal_id)


def archive(user: User, deal_id: int, reason: str) -> dict:
    with db.transaction() as conn:
        return archive_in(conn, user, deal_id, reason)


def restore_in(conn: db.Conn, user: User, deal_id: int) -> dict:
    entities.authorize(user, conn, ENTITY, deal_id, "write")
    _apply_in(conn, user, _row_in(conn, deal_id), {"archived_at": None, "archived_by": None, "archived_reason": None}, touch=False)
    return deal_in(conn, deal_id)


def restore(user: User, deal_id: int) -> dict:
    with db.transaction() as conn:
        return restore_in(conn, user, deal_id)


def merge_in(conn: db.Conn, user: User, target_id: int, source_id: int) -> dict:
    """Fold `source` into `target`: the source's timeline, files, custom fields (the target's
    values win), reminders, notifications, linked todos and activity move to the target through
    the on_entity_merged subscribers; the source is archived with "Merged into deal #T". The
    target's own fields are not edited. Both must be live."""
    if target_id == source_id:
        raise Invalid("A deal cannot be merged into itself")
    for deal_id in sorted((target_id, source_id)):
        entities.authorize(user, conn, ENTITY, deal_id, "write")
    target, source = _row_in(conn, target_id), _row_in(conn, source_id)
    if archived := [f"#{d['id']}" for d in (target, source) if d["archived_at"] is not None]:
        raise Conflict(f"Deal {', '.join(archived)} is archived; restore it before merging")
    entities.on_entity_merged_in(conn, ENTITY, target_id, source_id)
    reason = f"Merged into deal #{target_id}"
    _apply_in(conn, user, source, {"archived_at": clock.now_iso(), "archived_by": user.id, "archived_reason": reason}, touch=False)
    timeline.add_note_in(conn, user, ENTITY, target_id, f'Merged deal #{source_id} ("{source["title"]}") into this deal.')
    conn.execute("UPDATE crm_deals SET touch_dirty = 1 WHERE id = ?", (target_id,))
    scoring.refresh_in(conn, deal_ids=[target_id, source_id], person_ids=[target["person_id"], source["person_id"]])
    return deal_in(conn, target_id)


def merge(user: User, target_id: int, source_id: int) -> dict:
    with db.transaction() as conn:
        return merge_in(conn, user, target_id, source_id)
