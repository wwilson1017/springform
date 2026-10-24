"""The published contacts API: what apps and other core packages import
(`from backend.core.contacts import api as contacts`).

Every function has an `_in(conn, ...)` form for callers already in a transaction; `fn(...)`
runs it in its own transaction (writes) or on this thread's connection (reads). `user` is the
acting `User`, and every call authorizes through `entities.authorize`. Errors come from
`backend.core.errors`: NotFound (404), Forbidden (403), Invalid (422), Conflict (409; also any
write to a merged id).

Record shapes (all columns of the row; `tags` a list):
- person: {id, name, given_name, family_name, email, phone, title, source, status, tags, notes,
  owner_user_id, archived_at, merged_into_id, created_at, updated_at}
  + detail: organizations [{organization_id, name, archived_at, role, is_primary, started_on, ended_on}]
- organization: {id, name, domain, website, industry, email, phone, notes, source, status, tags,
  owner_user_id, archived_at, merged_into_id, created_at, updated_at}
  + detail: people [{person_id, name, email, phone, title, archived_at, role, is_primary, started_on, ended_on}]
- both details: addresses [{id, owner_type, owner_id, kind, line1, line2, city, region,
  postal_code, country, is_primary, created_at, updated_at}],
  channels [{id, owner_type, owner_id, kind, value, label, is_primary, created_at, updated_at}]
`email`/`phone` mirror the primary email/phone channel; passing them to create/update writes
that channel.
"""

from backend.core.contacts import service
from backend.core.contacts.service import (
    find_duplicates_in,
    link_in,
    organizations_for_in,
    people_for_in,
    reads,
    resolve_in,
    resolve_or_create_organizations_in,
    search_in,
    unlink_in,
    writes,
)


def get_person_in(conn, user, person_id: int) -> dict:
    """The person's detail, or {"merged_into": head} when the id was merged away."""
    return service.get_in(conn, user, "person", person_id)


def get_organization_in(conn, user, organization_id: int) -> dict:
    """The organization's detail, or {"merged_into": head} when the id was merged away."""
    return service.get_in(conn, user, "organization", organization_id)


def create_person_in(conn, user, **fields) -> dict:
    """Fields: name (or given_name/family_name), given_name, family_name, email, phone, title,
    source, status, tags, notes, owner_user_id. Returns the detail."""
    return service.create_in(conn, user, "person", fields)


def create_organization_in(conn, user, **fields) -> dict:
    """Fields: name (unique, case-insensitive), domain, website, industry, email, phone, source,
    status, tags, notes, owner_user_id. Returns the detail."""
    return service.create_in(conn, user, "organization", fields)


def update_person_in(conn, user, person_id: int, **fields) -> dict:
    return service.update_in(conn, user, "person", person_id, fields)


def update_organization_in(conn, user, organization_id: int, **fields) -> dict:
    return service.update_in(conn, user, "organization", organization_id, fields)


def merge_people_in(conn, user, target_id: int, source_id: int) -> dict:
    """Fold source into target (the survivor); returns the survivor's detail."""
    return service.merge_in(conn, "person", target_id, source_id, user)


def merge_organizations_in(conn, user, target_id: int, source_id: int) -> dict:
    return service.merge_in(conn, "organization", target_id, source_id, user)


get_person = reads(get_person_in)
get_organization = reads(get_organization_in)
search = reads(search_in)
organizations_for = reads(organizations_for_in)
people_for = reads(people_for_in)
find_duplicates = reads(find_duplicates_in)
resolve = reads(resolve_in)
create_person = writes(create_person_in)
create_organization = writes(create_organization_in)
update_person = writes(update_person_in)
update_organization = writes(update_organization_in)
link = writes(link_in)
unlink = writes(unlink_in)
resolve_or_create_organizations = writes(resolve_or_create_organizations_in)
merge_people = writes(merge_people_in)
merge_organizations = writes(merge_organizations_in)

__all__ = [
    "create_organization", "create_organization_in", "create_person", "create_person_in", "find_duplicates",
    "find_duplicates_in", "get_organization", "get_organization_in", "get_person", "get_person_in", "link",
    "link_in", "merge_organizations", "merge_organizations_in", "merge_people", "merge_people_in",
    "organizations_for", "organizations_for_in", "people_for", "people_for_in", "resolve", "resolve_in",
    "resolve_or_create_organizations", "resolve_or_create_organizations_in", "search", "search_in", "unlink",
    "unlink_in", "update_organization", "update_organization_in", "update_person", "update_person_in",
]  # fmt: skip
