# Contacts directory

**What this covers:** §3: the core people and organizations tables, the primary-channel sync rule, merge rules in full, the published `contacts.api`, routes, `can_read` / `can_write`, and the frontend components.
**Who reads it:** W2 (contacts backend), W11 (contacts frontend), the CRM port (W10/W13), any app that points at people or organizations.

Code: `backend/core/contacts/{service.py, api.py, router.py}`, `frontend/src/core/contacts/`.

The directory is core so every app points at the same people. People and organizations are many-to-many with a role.

## 1. Tables

Migration: the core init migration, `20261020000100_core_init.sql`. There is no separate contacts migration.

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
  …
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

core_contacts_fts   -- FTS5, tokenize = unicode61, over both people and organizations, maintained by triggers
```

Open: the `…` columns of `core_people` (timestamps), the enum values of `source` and `status`, and the FTS column list are not stated. Open: whether `core_addresses` and `core_contact_channels` have their own primary-uniqueness index per owner (the plan states one only for links).

## 2. Primary-channel sync

1. `core_people.email` and `core_people.phone` mirror the primary channel in `core_contact_channels`.
2. They are rewritten by the service **in the same transaction** whenever channels change.
3. There is **one writer path**: `contacts.service._sync_primary(conn, owner)`. Nothing else writes those columns.

Open: whether `core_organizations.email` / `phone` are mirrored the same way (`_sync_primary` takes an `owner`, and channels have `owner_type`, but the plan states the mirror only for people).

## 3. Merge

`merge_people_in(conn, target_id, source_id, actor)` and the organization twin.

**Preconditions**

1. Both ids are first resolved to their chain heads: `resolve(id)` follows `merged_into_id` with a cycle guard.
2. Self-merge is refused.
3. Merging into an archived record is refused.
4. The survivor is the **target**.

**Per-table rules**

| Data | Rule |
|---|---|
| Person–organization links | The source's primary flag is cleared **before** rows move (so the partial unique index is never violated mid-transaction). On a `UNIQUE(person, org, role)` collision the target's row is kept and the source's dropped. |
| Addresses, channels | Moved to the target; source primaries demoted. |
| Files | Repointed; on an `(entity, sha256)` collision the source row is dropped (same bytes). |
| Custom field values | The target's non-empty value wins, else the source's. |
| Timeline rows | Repointed, keeping their original author and time, plus one `system` row on the survivor: "merged #<source> into this record". |
| Reminders | Repointed. |
| App data | Through `on_entity_merged_in` subscribers in the same transaction. Example: the CRM's subscriber repoints deals and keeps the higher `crm_person_scores` score. |

**After the move**

1. The source gets `merged_into_id = target` and `archived_at`.
2. **Every older alias that pointed at the source is re-pointed at the target.** Aliases are kept flat, so a read of any merged id resolves in one hop.
3. Reads of a merged id return `{"merged_into": head}`.
4. A failing subscriber rolls the whole merge back.

Open: the HTTP status of a read that returns `{"merged_into": head}` is not stated. Open: whether a merge writes a `core_change_log` row, and how notifications that point at the source are handled, are not stated.

## 4. Published `contacts.api`

Each function has an `_in(conn, …)` form.

| Function | Purpose |
|---|---|
| `get` | One person or organization. |
| `search` | Search via `core_contacts_fts`. |
| `create` | Create a person or organization. |
| `update` | Update fields (channels through `_sync_primary`). |
| `link` / `unlink` | Person ↔ organization with a role. |
| `organizations_for` | Organizations of a person. |
| `people_for` | People of an organization. |
| `resolve_or_create_organizations` | Match organizations by name, creating the missing ones. |
| `merge` | `merge_people_in` / organization twin. |
| `find_duplicates` | Lifted from CakeCRM `analytics_service.py:234-330`. |

`resolve(id)` (follows `merged_into_id` to the chain head) is a service function the merge uses; the plan does not list it among the published functions.

Open: full signatures (person vs organization variants, argument names) are not stated (to be pinned by W2).

## 5. Routes

`/api/core/contacts/{people,organizations,links,addresses,channels}` (shape to be pinned by W2). Every route authorizes through `entities.authorize`.

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

Open: core page paths (`/people`, `/organizations`, …) are not stated.

## Tests that pin this

- Person ↔ two organizations with roles, primary uniqueness.
- Merge with every collision rule; merge repoints a deal and keeps score.
- A core merge that invokes a failing CRM subscriber leaves no partial change.
- Unicode search fixture.
- Playwright: create org → person → link with role → deal → note with @mention → attachment; example record panel on a person.

## Source

Build plan: §3 (all), §4 (merge interactions with timeline, files, fields, reminders), §7 (CRM table mapping), SQLite rules (identifiers, FTS5), Step 1, Verification.
