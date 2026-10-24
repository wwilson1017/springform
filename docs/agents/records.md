# Record services

**What this covers:** the §4 record services every entity gets: timeline (and `record_changes_in`), files (publication, sweep, crash cases, safe serving), custom fields, saved views, the reports registry, notifications, reminders, the change log, and the frontend `records/` components.
**Who reads it:** W2 (record-service backends), W3 (change log), W11 (record-services frontend), any app that shows a record page.

Every service checks `entities.authorize` before touching a record (`authorization.md`). Every service and published function comes as `fn` / `fn_in(conn, …)` (`database-and-transactions.md`). Each service lives in `backend/core/<service>/{service.py, api.py, router.py}`.

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

In the caller's transaction it writes:

1. one `field_change` row in `core_timeline`;
2. one `core_change_log` row;
3. a `core_outbox` row so the `after_record_changed` subscribers run after commit, with the payload `{entity_type, entity_id, changes: {field: [old, new]}, user_id, at}`;

and runs the sync `on_record_changed` subscribers (through `on_record_changed_in`) with the same fields. The CRM sets `touch_dirty` from that sync hook (`authorization.md` §3). The scoring and touch-count imports at CakeCRM `chatter_service.py:25` become CRM subscribers.

### Rules

1. Reads and writes go through `entities.authorize`.
2. `system` rows record platform actions (e.g. "merged #<source> into this record").
3. Merges repoint timeline rows keeping the original author and time (`contacts.md`).
4. A mention in `body` is written `@[Name](user:ID)`. It notifies only users who `can_read` the record (`deliver_in` to each mentioned user who passes).

### API

```
GET  /api/core/timeline?entity_type=&entity_id=&before=<id>&limit=50  -> [{id, kind: "note"|"comment"|"field_change"|"system", body, changes, author:{id,name}, created_at}], newest first
POST /api/core/timeline {entity_type, entity_id, body, kind?: "note"|"comment"} -> the new entry; kind defaults to "note"
```

Open (pinned by the implementing workstream, which updates this doc): how a comment differs from a note, and the `core_timeline_mentions` columns.

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

