# Authorization

**What this covers:** the `Entity` dataclass and the entity registry (`backend/core/entities.py`), `authorize`, `titles_for`, `delete_record_in`, the hook registry, how manifest roles reach routers, entities, reports and tools, the rule that stored copies and deliveries obey the same checks, the system principal, and the two-member test.
**Who reads it:** anyone writing a core service or router that touches a record, any app registering an entity, and anyone writing a surface that copies or delivers record data (change log, mentions, reminders, notifications, export, reports, Whisk tools).

## 1. `Entity`

`backend/core/entities.py` (~260 lines, new).

```python
@dataclass(frozen=True)
class Entity:
    type: str; table: str; label: str; label_plural: str
    url_fn: Callable[[int], str]
    title_fn: Callable[[Conn, list[int]], dict[int, str]]
    can_read: Callable[[User, Conn, int], bool]     # default: any active member
    can_write: Callable[[User, Conn, int], bool]    # default: any active member
    searchable: tuple[str, ...] = (); archived_column: str | None = None
```

| Field | Meaning |
|---|---|
| `type` | Entity type string, e.g. `core.person`, `core.organization`, `crm.deal`, `todos.item`. |
| `table` | The owning table (`core_people`, `crm_deals`, …). Uses `INTEGER PRIMARY KEY AUTOINCREMENT`. |
| `label`, `label_plural` | Display names. |
| `url_fn(id)` | Frontend URL of a record. |
| `title_fn(conn, ids)` | Batch title lookup, `{id: title}`. |
| `can_read(user, conn, id)` | Default: any active member. |
| `can_write(user, conn, id)` | Default: any active member. |
| `searchable` | Searchable columns. |
| `archived_column` | Column holding the archive marker, if any. |

Apps register entities in `entities.py` as `ENTITIES = [Entity(...)]`. Core registers `core.person` and `core.organization`.

`can_read` and `can_write` always take `(user, conn, id)`, as in the dataclass.

Entity type strings are `<slug>.<name>`; core's use `core.`. The format is enforced, and the contract test checks it.

### Registered entity types in the plan

| Type | Owner | `can_read` / `can_write` |
|---|---|---|
| `core.person` | core | Any active member. |
| `core.organization` | core | Any active member. |
| `crm.deal` | `crm` | Any member. |
| `todos.item` | `todos` | The Todos permission model (§6 below). |
| example's widget | `example` | A restrictive `can_read` (private widgets). Rule and type name: Open (pinned by the implementing workstream, which updates this doc; `apps-and-contracts.md` §7). |

## 2. Functions

| Function | Contract |
|---|---|
| `get(type)` | The registered `Entity`, or an error for an unknown type. Replaces CakeCRM's `VALID_ENTITY_TYPES` checks. |
| `assert_exists(conn, type, id)` | Raises when the record does not exist. |
| **`authorize(user, conn, type, id, "read" \| "write")`** | `read`: **404** when the record is missing **or** not readable, so existence never leaks. `write`: **404** when missing or not readable, **403** when readable but not writable. Called by every core service and router **before touching a record**. |
| `url_for(type, id)` | The record's URL via `url_fn`. |
| `titles_for(user, conn, type, ids)` | Titles via `title_fn`, **dropping titles the user may not read**. |
| `delete_record_in(conn, type, id)` | Deletes the record and runs the `on_entity_deleted` subscribers (through `on_entity_deleted_in`) **in the same transaction**. |

`entities.delete_record_in` is the only delete function; there is no form without `_in`, and it always runs on the caller's `conn`.

Open (pinned by the implementing workstream, which updates this doc): `url_for`'s exact signature is not stated.

Role-guarded routes refuse with **403**: a member calling an admin-only app's API (§4).

## 3. Hooks

Apps subscribe in `hooks.py`. The registry registers the subscribers; nothing uses signals.

```python
# backend/apps/<slug>/hooks.py
HOOKS = {
    "on_entity_deleted": [...],
    "on_entity_merged": [...],
    "on_record_changed": [...],
    "after_record_changed": [...],
}
```

| `HOOKS` key | Kind | Subscriber | Runs | Use |
|---|---|---|---|---|
| `on_entity_deleted` | Sync | `fn(conn, entity_type, entity_id)` | Inside the deleting transaction. | Cascade owned rows (core uses it for timeline, files, fields, reminders, notifications; the change log stamps `deleted_at`). |
| `on_entity_merged` | Sync | `fn(conn, entity_type, target_id, source_id)` | Inside the merge transaction. | Repoint or reconcile app rows (CRM keeps the higher `crm_person_scores` score). |
| `on_record_changed` | Sync | `fn(conn, entity_type, entity_id, changes, user_id)` | Inside the changing transaction. | Cheap bookkeeping (CRM sets `crm_deals.touch_dirty`). |
| `after_record_changed` | Durable, via the outbox | `fn(conn, payload)` | After `COMMIT`: the single drainer runs it inside its own transaction, which also sets `processed_at`, so it runs exactly once. Each subscriber gets its own outbox row. | Follow-up DB work that must survive a crash. It runs inside a transaction, so no network or LLM call: external work goes to an `external=True` outbox consumer or the app's own job (`database-and-transactions.md` §4). |

`changes` is always a list, one item per changed field. The `after_record_changed` payload carries the same fields:

```
{entity_type, entity_id, changes: [{field, old, new}], user_id}
```

Core's dispatchers carry `_in` and run on the caller's `conn`: `on_entity_deleted_in`, `on_entity_merged_in` and `on_record_changed_in` call the sync subscribers, and `after_record_changed_in` writes the outbox rows. `delete_record_in`, the merge functions and `record_changes_in` call them.

Rules:

