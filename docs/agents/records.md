# Record services

**What this covers:** the §4 record services every entity gets: timeline (and `record_changes_in`), files (publication, sweep, crash cases, safe serving), custom fields, saved views, the reports registry, notifications, reminders, the change log, and the frontend `records/` components.
**Who reads it:** W2 (record-service backends), W3 (change log), W11 (record-services frontend), any app that shows a record page.

Every service checks `entities.authorize` before touching a record (`authorization.md`). Every service and published function comes as `fn` / `fn_in(conn, …)` (`database-and-transactions.md`), with these exceptions: `timeline.api.list_for` has no `_in` form, `record_changes_in` has only the `_in` form, and a report's `run` needs none because it opens no transaction. Most services live in `backend/core/<service>/{service.py, api.py, router.py}`. Two do not: the change-log writer is the single module `backend/core/changelog.py`, with its route in `backend/core/platform/`, and reports are `backend/core/reports/{registry.py, service.py, router.py}` with no `api.py` (apps import `Report` from `backend.core.reports.registry`).

## 1. Timeline

Source: CakeCRM `backend/crm/chatter_service.py` (345 → ~280) and `backend/crm/mention_notify.py` (84).

```sql
core_timeline(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entity_type, entity_id,
  kind CHECK (kind IN ('note','comment','field_change','system')),
  body,
  changes,          -- JSON
  author_user_id,
  …
)
core_timeline_mentions     -- mention rows
-- plus an FTS5 (unicode61) index over timeline bodies
```

### `record_changes_in`

```python
record_changes_in(conn, type, id, before, after, user_id)
```

A change is a key present in both `before` and `after` whose value differs (`id`, `created_at` and `updated_at` are not tracked). When nothing changed it writes nothing. Otherwise, in the caller's transaction, it writes:

1. one `field_change` row in `core_timeline`, whose `changes` holds the list `[{field, old, new}]`;
2. one `core_change_log` row **per changed field**;
3. one `core_outbox` row per `after_record_changed` subscriber, with the payload `{entity_type, entity_id, changes: [{field, old, new}], user_id}`;

and runs the sync `on_record_changed` subscribers (through `on_record_changed_in`) with the same fields. The CRM sets `touch_dirty` from that sync hook (`authorization.md` §3). The scoring and touch-count imports at CakeCRM `chatter_service.py:25` become CRM subscribers.

### Rules