core_file_blobs(sha256 PK, byte_size, created_at, unreferenced_since, missing_at)
```

**Bytes live on the volume** at `/data/files/<sha[:2]>/<sha>`, never in the DB (`VACUUM INTO` and Litestream would copy every PDF nightly). Thumbnails live in the row.

### Publication (upload)

**Publication and sweep share the write lock, so they cannot interleave.**

1. Stream the upload to `/data/files/tmp/<uuid>`, enforcing the size cap (setting `files.max_bytes`, default 25 MB).
2. Hash (sha256) and `fsync`. This happens **outside** the lock.
3. Inside **one** `transaction()`:
   1. upsert `core_file_blobs` (clearing `unreferenced_since`);
   2. insert the `core_files` row;
   3. `rename` the tmp file into `/data/files/<sha[:2]>/<sha>` (a local disk op, allowed under the lock);
   4. `COMMIT`.
4. The same bytes uploaded to the same record (`UNIQUE(entity_type, entity_id, sha256)`) return **200** with the existing row.
5. When a blob's last `core_files` row is deleted, the files service sets `core_file_blobs.unreferenced_since` in the same transaction.

### Sweep (`core.files.sweep`, 03:30 install-local)

1. Inside **one** `transaction()`:
   1. select blobs whose `unreferenced_since` is older than **7 days** **and** whose sha256 appears in **no retained backup manifest**;
   2. re-check each is still unreferenced;
   3. delete their rows;
   4. unlink their files;
   5. `COMMIT`.
2. Outside the lock: remove tmp files older than **24 h**.
3. A blob is never deleted while any retained manifest lists it, so every retained backup set restores whole (`deploy.md`).

### Crash cases

| Crash | Outcome |
|---|---|
| Rollback after `rename` | A file without a row. The sweep treats it as an orphan after 24 h. |
| A row whose file is missing | The sweep sets `core_file_blobs.missing_at` and reports it. Never silently served. |

### Safe serving

1. Download requires `authorize(read)` on the parent record.
2. Served with `Content-Disposition: attachment` and `X-Content-Type-Options: nosniff`.
3. `mime_type` comes from an allow-list, a module constant; HTML and SVG are served as `application/octet-stream`.
4. Upload requires `authorize(write)` on the parent record.
5. `DELETE` requires `authorize(write)` on the parent record.

### API

```
GET  /api/core/files?entity_type=&entity_id=  -> [{id, filename, mime_type, byte_size, sha256, created_at, uploaded_by:{id,name}}]
POST /api/core/files  multipart fields entity_type, entity_id, file -> File
GET  /api/core/files/{id}/download   -> bytes, Content-Disposition: attachment
DELETE /api/core/files/{id}          -> 204
```

Open (pinned by the implementing workstream, which updates this doc): how a missing blob is reported beyond `missing_at`, the mime allow-list's contents, and how the sweep enumerates "a file without a row" (a directory walk under `/data/files`).

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

Open (pinned by the implementing workstream, which updates this doc): table columns and routes are not stated (shape to be pinned by W2).

## 4. Saved views

Source: CakeCRM `backend/saved_views/` (356 → ~320). `Json()` → `json.dumps`.

```sql
core_saved_views(surface, entity_type, name, version, payload JSON, owner_user_id, is_shared)
```

1. Views store filters, not rows, so there is no record authorization beyond ownership / `is_shared`.
2. `version` lets the client refuse a stale view (`SavedViewBar` stale-version refusal, Vitest).

Open (pinned by the implementing workstream, which updates this doc): routes and what `surface` names are not stated.

## 5. Reports registry

New (~250) + CakeCRM `crm/export.py` `_cell`.

```python
Report(key, label, app, params, run(params, user) -> (columns, rows), admin_only)
```

1. Apps register via `reports.py` (`REPORTS = [Report(...)]`).
2. `run` receives the user and **must apply `can_read`**.
3. An app's reports default to "user has one of the app's roles" before their own checks; `admin_only` restricts to admins.
4. `GET /api/core/reports/{key}?format=csv` streams CSV via `core.csv_export.stream_csv` (shape to be pinned by W2).
5. CakeCRM's `report_service.py` stays CRM-owned in `apps/crm/reports.py`.

Open (pinned by the implementing workstream, which updates this doc): the `params` schema format, the JSON (non-CSV) response shape, and a report-listing route are not stated.

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
-- VAPID keys live in core_settings
```

### `deliver_in`

```python
deliver_in(conn, title, message, user_id=None, entity=None, link=None)
```

1. Inserts one `core_notifications` row per recipient **in the caller's transaction**, so the in-app notification is **exactly-once**.
2. `user_id=None` expands to every **active human** user who may read `entity` (never the system principal). A broadcast is therefore one row per user, and read state is per user.
3. Inserts a delivery-intent row per external channel in `core_notification_deliveries`.

### The notification remembers its record

1. Listing and reading re-run `entities.authorize(read)` on `(entity_type, entity_id)` and hide rows that fail, setting `suppressed_at`.
2. `flush` re-checks the same before sending a queued delivery and drops it if access is gone.
3. **A message already delivered externally cannot be recalled.** The contract says so.
4. Merges repoint notifications on the source to the target, like reminders (`contacts.md`).

### External delivery (`core.notifications.flush`, every 30 s)

1. Sends, then records `sent_at`. A crash between the two re-sends: external channels are **at-least-once**.
2. The payload carries `notification_id`, so the service worker drops a duplicate push.
3. Failures bump `attempts` and record `last_error`.
4. CakeCRM's Telegram branch becomes a `register_channel` extension point.

Open (pinned by the implementing workstream, which updates this doc): `entity` is passed as one argument while the table has two columns; its type (a `(type, id)` tuple is implied) is not stated. The `status` values of `core_notification_deliveries`, the retry limit, the `register_channel` signature, and the notification routes (list, mark read) are not stated. What happens when both `user_id` and `entity` are given and the user cannot read the entity.

