from typing import Any, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict

from backend.core import entities
from backend.core.auth.deps import User, current_user
from backend.core.fields import models, service

router = APIRouter(prefix="/api/core/fields", tags=["core"])
FieldType = Literal["text", "number", "boolean", "date", "select", "multiselect", "url", "user"]


class DefinitionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_type: str
    label: str
    type: FieldType
    key: str | None = None
    options: list[str] | None = None
    required: bool = False
    position: int | None = None


class DefinitionPatch(BaseModel):
    """Only the fields sent change; null is refused except for options."""

    model_config = ConfigDict(extra="forbid")
    label: str = ""
    options: list[str] | None = None
    required: bool = False
    position: int = 0
    archived: bool = False


class ValuesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_type: str
    entity_id: int
    values: dict[str, Any]


@router.get("/entity-types", response_model=list[models.FieldEntityType])
def list_field_entity_types(user: User = Depends(current_user)) -> list[dict]:
    """Every registered entity type, for the admin's field-definition picker."""
    return [{"type": e.type, "label": e.label, "label_plural": e.label_plural} for e in entities.all_entities()]


@router.get("/definitions", response_model=list[models.FieldDefinition])
def list_field_definitions(entity_type: str, include_archived: bool = False, user: User = Depends(current_user)) -> list[dict]:
    return service.list_definitions(entity_type, include_archived)


@router.post("/definitions", response_model=models.FieldDefinition)
def create_field_definition(body: DefinitionIn, user: User = Depends(current_user)) -> dict:
    return service.create_definition(user, body.model_dump())


@router.patch("/definitions/{definition_id}", response_model=models.FieldDefinition)
def update_field_definition(definition_id: int, body: DefinitionPatch, user: User = Depends(current_user)) -> dict:
    return service.update_definition(user, definition_id, body.model_dump(exclude_unset=True))


@router.delete("/definitions/{definition_id}", status_code=204)
def archive_field_definition(definition_id: int, user: User = Depends(current_user)) -> Response:
    service.archive_definition(user, definition_id)
    return Response(status_code=204)


@router.get("/values")
def get_field_values(entity_type: str, entity_id: int, user: User = Depends(current_user)) -> dict[str, Any]:
    return service.values_for(user, entity_type, entity_id)


@router.put("/values")
def set_field_values(body: ValuesIn, user: User = Depends(current_user)) -> dict[str, Any]:
    return service.set_values(user, body.entity_type, body.entity_id, body.values)
