# Contacts directory

**What this covers:** §3: the core people and organizations tables, the primary-channel sync rule, merge rules in full, the published `contacts.api`, routes, `can_read` / `can_write`, and the frontend components.
**Who reads it:** W2 (contacts backend), W11 (contacts frontend), the CRM port (W10/W13), any app that points at people or organizations.

Code: `backend/core/contacts/{service.py, api.py, router.py, seed.py, startup.py}` (`seed.py` and `startup.py` add sample contacts once in `PREVIEW_MODE`), `frontend/src/core/contacts/`.

The directory is core so every app points at the same people. People and organizations are many-to-many with a role.

## 1. Tables

Migrations: the tables are in the core init migration, `20261020000100_core_init.sql`. `20261020000300_core_contacts.sql` adds two partial unique indexes: one primary channel per (owner, kind), and one primary address per owner.

```sql
core_people(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name,                 -- one display field, so lifted CRM UI keeps reading .name
  given_name, family_name,
  email, phone,         -- mirror the primary channel; written only by _sync_primary
  title, source, status,
  tags,                 -- JSON
  notes, owner_user_id,
  archived_at, merged_into_id,
  created_at, updated_at
)

core_organizations(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name, domain, website, industry, email, phone, notes,
  source, status, tags, owner_user_id, archived_at, merged_into_id
)
-- UNIQUE lower(trim(name)) WHERE merged_into_id IS NULL

core_person_organizations(person_id, organization_id, role, is_primary, started_on, ended_on)
-- UNIQUE(person_id, organization_id, role)
-- partial UNIQUE (person_id) WHERE is_primary = 1

core_addresses(owner_type CHECK (owner_type IN ('person','organization')), owner_id,
               kind, line1, line2, city, region, postal_code, country, is_primary)

core_contact_channels(owner_type, owner_id,
                      kind CHECK (kind IN ('email','phone','url','other')),
                      value, label, is_primary)

core_contacts_fts(owner_type UNINDEXED, owner_id UNINDEXED, name, email, phone, body)
  -- FTS5, tokenize = 'unicode61 remove_diacritics 2', maintained by triggers;
  -- rowid 2*id for a person, 2*id+1 for an organization
```

`source` and `status` are free text.

## 2. Primary-channel sync

1. `email` and `phone` on a person or an organization mirror its primary email and phone channel in `core_contact_channels`.
2. They are rewritten by the service **in the same transaction** whenever channels change.
3. There is **one writer path**: `contacts.service._sync_primary(conn, owner_type, owner_id)`. Nothing else writes those columns.

## 3. Merge

The service forms are `contacts.service.merge_people_in(conn, target_id, source_id, actor)` and `merge_organizations_in`. The published `contacts.api` forms put the user first: `merge_people_in(conn, user, target_id, source_id)` and `merge_organizations_in(conn, user, target_id, source_id)`.

**Preconditions**

1. Both ids are first resolved to their chain heads: `resolve(id)` follows `merged_into_id` with a cycle guard.
2. Self-merge is refused (422).
3. Merging into an archived record is refused (409).
4. The actor needs write access to both records.
5. The survivor is the **target**.

**Per-table rules**

| Data | Rule |
|---|---|
| Person–organization links | The source's primary flags are cleared **before** rows move, so the partial unique index is never violated mid-transaction. On a `UNIQUE(person, org, role)` collision the target's row is kept and the source's dropped. A cleared primary comes back on the moved or kept row only when that person has no other primary. |
| Addresses, channels | Moved to the target. A source channel equal to one of the target's (same kind and value, ignoring case) is dropped. A source primary is demoted where the target already has a primary for that slot (per kind for channels, one per owner for addresses); otherwise it stays primary on the target. |
| Files | Repointed; on an `(entity, sha256)` collision the source row is dropped (same bytes). |
| Custom field values | The target's non-empty value wins, else the source's. |
| Timeline rows | Repointed, keeping their original author and time, plus one `system` row on the survivor: "merged #<source> into this record". |
| Reminders | Repointed. |
| Notifications | Repointed, like reminders. |
| App data | Through `on_entity_merged` subscribers (dispatched by `on_entity_merged_in`) in the same transaction. Example: the CRM's subscriber repoints deals and keeps the higher `crm_person_scores` score. |

**After the move**

