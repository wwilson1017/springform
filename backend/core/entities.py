"""The entity registry: every record type core services can attach to, and who may touch it.

An entity type is `<app>.<name>` (`core.person`, `example.widget`) backed by one table the app
owns. Every core service and router calls `authorize` before touching a record:
- missing record, unknown type, or not readable -> NotFound (404: existence is not leaked)
- readable but the action is "write" and not writable -> Forbidden (403)
- the system principal never writes, whatever the entity's can_write says

Hooks (docs/agents/authorization.md):
- sync, in the caller's transaction, cheap bookkeeping only; a failing subscriber rolls the
  whole write back: on_entity_deleted(conn, type, id), on_entity_merged(conn, type, target_id,
  source_id), on_record_changed(conn, type, id, changes, user_id).
- durable, after commit, through the outbox: after_record_changed(conn, payload) where payload
  is {entity_type, entity_id, changes, user_id}. Each subscriber gets its own outbox row.
`changes` is always a list of {field, old, new}.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from backend.core import outbox
from backend.core.errors import Forbidden, NotFound

if TYPE_CHECKING:
    from backend.core.auth.deps import User
    from backend.core.db import Conn

Action = Literal["read", "write"]
SYNC_HOOKS = ("on_entity_deleted", "on_entity_merged", "on_record_changed")
HOOKS = (*SYNC_HOOKS, "after_record_changed")
_TYPE = re.compile(r"^([a-z][a-z0-9_]*)\.[a-z][a-z0-9_]*$")
_TABLE = re.compile(r"^[a-z][a-z0-9_]*$")
_AFTER = "after_record_changed:"


def member_can_read(user: User, conn: Conn, entity_id: int) -> bool:
    """Default: any active member; the system principal (jobs) reads too."""
    return user.is_active and user.role in ("admin", "member", "system")


def member_can_write(user: User, conn: Conn, entity_id: int) -> bool:
    return user.is_active and user.role in ("admin", "member")


def title_from(table: str, column: str = "name") -> Callable[[Conn, list[int]], dict[int, str]]:
    """A title_fn reading one column of the entity's table."""

    def titles(conn: Conn, ids: list[int]) -> dict[int, str]:
        sql = f"SELECT id, {column} FROM {table} WHERE id IN (SELECT value FROM json_each(?))"
        return {r[0]: r[1] for r in conn.execute(sql, (json.dumps(ids),))}

    return titles


@dataclass(frozen=True)
class Entity:
    type: str
    table: str
    label: str
    label_plural: str
    url_fn: Callable[[int], str]
    title_fn: Callable[[Conn, list[int]], dict[int, str]]
    can_read: Callable[[User, Conn, int], bool] = member_can_read
    can_write: Callable[[User, Conn, int], bool] = member_can_write
    searchable: tuple[str, ...] = ()
    archived_column: str | None = None

    @property
    def app(self) -> str:
        return self.type.split(".", 1)[0]


CORE_ENTITIES = [
    Entity(
        "core.person", "core_people", "Person", "People", lambda i: f"/people/{i}", title_from("core_people"),
        archived_column="archived_at",
    ),
    Entity(
        "core.organization", "core_organizations", "Organization", "Organizations",
        lambda i: f"/organizations/{i}", title_from("core_organizations"), archived_column="archived_at",
    ),
]

_ENTITIES: dict[str, Entity] = {}
_SUBSCRIBERS: dict[str, list[Callable]] = {h: [] for h in SYNC_HOOKS}
_AFTER_HOOKS: list[str] = []


def register(entity: Entity) -> None:
    m = _TYPE.match(entity.type)
    if not m:
        raise ValueError(f"Entity type {entity.type!r} must look like '<app>.<name>'")
    if not _TABLE.match(entity.table) or not entity.table.startswith(f"{m.group(1)}_"):
        raise ValueError(f"Entity {entity.type!r}: table {entity.table!r} must start with '{m.group(1)}_'")
    if entity.type in _ENTITIES:
        raise ValueError(f"Entity type {entity.type!r} is registered twice")
    _ENTITIES[entity.type] = entity


