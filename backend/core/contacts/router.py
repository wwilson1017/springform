"""Contacts routes under `/api/core/contacts`. Every route needs a signed-in user, and the
service authorizes each record through `entities.authorize`. Record shapes: `api.py`.

People and organizations get the same routes (built by `_record_routes`); so do channels and
addresses (`_part_routes`). Not `from __future__ import annotations`: the route factories bind
their body models by closure, which FastAPI must see as real classes.
"""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from backend.core.auth.deps import User, current_user
from backend.core.contacts import models, service
from backend.core.platform.models import Ok, Out

router = APIRouter(prefix="/api/core/contacts", tags=["core"], dependencies=[Depends(current_user)])

OwnerType = Literal["person", "organization"]
ChannelKind = Literal["email", "phone", "url", "other"]


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _Common(Body):
    """Fields both kinds share; PATCH changes only the fields sent (null clears)."""

    name: str | None = None
    email: str | None = None
    phone: str | None = None
    source: str | None = None
    status: str | None = None
    tags: list[str] | None = None
    notes: str | None = None
    owner_user_id: int | None = None


class PersonFields(_Common):
    given_name: str | None = None
    family_name: str | None = None
    title: str | None = None


class OrganizationFields(_Common):
    domain: str | None = None
    website: str | None = None
    industry: str | None = None


class MergeIn(Body):
    target_id: int
    source_id: int


class LinkKey(Body):
    person_id: int
    organization_id: int
    role: str = ""


class LinkIn(LinkKey):
    is_primary: bool = False
    started_on: date | None = None
    ended_on: date | None = None


class LinkPatch(LinkKey):
    new_role: str | None = None
    is_primary: bool | None = None
    started_on: date | None = None
    ended_on: date | None = None


class ChannelPatch(Body):
    kind: ChannelKind | None = None
    value: str | None = None
    label: str | None = None
    is_primary: bool | None = None


class ChannelIn(Body):
    owner_type: OwnerType
    owner_id: int
    kind: ChannelKind
    value: str
    label: str | None = None
    is_primary: bool = False


class AddressPatch(Body):
    kind: str | None = None
    line1: str | None = None
    line2: str | None = None
    city: str | None = None
    region: str | None = None
    postal_code: str | None = None
    country: str | None = None
    is_primary: bool | None = None


class AddressIn(AddressPatch):
    owner_type: OwnerType
    owner_id: int


@router.get("/search", response_model=list[models.ContactSearchHit])
def search(q: str, kind: OwnerType | None = None, limit: int = 20, user: User = Depends(current_user)) -> list[dict]:
    """[{kind, id, name, email, phone, url}], best match first; live records only."""
    return service.search(user, q, kind, limit)


@router.get("/people", response_model=models.PersonPage)
def list_people(
    q: str | None = None, archived: bool = False, organization_id: int | None = None, tag: str | None = None,
    page: int = 1, page_size: int | None = None, user: User = Depends(current_user),
) -> dict:
    """{items: [person + primary_organization_id, primary_organization_name], total, page, page_size}"""
    return service.list_records(
        user, "person", q=q, archived=archived, organization_id=organization_id, tag=tag, page=page, page_size=page_size
    )


@router.get("/organizations", response_model=models.OrganizationPage)
def list_organizations(
    q: str | None = None, archived: bool = False, tag: str | None = None, page: int = 1, page_size: int | None = None,
    user: User = Depends(current_user),
) -> dict:
    """{items: [organization], total, page, page_size}"""
    return service.list_records(user, "organization", q=q, archived=archived, tag=tag, page=page, page_size=page_size)


def _record_routes(kind: str, path: str, fields_model: type[Body], detail: type[Out]) -> None:
    @router.get(f"/{path}/duplicates", name=f"{path}_duplicates", response_model=list[models.ContactDuplicates])
    def duplicates(user: User = Depends(current_user)) -> list[dict]:
        return service.find_duplicates(user, kind)

    @router.post(f"/{path}/merge", name=f"merge_{path}", response_model=detail)
    def merge(body: MergeIn, user: User = Depends(current_user)) -> dict:
        return service.merge(kind, body.target_id, body.source_id, user)

    @router.post(f"/{path}", name=f"create_{kind}", response_model=detail)
    def create(body: fields_model, user: User = Depends(current_user)) -> dict:
        return service.create(user, kind, body.model_dump(exclude_unset=True))

    @router.get(f"/{path}/{{record_id}}", name=f"get_{kind}", response_model=detail | models.MergedAway)
    def get(record_id: int, user: User = Depends(current_user)) -> dict:
        return service.get(user, kind, record_id)

    @router.patch(f"/{path}/{{record_id}}", name=f"update_{kind}", response_model=detail)
    def update(record_id: int, body: fields_model, user: User = Depends(current_user)) -> dict:
        return service.update(user, kind, record_id, body.model_dump(exclude_unset=True))

    @router.delete(f"/{path}/{{record_id}}", name=f"archive_{kind}", response_model=detail)
    def archive(record_id: int, user: User = Depends(current_user)) -> dict:
        return service.archive(user, kind, record_id)

    @router.post(f"/{path}/{{record_id}}/restore", name=f"restore_{kind}", response_model=detail)
    def restore(record_id: int, user: User = Depends(current_user)) -> dict:
        return service.restore(user, kind, record_id)


def _part_routes(part: str, path: str, in_model: type[Body], patch_model: type[Body], out: type[Out]) -> None:
    @router.post(f"/{path}", name=f"add_{part}", response_model=out)
    def add(body: in_model, user: User = Depends(current_user)) -> dict:
        fields = body.model_dump(exclude_unset=True, exclude={"owner_type", "owner_id"})
        return service.add_part(user, part, body.owner_type, body.owner_id, **fields)

    @router.patch(f"/{path}/{{part_id}}", name=f"update_{part}", response_model=out)
    def update(part_id: int, body: patch_model, user: User = Depends(current_user)) -> dict:
        return service.update_part(user, part, part_id, **body.model_dump(exclude_unset=True))

    @router.delete(f"/{path}/{{part_id}}", name=f"delete_{part}", response_model=Ok)
    def delete(part_id: int, user: User = Depends(current_user)) -> dict:
        service.delete_part(user, part, part_id)
        return {"ok": True}


_record_routes("person", "people", PersonFields, models.PersonDetail)
_record_routes("organization", "organizations", OrganizationFields, models.OrganizationDetail)
_part_routes("channel", "channels", ChannelIn, ChannelPatch, models.Channel)
_part_routes("address", "addresses", AddressIn, AddressPatch, models.Address)


@router.post("/links", response_model=models.ContactLink)
def create_link(body: LinkIn, user: User = Depends(current_user)) -> dict:
    return service.link(user, **body.model_dump())


@router.patch("/links", response_model=models.ContactLink)
def update_link(body: LinkPatch, user: User = Depends(current_user)) -> dict:
    fields = body.model_dump(exclude_unset=True, exclude={"person_id", "organization_id", "role"})
    return service.update_link(user, body.person_id, body.organization_id, body.role, **fields)


@router.delete("/links", response_model=Ok)
def delete_link(body: LinkKey, user: User = Depends(current_user)) -> dict:
    service.unlink(user, body.person_id, body.organization_id, body.role)
    return {"ok": True}