1. The source gets `merged_into_id = target` and `archived_at`.
2. **Every older alias that pointed at the source is re-pointed at the target.** Aliases are kept flat, so a read of any merged id resolves in one hop.
3. Reads of a merged id return **200** `{"merged_into": head}`.
4. The merge writes one `core_change_log` row, on the survivor: `field` is `merged_from` and `new` is the source id.
5. A failing subscriber rolls the whole merge back.

## 4. Published `contacts.api`

Each function has an `_in(conn, …)` form.

| Function | Purpose |
|---|---|
| `get_person`, `get_organization` | One record, or `{"merged_into": head}` for a merged id. |
| `search` | Search via `core_contacts_fts`. |
| `create_person`, `create_organization` | Create a record. |
| `update_person`, `update_organization` | Update fields (channels through `_sync_primary`). |
| `link` / `unlink` | Person ↔ organization with a role. |
| `organizations_for` | Organizations of a person. |
| `people_for` | People of an organization. |
| `resolve_or_create_organizations` | Match organizations by name, creating the missing ones. |
| `merge_people`, `merge_organizations` | §3; the `_in` forms take `(conn, user, target_id, source_id)`. |
| `find_duplicates` | Lifted from CakeCRM `analytics_service.py:234-330`. |
| `resolve` | Follows `merged_into_id` to the chain head. |

Open (pinned by the implementing workstream, which updates this doc): the full argument lists of the remaining functions (see `backend/core/contacts/api.py`).

## 5. Routes

All under `/api/core/contacts`, behind `current_user`:

```
GET    /search?q=&kind=&limit=                      [{kind, id, name, email, phone, url}], best match first
GET    /people, /organizations                      lists
POST   /people, /organizations                      create
GET    /people/{id}, /organizations/{id}            detail, or {"merged_into": head}
PATCH  /people/{id}, /organizations/{id}            update
DELETE /people/{id}, /organizations/{id}            archive
POST   /people/{id}/restore, /organizations/{id}/restore
GET    /people/duplicates, /organizations/duplicates
POST   /people/merge, /organizations/merge
POST   /channels, /addresses; PATCH / DELETE /channels/{part_id}, /addresses/{part_id}
POST / PATCH / DELETE /links                        keyed by the body
```

Routes on one record call `entities.authorize`. Create, list, search and duplicates touch no single record, so they ask the entity's `can_read` / `can_write` rule directly.

## 6. Authorization

| Entity | `can_read` | `can_write` |
|---|---|---|
| `core.person` | Any active member. | Any active member. |
| `core.organization` | Any active member. | Any active member. |

The system principal reads them from jobs only (`authorization.md` §7).

## 7. Service source

Lifted from CakeCRM `backend/crm/service.py:315-1031` (~650 lines) plus `backend/crm/analytics_service.py:234-330` (`find_duplicates`). The CRM's own `contacts` table becomes `core_people` (+ `crm_person_scores`), `companies` becomes `core_organizations`.

## 8. Frontend (`frontend/src/core/contacts/`)

| Piece | Source | Contract |
|---|---|---|
| `ContactPicker` | CakeCRM `crm/components/RecordCombobox.tsx` (458, already generic) + `crm/dealLinkPickers.ts` | Picks a person or organization. |
| People list + detail | CakeCRM `crm/ContactsPage.tsx`, `crm/ContactDetailPage.tsx` | Detail renders every app's `recordPanels["core.person"]`. |
| Organizations list + detail | CakeCRM `crm/CompaniesPage.tsx`, `crm/CompanyDetailPage.tsx` | Detail renders every app's `recordPanels["core.organization"]`. |
| Forms | CakeCRM `crm/components/ContactForm.tsx`, `CompanyForm.tsx` | |

The four pages and forms are ~1,350 lifted lines. Detail pages also host the core record components (`records.md`).

Pages: `/people`, `/people/:id`, `/organizations`, `/organizations/:id` (`frontend-shell.md` §3).

## Tests that pin this

- Person ↔ two organizations with roles, primary uniqueness.
- Merge with every collision rule; merge repoints a deal and keeps score.
- A core merge that invokes a failing CRM subscriber leaves no partial change.
- Unicode search fixture.
- Playwright: create org → person → link with role → deal → note with @mention → attachment; example record panel on a person.

## Source

Build plan: §3 (all), §4 (merge interactions with timeline, files, fields, reminders), §7 (CRM table mapping), SQLite rules (identifiers, FTS5), Step 1, Verification.