def subscribe(hook: str, fn: Callable) -> None:
    if hook not in HOOKS:
        raise ValueError(f"Unknown hook {hook!r}; expected one of {', '.join(HOOKS)}")
    if hook == "after_record_changed":
        name = f"{_AFTER}{fn.__module__}.{fn.__qualname__}"
        outbox.register(name, fn)
        _AFTER_HOOKS.append(name)
    else:
        _SUBSCRIBERS[hook].append(fn)


def clear() -> None:
    _ENTITIES.clear()
    for subscribers in _SUBSCRIBERS.values():
        subscribers.clear()
    _AFTER_HOOKS.clear()


def all_entities() -> list[Entity]:
    return list(_ENTITIES.values())


def get(entity_type: str) -> Entity:
    try:
        return _ENTITIES[entity_type]
    except KeyError:
        raise NotFound(f"unknown entity type {entity_type!r}") from None


def exists(conn: Conn, entity_type: str, entity_id: int) -> bool:
    entity = get(entity_type)
    return conn.execute(f"SELECT 1 FROM {entity.table} WHERE id = ?", (entity_id,)).fetchone() is not None


def assert_exists(conn: Conn, entity_type: str, entity_id: int) -> Entity:
    if not exists(conn, entity_type, entity_id):
        raise NotFound()
    return get(entity_type)


def authorize(user: User, conn: Conn, entity_type: str, entity_id: int, action: Action = "read") -> Entity:
    """The entity, when `user` may perform `action` on the record. See the module docstring."""
    if action not in ("read", "write"):
        raise ValueError(f"action must be 'read' or 'write', not {action!r}")
    entity = assert_exists(conn, entity_type, entity_id)
    if not entity.can_read(user, conn, entity_id):
        raise NotFound()
    if action == "write" and (user.role == "system" or not entity.can_write(user, conn, entity_id)):
        raise Forbidden()
    return entity


def url_for(entity_type: str, entity_id: int) -> str:
    return get(entity_type).url_fn(entity_id)


def titles_for(user: User, conn: Conn, entity_type: str, ids: Iterable[int]) -> dict[int, str]:
    """Titles of the records `user` may read; the rest are dropped, not masked."""
    entity = get(entity_type)
    titles = entity.title_fn(conn, list(dict.fromkeys(int(i) for i in ids)))
    return {i: t for i, t in titles.items() if entity.can_read(user, conn, i)}


def delete_record_in(conn: Conn, entity_type: str, entity_id: int) -> None:
    """Delete one record and, through on_entity_deleted, everything core and apps hang off it.
    The caller has already authorized the delete."""
    entity = assert_exists(conn, entity_type, entity_id)
    on_entity_deleted_in(conn, entity_type, entity_id)
    conn.execute(f"DELETE FROM {entity.table} WHERE id = ?", (entity_id,))


def on_entity_deleted_in(conn: Conn, entity_type: str, entity_id: int) -> None:
    for fn in _SUBSCRIBERS["on_entity_deleted"]:
        fn(conn, entity_type, entity_id)


def on_entity_merged_in(conn: Conn, entity_type: str, target_id: int, source_id: int) -> None:
    for fn in _SUBSCRIBERS["on_entity_merged"]:
        fn(conn, entity_type, target_id, source_id)


def on_record_changed_in(conn: Conn, entity_type: str, entity_id: int, changes: list[dict], user_id: int | None) -> None:
    for fn in _SUBSCRIBERS["on_record_changed"]:
        fn(conn, entity_type, entity_id, changes, user_id)


def after_record_changed_in(conn: Conn, entity_type: str, entity_id: int, changes: list[dict], user_id: int | None) -> None:
    """Queue one durable outbox row per after_record_changed subscriber; they run after COMMIT."""
    payload = {"entity_type": entity_type, "entity_id": entity_id, "changes": changes, "user_id": user_id}
    for hook in _AFTER_HOOKS:
        outbox.enqueue_in(conn, hook, payload)
