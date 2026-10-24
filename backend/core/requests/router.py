from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.core.auth.deps import User, current_user, require_admin
from backend.core.platform.models import Updated
from backend.core.requests import models, service

router = APIRouter(prefix="/api/core/requests", tags=["core"])


class RequestIn(BaseModel):
    title: str
    app: str = "core"
    description: str = ""


@router.post("", response_model=models.RequestRow)
def requests_create(body: RequestIn, user: User = Depends(current_user)) -> dict:
    return service.create(user, body.title, body.app, body.description)


@router.get("", response_model=list[models.RequestRow])
def requests_list(
    state: Literal["open", "closed", "all"] = "open",
    limit: int | None = None,
    offset: int | None = None,
    user: User = Depends(current_user),
) -> list[dict]:
    return service.list_requests(state, limit, offset)


@router.get("/config", response_model=models.RequestsConfig)
def requests_config(user: User = Depends(current_user)) -> dict:
    return service.config()


@router.post("/refresh", response_model=Updated)
def requests_refresh(user: User = Depends(require_admin)) -> dict:
    return {"updated": service.refresh()}
