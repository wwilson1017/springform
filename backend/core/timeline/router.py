from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.core.auth.deps import User, current_user
from backend.core.timeline import service

router = APIRouter(prefix="/api/core/timeline", tags=["core"])


class NoteIn(BaseModel):
    entity_type: str
    entity_id: int
    body: str


@router.get("")
def list_timeline(
    entity_type: str, entity_id: int, limit: int | None = None, offset: int | None = None,
    user: User = Depends(current_user),
) -> list[dict]:
    return service.list_for(user, entity_type, entity_id, limit, offset)


@router.post("")
def add_note(body: NoteIn, user: User = Depends(current_user)) -> dict:
    return service.add_note(user, body.entity_type, body.entity_id, body.body)