1. Sync subscribers receive `conn` and run in the caller's transaction; a failing subscriber rolls the whole write back.
2. Sync subscribers do cheap bookkeeping only: set a flag, write a row. No network, no `transaction()`.
3. After-commit work is durable: a `core_outbox` row written in the same transaction as the change.

## 4. Manifest roles reach the API

1. `registry.mount()` adds `Depends(require_roles(manifest.roles))` to each app's router. A member calling an admin-only app's API directly gets **403**.
2. Entities, reports and tools registered by an app **default their `can_read` / `can_write` to "user has one of the app's roles"**, applied **before** the app's own check.
3. `registry.for_user(user)` filters tools by `enabled(user)` and app roles (`agent.md`).
4. `Report.admin_only` restricts a report to admins (`records.md`).

## 5. Stored copies and deliveries obey the same rules

A copy of record data (an audit row, a notification, a reminder, an export) is checked against the record's current `can_read` when it is shown or delivered, not only when it was written.

| Surface | Rule |
|---|---|
| Change log | The ChangeLog viewer and `/api/core/changelog` apply `authorize(read)` **per row** and hide the rest. |
| @-mentions | An @-mention notifies only users who `can_read` the record. |
| Reminders | Re-check `authorize(read)` for their owner **at fire time** and void themselves otherwise. |
| Notifications | Listing and reading re-run `authorize(read)` on `(entity_type, entity_id)` and hide rows that fail (setting `suppressed_at`); `flush` re-checks before sending a queued external delivery and drops it if access is gone. A message already delivered externally cannot be recalled. |
| Broadcasts | Expanded at creation into one `core_notifications` row per active human user who may read the entity, so read state is per user. |
| Titles | `titles_for` drops titles the user may not read. |
| Reports | `run(params, user)` receives the user and must apply `can_read`. |
| Fields | Values are read and written only after `authorize`. |
| Files | Download requires `authorize(read)` on the parent record; upload and delete require `authorize(write)`. |
| Timeline | Reads and writes go through `authorize`. |
| Saved views | Store filters, not rows; no record authorization beyond ownership / `is_shared`. |
| Todos `/for/{entity_type}/{entity_id}` | `authorize(read)` on the record first, then team todos plus the caller's private ones. |
| Admin CSV export | Rows the exporting admin cannot `can_read` are left out (`sheets-and-export.md`). |
| Whisk tools | `targets(args)` records are authorized for `write` inside the approval transaction (`agent.md`). |

## 6. Reference: `todos.item`

The restrictive entity the two-member test uses. `apps/todos/entities.py` registers `todos.item` with `can_read` / `can_write` implementing exactly this, so core timeline, files and reminders on a todo obey it:

1. Private todos: owner only (read, write, complete).
2. Team todos: any active member may view, edit, complete, reassign.
3. Admins see team todos and their own, never others' private ones.
4. Deactivating a user hides their private todos (an admin "transfer" moves them to another owner) and leaves team todos in place.

## 7. The system principal

| Property | Value |
|---|---|
| Row | `core_users` `id=0`, `role='system'`, email `system@springform.local`, `password_hash='!'`. Seeded by the core init migration. |
| Why | So `user_id` foreign keys on tool runs, timeline rows and change-log rows can record unattended actions. |
| Authentication | Never. Login, Google, invite and MCP-link minting all reject `role='system'`. |
| Excluded from | User listings, notification recipients, and "every active user" expansions. |
| Reads | Through the entity's `can_read`, with the system user treated as a **member**. Owner-only rules refuse it, so it reads no private records. |
| Writes | `authorize(system, …, "write")` is **always refused**. |
| Jobs | Jobs call services with the system `User` object directly. `require_roles` is HTTP-only, and HTTP can never authenticate as the system user. |
| Agent | Unattended runs (`source='job'`) run as the system principal and may only call tools that are `writes=False`, not `always_confirm`, not remote, not `untrusted_source`, enforced in `registry.for_source` (`agent.md`). |
| Bootstrap | First-run checks look for the absence of **human** accounts (`WHERE role != 'system'`), not an empty table (`auth.md`). |

The Todos team rev is stored in `todos_sync` at `user_id = 0` on purpose: 0 is the system principal's id, because the team rev belongs to no human.

## 8. The two-member test

Two members, one private todo. Every core surface refuses the other member:

- todos (the app's own routes);
- timeline;
- files;
- custom fields;
- reminders, including a reminder fired after the todo went private;
- search;
- reports;
- titles;
- change log;
- mention delivery.

Plus: a member calling an admin-only app's API directly gets 403. Step 1b runs the same check on an `example` record across every surface built in Step 1.

Open (pinned by the implementing workstream, which updates this doc): which search endpoint the "search" surface means (contacts FTS, timeline FTS, a global search) is not stated.

## Tests that pin this

- Two members: private todo invisible through todos, timeline, files, fields, reminders, search, reports and titles; also change log, mention delivery and a reminder fired after the todo went private.
- A member calling an admin-only app's API directly gets 403; `require_admin` 403.
- Download refused without `can_read`, served as attachment.
- A team todo notifies a member, then goes private: before `flush` the delivery is dropped and the row hidden; after an in-app delivery the row is hidden on next read.
- Reset an app holding a private record with attachments and notes, create a new record visible to another member, and assert none of the old content attaches to or is readable through it.
- Export: a two-user test proves a private todo is absent from the other admin's export.
- Setup test runs against the real migrated, seeded database (system row present).

## Source

Build plan: §4 (entity registry and "stored copies"), §2 (system principal), §5 (system principal for jobs, `for_source`), §8 (Todos permissions), §9 (export rows), Architecture → app contract, SQLite rules (identifiers, hooks), Risks 3, Verification. API block (orchestrator) for status codes.
