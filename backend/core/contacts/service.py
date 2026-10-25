"""The contacts directory: people and organizations (many-to-many with a role), their addresses
and contact channels, search, duplicates and merge (docs/agents/contacts.md).

Rules:
- Every function has `fn(...)` (writes: its own transaction; reads: this thread's connection)
  and `fn_in(conn, ...)`. Every record operation calls `entities.authorize` first.
- `email`/`phone` on a person or organization mirror its primary email/phone channel. They are
  written only by `_sync_primary`, in the transaction that changed the channels.
- Primaries: one per person among its organization links, one per owner and channel kind,
  one per owner among addresses (unique indexes). Whenever rows exist and none is primary the
  oldest is promoted, so the first one added is primary and deleting the primary promotes the
  next. Making a row primary demotes the old one first.
- A merged record keeps its row with `merged_into_id` (always the chain head: aliases are
  flat) and `archived_at`. Reads of it return `{"merged_into": head}`; writes are refused (409).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

from backend.core import changelog, clock, db, entities, pagination
from backend.core.errors import Conflict, Forbidden, Invalid, NotFound
from backend.core.timeline import service as timeline

if TYPE_CHECKING:
    from backend.core.auth.deps import User


@dataclass(frozen=True)
class Kind:
    table: str
    entity: str
    fields: tuple[str, ...]  # writable columns; email/phone go through channels


@dataclass(frozen=True)
class Part:
    table: str
    fields: tuple[str, ...]
    plural: str
    by_kind: bool  # channels have one primary per kind, addresses one per owner


KINDS = {
    "person": Kind(
        "core_people", "core.person",
        ("name", "given_name", "family_name", "title", "source", "status", "tags", "notes", "owner_user_id"),
    ),
    "organization": Kind(
        "core_organizations", "core.organization",
        ("name", "domain", "website", "industry", "source", "status", "tags", "notes", "owner_user_id"),
    ),
}
PARTS = {
    "channel": Part("core_contact_channels", ("kind", "value", "label"), "channels", True),
    "address": Part(
        "core_addresses", ("kind", "line1", "line2", "city", "region", "postal_code", "country"), "addresses", False
    ),
}
CHANNEL_KINDS = ("email", "phone", "url", "other")
MIRRORED = ("email", "phone")
LINKS = "core_person_organizations"


def writes(fn_in: Callable) -> Callable:
    """`fn(...)` = `fn_in(conn, ...)` in its own transaction."""

    def fn(*args, **kwargs):
        with db.transaction() as conn:
            return fn_in(conn, *args, **kwargs)

    fn.__name__, fn.__doc__ = fn_in.__name__.removesuffix("_in"), fn_in.__doc__
    return fn


def reads(fn_in: Callable) -> Callable:
    """`fn(...)` = `fn_in(conn, ...)` on this thread's connection."""

    def fn(*args, **kwargs):
        return fn_in(db.get_conn(), *args, **kwargs)

    fn.__name__, fn.__doc__ = fn_in.__name__.removesuffix("_in"), fn_in.__doc__
    return fn


# ── Helpers ──────────────────────────────────────────────────────────────────


def _kind(kind: str) -> Kind:
    try:
        return KINDS[kind]
    except KeyError:
        raise Invalid(f"kind must be 'person' or 'organization', not {kind!r}") from None


def _part(part: str) -> Part:
    try:
        return PARTS[part]
    except KeyError:
        raise Invalid(f"part must be 'channel' or 'address', not {part!r}") from None


def _gate(user: User, conn: db.Conn, kind: str, action: str) -> None:
    """Operations on no single record (create, list, search, duplicates) ask the entity's rule."""
    # simplification: core.person/core.organization rules ignore the id (any active member); a
    # fork that registers a per-record rule would need lists to filter rows instead.
    entity = entities.get(_kind(kind).entity)
    if not (entity.can_read if action == "read" else entity.can_write)(user, conn, 0):
        raise Forbidden()


def _record(row) -> dict:
    rec = dict(row)
    rec["tags"] = json.loads(rec["tags"] or "[]")
    return rec


def _bools(row) -> dict:
    rec = dict(row)
    rec["is_primary"] = bool(rec["is_primary"])
    return rec


def _row_in(conn: db.Conn, kind: str, record_id: int) -> dict:
    return _record(conn.execute(f"SELECT * FROM {KINDS[kind].table} WHERE id = ?", (record_id,)).fetchone())


def _live_in(conn: db.Conn, user: User, kind: str, record_id: int) -> dict:
    """Authorize a write, then the record; a merged record is refused (write to the survivor)."""
    entities.authorize(user, conn, _kind(kind).entity, record_id, "write")
    rec = _row_in(conn, kind, record_id)
    if rec["merged_into_id"] is not None:
        raise Conflict(f"{kind} #{record_id} was merged into #{rec['merged_into_id']}")
    return rec


