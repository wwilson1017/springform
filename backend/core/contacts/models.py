"""Response models for `/api/core/contacts`: every column of the row, `tags` a list, `is_primary` a
bool. Person and organization rows keep their table's column order."""

from typing import Literal

from backend.core.platform.models import Out

OwnerType = Literal["person", "organization"]


class PersonRecord(Out):
    id: int
    name: str
    given_name: str | None
    family_name: str | None
    email: str | None  # mirrors the primary email channel
    phone: str | None  # mirrors the primary phone channel
    title: str | None
    source: str | None
    status: str | None
    tags: list[str]
    notes: str | None
    owner_user_id: int | None
    archived_at: str | None
    merged_into_id: int | None
    created_at: str
    updated_at: str


class PersonRow(PersonRecord):
    """A row of the people list."""

    primary_organization_id: int | None
    primary_organization_name: str | None


class OrganizationRecord(Out):
    id: int
    name: str
    domain: str | None
    website: str | None
    industry: str | None
    email: str | None
    phone: str | None
    notes: str | None
    source: str | None
    status: str | None
    tags: list[str]
    owner_user_id: int | None
    archived_at: str | None
    merged_into_id: int | None
    created_at: str
    updated_at: str


class Channel(Out):
    id: int
    owner_type: OwnerType
    owner_id: int
    kind: Literal["email", "phone", "url", "other"]
    value: str
    label: str | None
    is_primary: bool
    created_at: str
    updated_at: str


class Address(Out):
    id: int
    owner_type: OwnerType
    owner_id: int
    kind: str | None
    line1: str | None
    line2: str | None
    city: str | None
    region: str | None
    postal_code: str | None
    country: str | None
    is_primary: bool
    created_at: str
    updated_at: str


class OrganizationLink(Out):
    """One of a person's organizations, primary first."""

    organization_id: int
    name: str
    archived_at: str | None
    role: str
    is_primary: bool
    started_on: str | None
    ended_on: str | None


class PersonLink(Out):
    """One of an organization's people, by name."""

    person_id: int
    name: str
    email: str | None
    phone: str | None
    title: str | None
    archived_at: str | None
    role: str
    is_primary: bool
    started_on: str | None
    ended_on: str | None


class PersonDetail(PersonRecord):
    organizations: list[OrganizationLink]
    channels: list[Channel]
    addresses: list[Address]


class OrganizationDetail(OrganizationRecord):
    people: list[PersonLink]
    channels: list[Channel]
    addresses: list[Address]


class MergedAway(Out):
    """What reading a merged id answers: the survivor's id."""

    merged_into: int


class ContactLink(Out):
    """A person-organization link row."""

    id: int
    person_id: int
    organization_id: int
    role: str
    is_primary: bool
    started_on: str | None
    ended_on: str | None
    created_at: str


class PersonPage(Out):
    items: list[PersonRow]
    total: int
    page: int
    page_size: int


class OrganizationPage(Out):
    items: list[OrganizationRecord]
    total: int
    page: int
    page_size: int


class ContactSearchHit(Out):
    kind: OwnerType
    id: int
    name: str
    email: str | None
    phone: str | None
    url: str


class ContactLabel(Out):
    id: int
    label: str


class ContactDuplicates(Out):
    """Live records sharing an email, phone, name (people) or domain (organizations)."""

    match_on: Literal["email", "phone", "name", "domain"]
    value: str
    count: int
    records: list[ContactLabel]
