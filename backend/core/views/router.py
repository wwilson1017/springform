from typing import Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, StrictInt

from backend.core.auth.deps import User, current_user
from backend.core.views import models, service

router = APIRouter(prefix="/api/core/views", tags=["core"])


class ViewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    surface: str
    name: str
    payload: dict[str, Any]
    entity_type: str | None = None


class ViewPatch(BaseModel):
    """`version` is the version the edit is based on. Only the other fields sent change."""

    model_config = ConfigDict(extra="forbid")
    version: StrictInt  # strict: true/"1" must not pass for an equality token
    name: str = ""
    payload: dict[str, Any] = {}
    entity_type: str | None = None


class ShareIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_shared: bool | None = None


@router.get("", response_model=list[models.SavedView])
def list_saved_views(surface: str, user: User = Depends(current_user)) -> list[dict]:
    return service.list_views(user, surface)


@router.post("", response_model=models.SavedView)
def create_saved_view(body: ViewIn, user: User = Depends(current_user)) -> dict:
    return service.create_view(user, body.surface, body.name, body.payload, body.entity_type)


@router.patch("/{view_id}", response_model=models.SavedView)
def update_saved_view(view_id: int, body: ViewPatch, user: User = Depends(current_user)) -> dict:
    changes = body.model_dump(exclude_unset=True)
    return service.update_view(user, view_id, changes.pop("version"), changes)


@router.delete("/{view_id}", status_code=204)
def delete_saved_view(view_id: int, user: User = Depends(current_user)) -> Response:
    service.delete_view(user, view_id)
    return Response(status_code=204)


@router.post("/{view_id}/share", response_model=models.SavedView)
def share_saved_view(view_id: int, body: ShareIn | None = None, user: User = Depends(current_user)) -> dict:
    return service.share_view(user, view_id, body.is_shared if body else None)