def _day(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError:
        raise Invalid(f"not a date: {value!r}") from None


def _match(q: str | None) -> str | None:
    """An FTS5 query from user text: every word must match as a prefix. The unicode61 tokenizer
    folds case and accents on both sides; quoting keeps FTS syntax out of user input."""
    return " ".join(f'"{t}"*' for t in re.findall(r"\w+", q or "")) or None


def _ensure_primary_in(conn: db.Conn, table: str, where: str, params: tuple) -> None:
    """When rows match `where` and none is primary, promote the oldest."""
    conn.execute(
        f"""UPDATE {table} SET is_primary = 1
            WHERE id = (SELECT id FROM {table} WHERE {where} ORDER BY id LIMIT 1)
              AND NOT EXISTS (SELECT 1 FROM {table} WHERE {where} AND is_primary = 1)""",
        (*params, *params),
    )


def _sync_primary(conn: db.Conn, owner_type: str, owner_id: int) -> None:
    """The one writer of the `email`/`phone` mirror columns: the primary channel's value or NULL."""
    primary = {
        r["kind"]: r["value"]
        for r in conn.execute(
            """SELECT kind, value FROM core_contact_channels
               WHERE owner_type = ? AND owner_id = ? AND is_primary = 1 AND kind IN ('email', 'phone')""",
            (owner_type, owner_id),
        )
    }
    email, phone = primary.get("email"), primary.get("phone")
    conn.execute(
        f"""UPDATE {KINDS[owner_type].table} SET email = ?, phone = ?, updated_at = ?
            WHERE id = ? AND (email IS NOT ? OR phone IS NOT ?)""",
        (email, phone, clock.now_iso(), owner_id, email, phone),
    )


def _settle_in(conn: db.Conn, owner_type: str, owner_id: int, user: User | None = None, before: dict | None = None) -> None:
    """After any change to an owner's channels or addresses: primaries, the mirror, and (given
    `before`) the field changes on the owner's timeline and change log."""
    for kind in CHANNEL_KINDS:
        _ensure_primary_in(
            conn, "core_contact_channels", "owner_type = ? AND owner_id = ? AND kind = ?", (owner_type, owner_id, kind)
        )
    _ensure_primary_in(conn, "core_addresses", "owner_type = ? AND owner_id = ?", (owner_type, owner_id))
    _sync_primary(conn, owner_type, owner_id)
    if before is not None:
        after = _row_in(conn, owner_type, owner_id)
        timeline.record_changes_in(conn, KINDS[owner_type].entity, owner_id, before, after, user.id)


def _set_primary_channel_in(conn: db.Conn, owner_type: str, owner_id: int, kind: str, value: Any) -> None:
    """`email=`/`phone=` on create or update: rewrite the primary channel of that kind; blank removes it."""
    value = "" if value is None else str(value).strip()
    row = conn.execute(
        "SELECT id FROM core_contact_channels WHERE owner_type = ? AND owner_id = ? AND kind = ? AND is_primary = 1",
        (owner_type, owner_id, kind),
    ).fetchone()
    now = clock.now_iso()
    if row and value:
        conn.execute("UPDATE core_contact_channels SET value = ?, updated_at = ? WHERE id = ?", (value, now, row[0]))
    elif row:
        conn.execute("DELETE FROM core_contact_channels WHERE id = ?", (row[0],))
    elif value:
        conn.execute(
            """INSERT INTO core_contact_channels (owner_type, owner_id, kind, value, is_primary, created_at, updated_at)
               VALUES (?, ?, ?, ?, 1, ?, ?)""",
            (owner_type, owner_id, kind, value, now, now),
        )


def _clean_in(conn: db.Conn, kind: str, fields: dict, creating: bool) -> tuple[dict, dict]:
    """Validated columns, and the mirrored channel values (`email`, `phone`), from caller fields."""
    allowed = _kind(kind).fields
    if unknown := set(fields) - set(allowed) - set(MIRRORED):
        raise Invalid(f"unknown field(s): {', '.join(sorted(unknown))}")
    cols = {f: (v.strip() or None) if isinstance(v, str) else v for f, v in fields.items() if f in allowed}
    mirrored = {f: fields[f] for f in MIRRORED if f in fields}
    if creating and kind == "person" and not cols.get("name"):
        cols["name"] = " ".join(filter(None, (cols.get("given_name"), cols.get("family_name")))) or None
    if (creating or "name" in cols) and not cols.get("name"):
        raise Invalid("name is required")
    if "tags" in cols:
        tags = cols["tags"] or []
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            raise Invalid("tags must be a list of strings")
        cols["tags"] = json.dumps(list(dict.fromkeys(t.strip() for t in tags if t.strip())))
    owner = cols.get("owner_user_id")
    if owner is not None and not conn.execute("SELECT 1 FROM core_users WHERE id = ? AND role != 'system'", (owner,)).fetchone():
        raise Invalid("owner_user_id: no such user")
    return cols, mirrored


def _name_key(name: str | None) -> str:
    """Names compare trimmed and casefolded, so "Café" and "CAFÉ" match (SQL lower() is ASCII-only)."""
    return (name or "").strip().casefold()


def _org_named_in(conn: db.Conn, name: str, exclude: int | None = None, merged: bool = False) -> int | None:
    """The organization holding `name` (`_name_key`): unmerged ones only, or, with `merged`,
    unmerged first and then merged ones. The unique index on lower(trim(name)) is the backstop.
    # simplification: linear scan over organizations, upgrade path name_key column"""
    key = _name_key(name)
    rows = conn.execute(
        """SELECT id, name FROM core_organizations WHERE (? OR merged_into_id IS NULL) AND id IS NOT ?
            ORDER BY merged_into_id IS NOT NULL, id""",
        (merged, exclude),
    )
    return next((r[0] for r in rows if _name_key(r[1]) == key), None)


def _links_in(conn: db.Conn, kind: str, record_id: int) -> list[dict]:
    link = "l.role, l.is_primary, l.started_on, l.ended_on"
    if kind == "person":
        sql = f"""SELECT l.organization_id, o.name, o.archived_at, {link}
                  FROM {LINKS} l JOIN core_organizations o ON o.id = l.organization_id
                  WHERE l.person_id = ? ORDER BY l.is_primary DESC, o.name COLLATE NOCASE, l.role"""
    else:
        sql = f"""SELECT l.person_id, p.name, p.email, p.phone, p.title, p.archived_at, {link}
                  FROM {LINKS} l JOIN core_people p ON p.id = l.person_id
                  WHERE l.organization_id = ? ORDER BY p.name COLLATE NOCASE, p.id, l.role"""
    return [_bools(r) for r in conn.execute(sql, (record_id,))]


def _detail_in(conn: db.Conn, kind: str, record_id: int) -> dict:
    rec = _row_in(conn, kind, record_id)
    owner = conn.execute("SELECT name FROM core_users WHERE id = ?", (rec["owner_user_id"],)).fetchone()
    rec["owner_name"] = owner[0] if owner else None  # kept out of _row_in, whose dict the change log diffs
    rec["organizations" if kind == "person" else "people"] = _links_in(conn, kind, record_id)
    for part in PARTS.values():
        rec[part.plural] = [
            _bools(r)
            for r in conn.execute(
                f"SELECT * FROM {part.table} WHERE owner_type = ? AND owner_id = ? ORDER BY kind, is_primary DESC, id",
                (kind, record_id),
            )
        ]
    return rec


# ── Read ─────────────────────────────────────────────────────────────────────


def resolve_in(conn: db.Conn, kind: str, record_id: int) -> int:
    """The chain head: follows merged_into_id to a record that was not merged (cycle-guarded)."""
    table, seen, current = _kind(kind).table, set(), record_id
    while True:
        row = conn.execute(f"SELECT merged_into_id FROM {table} WHERE id = ?", (current,)).fetchone()
        if row is None:
            raise NotFound()
        if row[0] is None:
            return current
        seen.add(current)
        current = row[0]
        if current in seen:
            raise Conflict(f"the merge chain of {kind} #{record_id} loops")


def get_in(conn: db.Conn, user: User, kind: str, record_id: int) -> dict:
    """A person or organization with its links, addresses and channels; `{"merged_into": head}`
    when the id was merged away."""
    entities.authorize(user, conn, _kind(kind).entity, record_id, "read")
    head = resolve_in(conn, kind, record_id)
    return {"merged_into": head} if head != record_id else _detail_in(conn, kind, record_id)


def list_in(
    conn: db.Conn, user: User, kind: str, *, q: str | None = None, archived: bool = False,
    organization_id: int | None = None, tag: str | None = None, page: int = 1, page_size: int | None = None,
) -> dict:
    """One page of unmerged records, live or (archived=True) archived, ordered by name.
    Rows carry the owner's name; people rows also their primary organization's id and name."""
    _gate(user, conn, kind, "read")
    where, params = ["r.merged_into_id IS NULL", f"r.archived_at IS {'NOT ' if archived else ''}NULL"], []
    if match := _match(q):
        where.append("r.id IN (SELECT owner_id FROM core_contacts_fts WHERE core_contacts_fts MATCH ? AND owner_type = ?)")
        params += [match, kind]
    if tag and tag.strip():
        where.append("EXISTS (SELECT 1 FROM json_each(r.tags) WHERE lower(value) = lower(?))")
        params.append(tag.strip())
    if organization_id is not None:
        if kind != "person":
            raise Invalid("organization_id filters people")
        where.append(f"r.id IN (SELECT person_id FROM {LINKS} WHERE organization_id = ?)")
        params.append(organization_id)
    table, clause = _kind(kind).table, " AND ".join(where)
    total = conn.execute(f"SELECT count(*) FROM {table} r WHERE {clause}", params).fetchone()[0]
    limit, _ = pagination.window(page_size)
    page = max(1, int(page or 1))
    select, join = "r.*, u.name AS owner_name", "LEFT JOIN core_users u ON u.id = r.owner_user_id"
    if kind == "person":
        select += ", o.id AS primary_organization_id, o.name AS primary_organization_name"
        join += f"""
                   LEFT JOIN {LINKS} l ON l.person_id = r.id AND l.is_primary = 1
                   LEFT JOIN core_organizations o ON o.id = l.organization_id"""
    rows = conn.execute(
        f"SELECT {select} FROM {table} r {join} WHERE {clause} ORDER BY r.name COLLATE NOCASE, r.id LIMIT ? OFFSET ?",
        (*params, limit, (page - 1) * limit),
    )
    return {"items": [_record(r) for r in rows], "total": total, "page": page, "page_size": limit}


def search_in(conn: db.Conn, user: User, q: str, kind: str | None = None, limit: int = 20) -> list[dict]:
    """Live people and organizations matching every word of `q` (prefix, case- and
    accent-insensitive), best match first: [{kind, id, name, email, phone, url}]."""
    kinds = [kind] if kind else list(KINDS)
    for k in kinds:
        _gate(user, conn, k, "read")
    if not (match := _match(q)):
        return []
    rows = conn.execute(
        """SELECT owner_type AS kind, owner_id AS id, coalesce(p.name, o.name) AS name,
                  coalesce(p.email, o.email) AS email, coalesce(p.phone, o.phone) AS phone
           FROM core_contacts_fts
           LEFT JOIN core_people p ON owner_type = 'person' AND p.id = owner_id
           LEFT JOIN core_organizations o ON owner_type = 'organization' AND o.id = owner_id
           WHERE core_contacts_fts MATCH ? AND owner_type IN (SELECT value FROM json_each(?))
             AND coalesce(p.merged_into_id, o.merged_into_id) IS NULL
             AND coalesce(p.archived_at, o.archived_at) IS NULL
           ORDER BY core_contacts_fts.rank LIMIT ?""",
        (match, json.dumps(kinds), pagination.window(limit)[0]),
    )
    return [{**dict(r), "url": entities.url_for(KINDS[r["kind"]].entity, r["id"])} for r in rows]


def organizations_for_in(conn: db.Conn, user: User, person_id: int) -> list[dict]:
    """[{organization_id, name, archived_at, role, is_primary, started_on, ended_on}], primary first.
    A merged person id reads its survivor's links."""
    entities.authorize(user, conn, "core.person", person_id, "read")
    return _links_in(conn, "person", resolve_in(conn, "person", person_id))


def people_for_in(conn: db.Conn, user: User, organization_id: int) -> list[dict]:
    """[{person_id, name, email, phone, title, archived_at, role, is_primary, started_on, ended_on}]
    by name. A merged organization id reads its survivor's links."""
    entities.authorize(user, conn, "core.organization", organization_id, "read")
    return _links_in(conn, "organization", resolve_in(conn, "organization", organization_id))


# Duplicate matching is exact after normalization (lifted from CakeCRM analytics_service): a
# false positive invites merging two real records, so near-misses are left for a human.
# simplification: phones compare with spaces, dashes, dots, brackets and '+' removed, so a
# number with and without its country code does not match; E.164 at write time is the upgrade.
_DIGITS = "replace(replace(replace(replace(replace(replace(c.value, ' ', ''), '-', ''), '(', ''), ')', ''), '.', ''), '+', '')"


def find_duplicates_in(conn: db.Conn, user: User, kind: str, limit: int = 50) -> list[dict]:
    """Groups of live records sharing an email or phone channel, or a name (people) or domain
    (organizations; their names are unique already):
    [{match_on, value, count, records: [{id, label}]}], biggest groups first."""
    _gate(user, conn, kind, "read")
    k, live = _kind(kind), "r.merged_into_id IS NULL AND r.archived_at IS NULL"
    channel = f"""SELECT DISTINCT r.id, {{}} AS k FROM core_contact_channels c JOIN {k.table} r ON r.id = c.owner_id
                  WHERE c.owner_type = '{kind}' AND c.kind = ? AND {live}"""
    column = "name" if kind == "person" else "domain"
    keys = [
        ("email", channel.format("c.value"), ("email",)),
        ("phone", channel.format(_DIGITS), ("phone",)),
        (column, f"SELECT r.id, r.{column} AS k FROM {k.table} r WHERE {live}", ()),
    ]
    groups = []
    for match_on, sql, params in keys:
        by_key: dict[str, set[int]] = {}
        for r in conn.execute(sql, params):
            if key := _name_key(r["k"]):  # casefold in Python: SQL lower() leaves "É" alone
                by_key.setdefault(key, set()).add(r["id"])
        found = sorted((-len(ids), key, sorted(ids)) for key, ids in by_key.items() if len(ids) > 1)
        groups += [
            {"match_on": match_on, "value": key, "count": len(ids), "ids": ids}
            for _, key, ids in found[: pagination.window(limit)[0]]
        ]
    labels = entities.titles_for(user, conn, k.entity, [i for g in groups for i in g["ids"]])
    for g in groups:
        g["records"] = [{"id": i, "label": labels.get(i, "")} for i in g.pop("ids")]
    return groups


# ── Write: records ───────────────────────────────────────────────────────────


def _insert_in(conn: db.Conn, user: User, kind: str, fields: dict) -> int:
    _gate(user, conn, kind, "write")
    cols, mirrored = _clean_in(conn, kind, fields, creating=True)
    if kind == "organization" and (other := _org_named_in(conn, cols["name"])):
        raise Conflict(f"organization #{other} already has that name")
    now = clock.now_iso()
    cols |= {"created_at": now, "updated_at": now}
    record_id = conn.execute(
        f"INSERT INTO {KINDS[kind].table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
        tuple(cols.values()),
    ).lastrowid
    for channel_kind, value in mirrored.items():
        _set_primary_channel_in(conn, kind, record_id, channel_kind, value)
    _settle_in(conn, kind, record_id)
    return record_id


def create_in(conn: db.Conn, user: User, kind: str, fields: dict) -> dict:
    """Create a person or organization; `email`/`phone` become its primary channels. A person
    without `name` takes "given_name family_name". Returns the detail (as `get`)."""
    return _detail_in(conn, kind, _insert_in(conn, user, kind, fields))


def update_in(conn: db.Conn, user: User, kind: str, record_id: int, fields: dict) -> dict:
    """Change the given fields; `email`/`phone` rewrite the primary channel (blank removes it).
    Changes go to the record's timeline and change log. Returns the detail."""
    before = _live_in(conn, user, kind, record_id)
    cols, mirrored = _clean_in(conn, kind, fields, creating=False)
    if kind == "organization" and "name" in cols and (other := _org_named_in(conn, cols["name"], record_id)):
        raise Conflict(f"organization #{other} already has that name")
    if cols:
        conn.execute(
            f"UPDATE {KINDS[kind].table} SET {', '.join(f'{c} = ?' for c in cols)}, updated_at = ? WHERE id = ?",
            (*cols.values(), clock.now_iso(), record_id),
        )
    for channel_kind, value in mirrored.items():
        _set_primary_channel_in(conn, kind, record_id, channel_kind, value)
    _settle_in(conn, kind, record_id, user, before)
    return _detail_in(conn, kind, record_id)


def _set_archived_in(conn: db.Conn, user: User, kind: str, record_id: int, archived_at: str | None) -> dict:
    before = _live_in(conn, user, kind, record_id)
    if (before["archived_at"] is None) != (archived_at is None):
        conn.execute(
            f"UPDATE {KINDS[kind].table} SET archived_at = ?, updated_at = ? WHERE id = ?",
            (archived_at, clock.now_iso(), record_id),
        )
        timeline.record_changes_in(conn, KINDS[kind].entity, record_id, before, _row_in(conn, kind, record_id), user.id)
    return _detail_in(conn, kind, record_id)


def archive_in(conn: db.Conn, user: User, kind: str, record_id: int) -> dict:
    """Hide from lists and search; the detail still loads, with `archived_at`."""
    return _set_archived_in(conn, user, kind, record_id, clock.now_iso())


def restore_in(conn: db.Conn, user: User, kind: str, record_id: int) -> dict:
    return _set_archived_in(conn, user, kind, record_id, None)


def resolve_or_create_organizations_in(conn: db.Conn, user: User, names: list[str]) -> dict[str, int]:
    """{name as passed: organization id}, matching case-insensitively after trimming and
    creating the missing ones. A name held by a merged organization maps to its survivor; one
    held by an archived organization maps to it. Blank names are left out."""
    _gate(user, conn, "organization", "write")
    out = {}
    for raw in dict.fromkeys(names):
        name = (raw or "").strip()
        if not name:
            continue
        found = _org_named_in(conn, name, merged=True)
        out[raw] = resolve_in(conn, "organization", found) if found else _insert_in(conn, user, "organization", {"name": name})
    return out


# ── Write: links ─────────────────────────────────────────────────────────────


def _link_row_in(conn: db.Conn, person_id: int, organization_id: int, role: str) -> dict:
    row = conn.execute(
        f"SELECT * FROM {LINKS} WHERE person_id = ? AND organization_id = ? AND role = ?",
        (person_id, organization_id, role),
    ).fetchone()
    if row is None:
        raise NotFound("no such link")
    return _bools(row)


def link_in(
    conn: db.Conn, user: User, person_id: int, organization_id: int, role: str = "", is_primary: bool = False,
    started_on: Any = None, ended_on: Any = None,
) -> dict:
    """Link a person to an organization with a role (idempotent per (person, organization, role)).
    is_primary=True demotes the person's other primary; a person's first link is primary.
    Returns the link {id, person_id, organization_id, role, is_primary, started_on, ended_on, created_at}."""
    _live_in(conn, user, "person", person_id)
    _live_in(conn, user, "organization", organization_id)
    role = (role or "").strip()
    if is_primary:
        conn.execute(
            f"UPDATE {LINKS} SET is_primary = 0 WHERE person_id = ? AND is_primary = 1 AND NOT (organization_id = ? AND role = ?)",
            (person_id, organization_id, role),
        )
    conn.execute(
        f"""INSERT INTO {LINKS} (person_id, organization_id, role, is_primary, started_on, ended_on, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (person_id, organization_id, role) DO UPDATE SET
              is_primary = max(is_primary, excluded.is_primary),
              started_on = coalesce(excluded.started_on, started_on),
              ended_on = coalesce(excluded.ended_on, ended_on)""",
        (person_id, organization_id, role, int(is_primary), _day(started_on), _day(ended_on), clock.now_iso()),
    )
    _ensure_primary_in(conn, LINKS, "person_id = ?", (person_id,))
    return _link_row_in(conn, person_id, organization_id, role)


def update_link_in(conn: db.Conn, user: User, person_id: int, organization_id: int, role: str, **fields) -> dict:
    """Change a link's role (`new_role`), `is_primary`, `started_on` or `ended_on`. Returns the link."""
    _live_in(conn, user, "person", person_id)
    _live_in(conn, user, "organization", organization_id)
    link = _link_row_in(conn, person_id, organization_id, (role or "").strip())
    if unknown := set(fields) - {"new_role", "is_primary", "started_on", "ended_on"}:
        raise Invalid(f"unknown field(s): {', '.join(sorted(unknown))}")
    cols = {k: _day(v) for k, v in fields.items() if k in ("started_on", "ended_on")}
    if "new_role" in fields:
        cols["role"] = (fields["new_role"] or "").strip()
        if cols["role"] != link["role"] and conn.execute(
            f"SELECT 1 FROM {LINKS} WHERE person_id = ? AND organization_id = ? AND role = ?",
            (person_id, organization_id, cols["role"]),
        ).fetchone():
            raise Conflict("that person already has that role at that organization")
    if "is_primary" in fields:
        cols["is_primary"] = int(bool(fields["is_primary"]))
        if cols["is_primary"]:
            conn.execute(f"UPDATE {LINKS} SET is_primary = 0 WHERE person_id = ? AND id != ?", (person_id, link["id"]))
    if cols:
        conn.execute(f"UPDATE {LINKS} SET {', '.join(f'{c} = ?' for c in cols)} WHERE id = ?", (*cols.values(), link["id"]))
    _ensure_primary_in(conn, LINKS, "person_id = ?", (person_id,))
    return _bools(conn.execute(f"SELECT * FROM {LINKS} WHERE id = ?", (link["id"],)).fetchone())


def unlink_in(conn: db.Conn, user: User, person_id: int, organization_id: int, role: str = "") -> None:
    """Remove one link; when it was the primary, the person's oldest remaining link becomes primary."""
    _live_in(conn, user, "person", person_id)
    _live_in(conn, user, "organization", organization_id)
    link = _link_row_in(conn, person_id, organization_id, (role or "").strip())
    conn.execute(f"DELETE FROM {LINKS} WHERE id = ?", (link["id"],))
    _ensure_primary_in(conn, LINKS, "person_id = ?", (person_id,))


# ── Write: addresses and channels ────────────────────────────────────────────


def _part_cols(part: Part, fields: dict, creating: bool) -> dict:
    if unknown := set(fields) - set(part.fields) - {"is_primary"}:
        raise Invalid(f"unknown field(s): {', '.join(sorted(unknown))}")
    cols = {f: (v.strip() or None) if isinstance(v, str) else v for f, v in fields.items()}
    if part.by_kind:
        if (creating or "kind" in cols) and cols.get("kind") not in CHANNEL_KINDS:
            raise Invalid(f"kind must be one of {', '.join(CHANNEL_KINDS)}")
        if (creating or "value" in cols) and not cols.get("value"):
            raise Invalid("value is required")
    return cols


def _demote_in(conn: db.Conn, part: Part, row: dict, except_id: int | None) -> None:
    """Clear the primary in `row`'s slot (same owner, and same kind for channels)."""
    where, params = "owner_type = ? AND owner_id = ? AND id IS NOT ?", [row["owner_type"], row["owner_id"], except_id]
    if part.by_kind:
        where, params = where + " AND kind = ?", [*params, row["kind"]]
    conn.execute(f"UPDATE {part.table} SET is_primary = 0 WHERE {where}", params)


def _part_row_in(conn: db.Conn, part: Part, part_id: int) -> dict:
    row = conn.execute(f"SELECT * FROM {part.table} WHERE id = ?", (part_id,)).fetchone()
    if row is None:
        raise NotFound()
    return _bools(row)


def add_part_in(conn: db.Conn, user: User, part: str, owner_type: str, owner_id: int, **fields) -> dict:
    """Add an address (`part="address"`) or channel (`part="channel"`) to a person or organization.
    is_primary=True demotes the old primary; the first of its slot is primary anyway."""
    p = _part(part)
    before = _live_in(conn, user, owner_type, owner_id)
    now = clock.now_iso()
    cols = _part_cols(p, fields, creating=True) | {
        "owner_type": owner_type, "owner_id": owner_id, "is_primary": int(bool(fields.get("is_primary"))),
        "created_at": now, "updated_at": now,
    }
    if cols["is_primary"]:
        _demote_in(conn, p, cols, None)
    part_id = conn.execute(
        f"INSERT INTO {p.table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", tuple(cols.values())
    ).lastrowid
    _settle_in(conn, owner_type, owner_id, user, before)
    return _part_row_in(conn, p, part_id)


def update_part_in(conn: db.Conn, user: User, part: str, part_id: int, **fields) -> dict:
    """Change an address or channel. A channel moved to another kind stays primary only when
    asked (is_primary=True); its old slot promotes its next row."""
    p = _part(part)
    row = _part_row_in(conn, p, part_id)
    before = _live_in(conn, user, row["owner_type"], row["owner_id"])
    cols = _part_cols(p, fields, creating=False)
    moved = p.by_kind and cols.get("kind", row["kind"]) != row["kind"]
    primary = bool(cols["is_primary"]) if "is_primary" in cols else row["is_primary"] and not moved
    cols["is_primary"] = int(primary)
    if primary:
        _demote_in(conn, p, {**row, **cols}, part_id)
    conn.execute(
        f"UPDATE {p.table} SET {', '.join(f'{c} = ?' for c in cols)}, updated_at = ? WHERE id = ?",
        (*cols.values(), clock.now_iso(), part_id),
    )
    _settle_in(conn, row["owner_type"], row["owner_id"], user, before)
    return _part_row_in(conn, p, part_id)


def delete_part_in(conn: db.Conn, user: User, part: str, part_id: int) -> None:
    """Delete an address or channel; deleting the primary promotes the slot's oldest row."""
    p = _part(part)
    row = _part_row_in(conn, p, part_id)
    before = _live_in(conn, user, row["owner_type"], row["owner_id"])
    conn.execute(f"DELETE FROM {p.table} WHERE id = ?", (part_id,))
    _settle_in(conn, row["owner_type"], row["owner_id"], user, before)


# ── Merge ────────────────────────────────────────────────────────────────────


def _merge_links_in(conn: db.Conn, kind: str, target: int, source: int) -> None:
    """The source's primary flags are cleared before rows move, so the one-primary index never
    sees two. A (person, organization, role) collision keeps the target's row. A cleared primary
    comes back on the moved or kept row when that person has no other primary."""
    col, other = ("person_id", "organization_id") if kind == "person" else ("organization_id", "person_id")
    primaries = conn.execute(f"SELECT {other}, role FROM {LINKS} WHERE {col} = ? AND is_primary = 1", (source,)).fetchall()
    conn.execute(f"UPDATE {LINKS} SET is_primary = 0 WHERE {col} = ?", (source,))
    conn.execute(
        f"""DELETE FROM {LINKS} WHERE {col} = ? AND EXISTS (
              SELECT 1 FROM {LINKS} t WHERE t.{col} = ? AND t.{other} = {LINKS}.{other} AND t.role = {LINKS}.role)""",
        (source, target),
    )
    conn.execute(f"UPDATE {LINKS} SET {col} = ? WHERE {col} = ?", (target, source))
    for other_id, role in primaries:
        person = target if kind == "person" else other_id
        conn.execute(
            f"""UPDATE {LINKS} SET is_primary = 1 WHERE {col} = ? AND {other} = ? AND role = ?
                AND NOT EXISTS (SELECT 1 FROM {LINKS} WHERE person_id = ? AND is_primary = 1)""",
            (target, other_id, role, person),
        )


def _merge_parts_in(conn: db.Conn, kind: str, target: int, source: int) -> None:
    """Addresses and channels move to the target. A channel the target already has (same kind
    and value, ignoring case) is dropped; a source primary is demoted where the target already
    has one for that slot, and otherwise stays primary on the target."""
    scope, c, a = "owner_type = ? AND owner_id = ?", PARTS["channel"].table, PARTS["address"].table
    conn.execute(
        f"""DELETE FROM {c} WHERE {scope} AND EXISTS (
              SELECT 1 FROM {c} t WHERE t.owner_type = {c}.owner_type AND t.owner_id = ? AND t.kind = {c}.kind
                AND lower(trim(t.value)) = lower(trim({c}.value)))""",
        (kind, source, target),
    )
    conn.execute(
        f"UPDATE {c} SET is_primary = 0 WHERE {scope} AND kind IN (SELECT kind FROM {c} WHERE {scope} AND is_primary = 1)",
        (kind, source, kind, target),
    )
    conn.execute(
        f"UPDATE {a} SET is_primary = 0 WHERE {scope} AND EXISTS (SELECT 1 FROM {a} WHERE {scope} AND is_primary = 1)",
        (kind, source, kind, target),
    )
    for table in (c, a):
        conn.execute(f"UPDATE {table} SET owner_id = ?, updated_at = ? WHERE {scope}", (target, clock.now_iso(), kind, source))
    _settle_in(conn, kind, target)
    _sync_primary(conn, kind, source)


def merge_in(conn: db.Conn, kind: str, target_id: int, source_id: int, actor: User) -> dict:
    """Fold `source` into `target` (the survivor), both first resolved to their chain heads.
    Refuses a self-merge (422) and an archived target (409). Every `on_entity_merged`
    subscriber (timeline, files, reminders, notifications, apps) runs in this transaction, so
    one failing rolls the whole merge back. Returns the survivor's detail."""
    k = _kind(kind)
    target, source = resolve_in(conn, kind, target_id), resolve_in(conn, kind, source_id)
    if target == source:
        raise Invalid("cannot merge a record into itself")
    entities.authorize(actor, conn, k.entity, target, "write")
    entities.authorize(actor, conn, k.entity, source, "write")
    if _row_in(conn, kind, target)["archived_at"] is not None:
        raise Conflict(f"{kind} #{target} is archived; restore it before merging into it")
    _merge_links_in(conn, kind, target, source)
    _merge_parts_in(conn, kind, target, source)
    # TODO fields: custom field values (target's non-empty value wins, else the source's) belong
    # to the fields service, which subscribes to on_entity_merged like timeline and files do.
    entities.on_entity_merged_in(conn, k.entity, target, source)
    now = clock.now_iso()
    conn.execute(
        f"UPDATE {k.table} SET merged_into_id = ?, archived_at = coalesce(archived_at, ?), updated_at = ? WHERE id = ?",
        (target, now, now, source),
    )
    conn.execute(f"UPDATE {k.table} SET merged_into_id = ? WHERE merged_into_id = ?", (target, source))  # flat aliases
    timeline.add_system_in(conn, k.entity, target, f"merged #{source} into this record")
    changelog.record_in(conn, k.entity, target, "merged_from", None, source, actor.id)
    return _detail_in(conn, kind, target)


def merge_people_in(conn: db.Conn, target_id: int, source_id: int, actor: User) -> dict:
    return merge_in(conn, "person", target_id, source_id, actor)


def merge_organizations_in(conn: db.Conn, target_id: int, source_id: int, actor: User) -> dict:
    return merge_in(conn, "organization", target_id, source_id, actor)


# ── Top-level forms ──────────────────────────────────────────────────────────

resolve = reads(resolve_in)
get = reads(get_in)
list_records = reads(list_in)
search = reads(search_in)
organizations_for = reads(organizations_for_in)
people_for = reads(people_for_in)
find_duplicates = reads(find_duplicates_in)
create = writes(create_in)
update = writes(update_in)
archive = writes(archive_in)
restore = writes(restore_in)
resolve_or_create_organizations = writes(resolve_or_create_organizations_in)
link = writes(link_in)
update_link = writes(update_link_in)
unlink = writes(unlink_in)
add_part = writes(add_part_in)
update_part = writes(update_part_in)
delete_part = writes(delete_part_in)
merge = writes(merge_in)
merge_people = writes(merge_people_in)
merge_organizations = writes(merge_organizations_in)