## 7. Reminders

Source: CakeCRM `backend/reminders/` (767 → ~700; `recurrence.py` unchanged).

```sql
core_reminders(owner_user_id, entity_type, entity_id, due_at, repeat, series_id, status, fired_at, …)
```

1. Port: `INTEGER[]` / `ANY()` → `json_each`; `SKIP LOCKED` → plain select inside `transaction()`; the `crm.service` / `gtd_common` imports are cut.
2. Job `core.reminders.fire_due` every 60 s marks `fired_at` **and** calls `deliver_in` **in the same transaction**.
3. At fire time the reminder re-checks `authorize(read)` for its owner and **voids itself** otherwise.
4. Merges repoint reminders (`contacts.md`).

Open (pinned by the implementing workstream, which updates this doc): `status` values (including the "void" state's name) and the series/repeat columns' format (lifted from CakeCRM) are not stated here. Reminder routes.

## 8. Change log

```sql
core_change_log(id, at, user_id, app, entity, entity_id, field, old, new, reason, request_id,
                deleted_at TEXT NULL)
```

1. `record_changes_in` writes one row per change, alongside the timeline `field_change` row.
2. `core.changelog.record_in` is a frozen Step 1 stub signature that W3 fills.
3. Rows written before a delete are kept: they keep `entity_id`, and the delete cascade sets their `deleted_at`, so history stays distinguishable from any later record.
4. The ChangeLog viewer and `/api/core/changelog` apply `authorize(read)` per row and hide the rest. Filters: app, user, entity (`frontend-shell.md`).
5. `user_id` may be the system principal (`id=0`) for unattended actions.

Open (pinned by the implementing workstream, which updates this doc): `record_in`'s signature, whether `field` holds one field per row or a set, and `/api/core/changelog`'s query and response shape (shape to be pinned by W3).

## 9. Frontend (`frontend/src/core/records/`)

~2,700 lifted + ~400 new. **Props take `entityType: string`.**

| Component | Source (CakeCRM `frontend/src/crm/…` unless noted) | Contract |
|---|---|---|
| `Timeline` | Merge of `components/NotesThread.tsx` (276) + `components/ActivityTimeline.tsx` (232) | Lists timeline rows for a record; used as `<Timeline entityType="crm.deal">`. |
| `NoteComposer` | `components/NoteComposer.tsx` (323) | Posts a note. |
| `MentionPicker` | `components/MentionPicker.tsx` (185) | @-mention users. |
| `Attachments` | `components/NoteAttachments.tsx` (137) and `chatterAttachments.ts` | Lists, uploads, downloads files. |
| `CustomFields` | `components/CustomFieldsSection.tsx` (165) + `CustomFieldInputs.tsx` (72) + `useCustomFieldsForm.ts` | One generic renderer for every field type. |
| `CustomFieldSettings` | `components/CustomFieldSettings.tsx` (215) | Field definitions per entity type. |
| `SavedViewBar` | `frontend/src/shared/collection/SavedViewsMenu.tsx` (396) + `savedViews.ts` | Refuses a stale-version view. |
| `ReportTable` | new | Renders `(columns, rows)`; CSV download. |
| `NotificationBell` | `components/NotificationsBell.tsx` | In-app notifications. |
| `ReminderPicker` | `components/ReminderForm.tsx` (205) | Set a reminder on a record. |
| `RemindersPage` | `RemindersPage.tsx` (206) | The user's reminders. |

Open (pinned by the implementing workstream, which updates this doc): every prop other than `entityType` (the record id prop's name and type, callbacks) is not stated. The donor files listed are the likely sources by name; the plan gives only the totals and the `NotesThread` + `ActivityTimeline` merge.

## Tests that pin this

- `record_changes_in` writes one timeline row + one change-log row and fires the hook after commit.
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