1. Listing and adding notes go through `entities.authorize`; a note needs write access to its record. `record_changes_in`, `add_system_in` and the delete and merge hooks do not authorize: the caller has already authorized the edit.
2. `system` rows record platform actions (e.g. "merged #<source> into this record"). Core writes them with `timeline.add_system_in(conn, entity_type, entity_id, body)`; the author is the system principal (`id=0`), and the acting user is in the change log.
3. Merges repoint timeline rows keeping the original author and time (`contacts.md`).
4. A mention in `body` is written `@[Name](user:ID)`. Each mentioned active human user who can read the record gets a `core_timeline_mentions(timeline_id, user_id, display_name)` row and a notification (`deliver_in`, in the note's transaction), except the author. Anyone else named in the body gets neither.
5. A comment is stored and listed exactly like a note; only its `kind` differs.

### API

```
GET  /api/core/timeline?entity_type=&entity_id=&before=<id>&limit=  -> [{id, kind: "note"|"comment"|"field_change"|"system", body, changes, author:{id,name}|null, created_at}], newest first
POST /api/core/timeline {entity_type, entity_id, body, kind?: "note"|"comment"} -> the new entry; kind defaults to "note"
GET  /api/core/timeline/mentionable?q=  -> [{id, name}], active human users for the @-mention picker, by name, at most 20
```

`limit` defaults to 50, at most 200. To page back, pass the last id seen as `before`. `changes` is null except on `field_change` rows.

## 2. Files

Source: CakeCRM `backend/crm/attachment_service.py` (379 → ~330) and `backend/core/thumbnails.py` (~260).

```sql
core_files(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entity_type, entity_id, timeline_id,
  filename, mime_type, byte_size, sha256,
  thumb BLOB,          -- thumbnail stored in the row
  uploaded_by,
  …
)
-- UNIQUE(entity_type, entity_id, sha256)

core_file_blobs(sha256 PK, byte_size, created_at, unreferenced_since,
                missing_at)   -- added by 20261020000200_core_files.sql
```

**Bytes live on the volume** at `/data/files/<sha[:2]>/<sha>`, never in the DB (`VACUUM INTO` and Litestream would copy every PDF nightly). Thumbnails live in the row.

### Publication (upload)

**Publication and sweep share the write lock, so they cannot interleave.**

1. Copy the upload to `/data/files/tmp/<uuid>`, enforcing the size cap (setting `files.max_bytes`, default 25 MB): an oversize upload gets **413** `file_too_large`. Starlette has already spooled the whole multipart body by then, so the cap is enforced after receipt (a marked simplification).
2. Hash (sha256) and `fsync`. This happens **outside** the lock.
3. Inside **one** `transaction()`:
   1. upsert `core_file_blobs` (clearing `unreferenced_since`);
   2. insert the `core_files` row;
   3. `rename` the tmp file into `/data/files/<sha[:2]>/<sha>` (a local disk op, allowed under the lock);
   4. `COMMIT`.
4. A new attachment returns **201** with the `File`. The same bytes uploaded to the same record (`UNIQUE(entity_type, entity_id, sha256)`) return **200** with the existing row.
5. When a blob's last `core_files` row is deleted, the files service sets `core_file_blobs.unreferenced_since` in the same transaction.

### Sweep (`core.files_sweep`, 03:30 install-local)

1. Inside **one** `transaction()`:
   1. select blobs whose `unreferenced_since` is older than **7 days** **and** whose sha256 appears in **no retained backup manifest**;
   2. re-check each is still unreferenced;
   3. delete their rows;
   4. unlink their files;
   5. set `missing_at` on every blob row whose file is missing, logging it, and clear it on one whose file came back;
   6. remove each file under `files/<xx>/` that has no blob row and is over 24 h old (an orphan);
   7. `COMMIT`.
2. Outside the lock: remove tmp files older than **24 h**.
3. A blob is never deleted while any retained manifest lists it, so every retained backup set restores whole (`deploy.md`).

### Crash cases

| Crash | Outcome |
|---|---|
| Rollback after `rename` | A file without a row. The sweep treats it as an orphan after 24 h. |
| A row whose file is missing | The sweep sets `core_file_blobs.missing_at` and logs it. Download answers **410** `file_missing`; it is never silently served. |

### Safe serving

1. Download requires `authorize(read)` on the parent record.
2. Served with `Content-Disposition: attachment` and `X-Content-Type-Options: nosniff`.
3. `mime_type` comes from the allow-list `ALLOWED_MIME` in `backend/core/files/service.py`; anything else, HTML and SVG included, is served as `application/octet-stream`.
4. Upload requires `authorize(write)` on the parent record.
5. `DELETE` requires `authorize(write)` on the parent record.

### API

```
GET  /api/core/files?entity_type=&entity_id=  -> [File]
     File = {id, filename, mime_type, byte_size, sha256, created_at, uploaded_by: {id, name} | null, has_thumb}
POST /api/core/files  multipart fields entity_type, entity_id, file -> 201 File; 200 File when already attached
GET  /api/core/files/{id}/download   -> bytes, Content-Disposition: attachment; 410 file_missing
GET  /api/core/files/{id}/thumb      -> image/jpeg (read access to the parent record)
DELETE /api/core/files/{id}          -> 204
```

## 3. Custom fields

Source: CakeCRM `backend/crm/field_service.py` (427 → ~400).

| Item | Contract |
|---|---|
| Tables | `core_field_definitions`, `core_field_values`. |
| Entity check | CakeCRM's `VALID_ENTITY_TYPES` → `entities.get`. |
| Types | `text`, `number`, `boolean`, `date`, `select`, `multiselect`, `url`, `user`. |
| UI | One generic React renderer (`CustomFields`). |
| Authorization | Values are read and written only after `authorize`. |
| Merge | Target's non-empty value wins, else the source's. |

```sql
core_field_definitions(id, entity_type, key, label,
                       type CHECK (type IN ('text','number','boolean','date','select','multiselect','url','user')),
                       options,    -- JSON list; select and multiselect only
                       required,   -- advisory: shown in the UI, not enforced
                       position, archived_at, created_at, updated_at)   -- UNIQUE(entity_type, key)
core_field_values(entity_type, entity_id, definition_id, value JSON, updated_at, updated_by)
                       -- PRIMARY KEY (entity_type, entity_id, definition_id); an empty value has no row
```

```
GET    /api/core/fields/definitions
POST   /api/core/fields/definitions
PATCH  /api/core/fields/definitions/{id}
DELETE /api/core/fields/definitions/{id}    204
GET    /api/core/fields/values
PUT    /api/core/fields/values
GET    /api/core/fields/entity-types         [{type, label, label_plural}] from the entity registry (the admin's type picker)
```

## 4. Saved views

Source: CakeCRM `backend/saved_views/` (356 → ~320). `Json()` → `json.dumps`.

```sql
core_saved_views(id, surface, entity_type, name, version, payload JSON, owner_user_id, is_shared, created_at, updated_at)
  -- surface is '<app>.<screen>', e.g. 'example.widgets'; payload is opaque to the server
```

1. Views store filters, not rows, so there is no record authorization beyond ownership and `is_shared`. The owner or any admin may edit, share or delete a view. Someone else's private view is 404; a shared view the caller may not edit is 403.
2. The server refuses a stale edit: `PATCH` must send the `version` it was based on, a mismatch answers **409** `stale_view`, and every edit bumps `version` (sharing does not).
3. The screen's own schema lives in the payload: `SavedViewBar` stores `{schema_version, value}` and refuses to apply a view whose `schema_version` differs from the screen's (shown disabled with the reason, so its owner can still overwrite or delete it). On 409 `stale_view` it reloads the list and asks the user to retry.

```
GET    /api/core/views
POST   /api/core/views
PATCH  /api/core/views/{id}
DELETE /api/core/views/{id}           204
POST   /api/core/views/{id}/share
```

## 5. Reports registry

New (~250) + CakeCRM `crm/export.py` `_cell`.

```python
Report(key, label, app, run, params=None, admin_only=False, roles=("admin", "member"))
# run(params, user) -> (columns, rows); key is '<app>.<name>'; roles is set from the app manifest at mount
```

1. Apps register via `reports.py` (`REPORTS = [Report(...)]`).
2. `run` receives the user and **must apply `can_read`**.
3. An app's reports default to "user has one of the app's roles" before their own checks; `admin_only` restricts to admins.
4. `GET /api/core/reports` lists the reports the caller may run. `GET /api/core/reports/{key}` runs one and returns `{columns, rows}`: every query parameter is a report param, and an unknown one, `format` included, is refused with 422. `GET /api/core/reports/{key}/csv` (served from `backend/core/export/router.py`) streams the same report as CSV through `backend.core.export.csv_export.stream_csv`, after the same role check and param parsing (`reports.service.run`: defaults applied, bad params 422).
5. CakeCRM's `report_service.py` stays CRM-owned in `apps/crm/reports.py`.

`params` is a JSON schema object, `{"type": "object", "properties": {...}, "required": [...]}`. Each property has a `type` of `integer`, `number`, `boolean` or `string` (`format: "date"` allowed) and an optional `default`. Query-string values are coerced to those types, empty ones count as absent, and a missing required one is refused.

## 6. Notifications

Source: CakeCRM `backend/notifications/` (767 → ~650).

```sql
core_notifications(
  id, user_id NOT NULL, title, message,
  entity_type NULL, entity_id NULL,
  link, created_at, read_at, suppressed_at
)
core_notification_deliveries(notification_id, channel, status, attempts, last_error, sent_at)
core_push_subscriptions
-- VAPID keys live in core_settings (notifications.vapid_public_key / _private_key), generated
```

### `deliver_in`

```python
deliver_in(conn, title, message, *, user_id=None, entity: tuple[str, int] | None = None, link=None) -> list[int]
```

Everything after `message` is keyword-only.

1. Inserts one `core_notifications` row per recipient **in the caller's transaction**, so the in-app notification is **exactly-once**. Returns the new ids.
2. `user_id=None` expands to every **active human** user who may read `entity` (never the system principal). A broadcast is therefore one row per user, and read state is per user. A given `user_id` gets a row only if that user is an active human who may read `entity`; otherwise nothing is written. An unknown entity type or a missing record raises 404. `link` defaults to the record's URL from the entity's `url_fn`.
3. Inserts a `queued` row in `core_notification_deliveries` for each registered channel enabled for that recipient. A channel is `register_channel(name, send, *, enabled_in=None)`; web push registers itself as one.

### The notification remembers its record

1. Listing and reading re-run `entities.authorize(read)` on `(entity_type, entity_id)` and hide rows that fail, setting `suppressed_at`.
2. `flush` re-checks the same before sending a queued delivery and drops it if access is gone.
3. **A message already delivered externally cannot be recalled.** The contract says so.
4. Merges repoint notifications on the source to the target, like reminders (`contacts.md`).
5. Deleting a record hides its notifications (its `on_entity_deleted` hook sets `suppressed_at`); the rows are kept.

### External delivery (`core.notifications_flush`, every 30 s)

1. Sends, then records `sent_at`. A crash between the two re-sends: external channels are **at-least-once**.
2. The payload carries `notification_id`, so the service worker drops a duplicate push.
3. Failures bump `attempts` and record `last_error`.
4. CakeCRM's Telegram branch becomes a `register_channel` extension point.

Delivery `status` is `queued`, `sent`, `failed` or `dropped`; a delivery fails for good after 5 attempts.

```
GET    /api/core/notifications              the caller's notifications
GET    /api/core/notifications/unread-count
POST   /api/core/notifications/read-all
POST   /api/core/notifications/{id}/read
GET    /api/core/notifications/push/public-key
POST   /api/core/notifications/push/subscribe
DELETE /api/core/notifications/push/subscribe
```

## 7. Reminders

Source: CakeCRM `backend/reminders/` (767 → ~700). `recurrence.py` is new, ported in spirit from cake_os's reminder recurrence.

```sql
core_reminders(id, owner_user_id, entity_type NULL, entity_id NULL, title, note, due_at,
               repeat,       -- JSON {freq: daily|weekly|monthly|yearly, anchor, time, tz}; NULL = once
               series_id,    -- the first occurrence's id, shared by the series
               status CHECK (status IN ('open','done','voided','snoozed')), void_reason,
               fired_at, created_at, updated_at)
```

1. Port: `INTEGER[]` / `ANY()` → `json_each`; `SKIP LOCKED` → plain select inside `transaction()`; the `crm.service` / `gtd_common` imports are cut.
2. Job `core.reminders_fire_due` every 60 s marks `fired_at` **and** calls `deliver_in` **in the same transaction**.
3. At fire time the reminder re-checks `authorize(read)` for its owner and **voids itself** otherwise.
4. Merges repoint reminders (`contacts.md`).
5. Deleting a record voids its reminders (`status = 'voided'`, `void_reason = 'record deleted'`) instead of deleting them.

```
GET    /api/core/reminders            the caller's reminders
POST   /api/core/reminders
GET    /api/core/reminders/for        a record's reminders
PATCH  /api/core/reminders/{id}
POST   /api/core/reminders/{id}/snooze
POST   /api/core/reminders/{id}/done
DELETE /api/core/reminders/{id}       204
```

## 8. Change log

```sql
core_change_log(id, at, user_id, app, entity, entity_id, field, old, new, reason, request_id,
                deleted_at TEXT NULL)
```

1. `record_changes_in` writes one row per changed field, alongside the single timeline `field_change` row.
2. `core.changelog.record_in(conn, entity_type, entity_id, field, old, new, user_id, *, reason=None, request_id=None)` writes one row; `old` and `new` are stored as JSON.
3. Rows written before a delete are kept: they keep `entity_id`, and the delete cascade sets their `deleted_at`, so history stays distinguishable from any later record.
4. The ChangeLog viewer and `/api/core/changelog` check every row. A row about a live record is shown when the caller may read it. A row about a deleted record, or about an entity type that is no longer installed, is shown only to its author (`user_id` equal to the caller). Admins get no extra access, so a private record's history stays private after the record is gone. Such rows have `title` and `url` null.
5. `user_id` may be the system principal (`id=0`) for unattended actions.

```
GET /api/core/changelog?app=&user_id=&entity_type=&entity_id=&before=<id>&limit=
    -> [{id, at, user: {id, name} | null, app, entity_type, entity_id, title, url,
         field, old, new, reason, deleted_at}], newest first
```

`before` is the id cursor: pass the last row's id for the next page. The route is served from `backend/core/platform/router.py`.

## 9. Frontend (`frontend/src/core/records/`)

**Record props are `{entityType: string; entityId: number}`.** Sources are CakeCRM unless noted; `docs/PROVENANCE.md` has the rows.

| Export | Props | Contract |
|---|---|---|
| `RecordServices` | `{entityType, entityId}` | `CustomFields` + `RemindersPanel`, stacked. What a record page adds beside its own fields; `Timeline` and `Attachments` stay separate so the page places them. |
| `CustomFields` | `{entityType, entityId}` | The type's fields and values; nothing when the type has none. Edit sends only changed values in one all-or-nothing `PUT` (empty clears with null). A 403 turns it read-only. |
| `CustomFieldSettings` (default export) | none | Settings → Records → Custom fields (admin): type picker, create, edit, archive, restore, reorder. |
| `SavedViewBar<T>` | `{surface, entityType?, value: T, onChange(value: T), schemaVersion: number}` | Apply, save as, rename, overwrite, share/unshare, delete. Every edit sends the server `version`; schema mismatch refused (§4). |
| `ReportsPage` (default, `/reports`), `ReportParamsForm`, `ReportTable` | `ReportParamsForm {schema, values, onChange}`, `ReportTable {result}` | Role-filtered list, a form generated from the `params` schema (§5), run, and "Download CSV" to `/api/core/reports/{key}/csv` with the same query. |
| `NotificationBell` | none | In the header (`shell/Layout.tsx`). Unread count polled every 60 s while visible; latest 10; opening one marks it read and follows its same-origin `link`. |
| `NotificationsPage` (default, `/notifications`) | none | All or unread, mark read, mark all read. |
| `PushCard` (default) | none | Settings → Notifications → Push notifications (members). Registers `/sw.js` only on opt-in. `public/sw.js` shows `{title, body}` tagged with `notification_id` and opens `url` on click. |
| `RemindersPage` (default, `/reminders`) | none | The caller's reminders: status and date filters (a `SavedViewBar` on surface `core.reminders`), create without a record, edit, snooze presets, done, delete. |
| `RemindersPanel` | `{entityType, entityId}` | `GET /for`: everyone's reminders on the record; actions only on `mine`; add one for this record. |
| `NoteComposer`, `MentionPicker`, `useMentionPicker` | `NoteComposer {entityType, entityId, onPosted}` | `@` lists `/api/core/timeline/mentionable?q=`; picking inserts `@[Name](user:ID)`. `Timeline` renders mentions as chips. |
| `Timeline`, `Attachments` | `{entityType, entityId}` | `Attachments` shows `/thumb` when `has_thumb`, download and delete (a 403 says the record isn't writable). |

Core pages, nav and settings come through the shell seams: `routes.tsx` (`reports`, `reminders`, `notifications`, lazy), `nav.tsx` (Reminders and Reports in the user menu), `settingsCards.ts` (`notifications` order 8, member; `records` order 35, admin).

## Tests that pin this

- `record_changes_in` writes one timeline row + one change-log row per changed field and fires the hook after commit.
- File upload round-trips sha256, dedupes, a fresh blob survives `sweep`, an unreferenced blob survives 6 days and goes at 8.
- A deterministic interleaving (sweep claims the lock, an upload of the same bytes waits, sweep deletes, upload republishes) ends with the file present and referenced.
- Download refused without `can_read`, served as attachment.
- Reminders fire under a frozen clock → notification row in the same transaction.
- `flush` retries and never duplicates.
- A team todo notifies a member, then goes private: before `flush` the delivery is dropped and the row hidden; after an in-app delivery the row is hidden on next read.
- Two members: private todo invisible through timeline, files, fields, reminders, search, reports, titles, change log, mention delivery.
- Vitest: `Timeline`, `CustomFields` by type, `SavedViewBar` stale-version refusal.
- Playwright: note with @mention → attachment → reminder fires (frozen clock).

## Source

Build plan: §4 (entity registry, services table, frontend), §1 (`core_change_log`, backups pin blobs), §3 (merge effects), §11 (job cadences), SQLite rules (outbox, identifiers), Step 1 (timeline, files, frozen stubs), Verification. API block (orchestrator) for timeline and files routes.
