from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from backend.core.auth.deps import User, current_user
from backend.core.timeline import service

router = APIRouter(prefix="/api/core/timeline", tags=["core"])


class NoteIn(BaseModel):
    entity_type: str
    entity_id: int
    body: str
    kind: Literal["note", "comment"] = "note"


@router.get("")
def list_timeline(
    entity_type: str, entity_id: int, before: int | None = None, limit: int = Query(50, ge=1, le=200),
    user: User = Depends(current_user),
) -> list[dict]:
    """Newest first; pass the last id seen as `before` for the next page."""
    return service.list_for(user, entity_type, entity_id, before, limit)


@router.post("")
def add_note(body: NoteIn, user: User = Depends(current_user)) -> dict:
    return service.add_note(user, body.entity_type, body.entity_id, body.body, body.kind)
