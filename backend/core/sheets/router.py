from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.core.auth.deps import User, require_admin
from backend.core.sheets import models, service

router = APIRouter(prefix="/api/core/sheets", tags=["core"], dependencies=[Depends(require_admin)])


class CredentialsIn(BaseModel):
    service_account_json: str = Field(max_length=20_000)


class SheetPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spreadsheet_id: str | None = Field(None, max_length=500)
    range: str | None = Field(None, max_length=200)
    enabled: bool | None = None
    schedule: Literal["hourly", "daily", "manual"] | None = None


@router.get("/credentials", response_model=models.SheetCredentials)
def get_sheets_credentials() -> dict:
    return service.credentials_status()


@router.put("/credentials", response_model=models.SheetCredentials)
def put_sheets_credentials(body: CredentialsIn, user: User = Depends(require_admin)) -> dict:
    return service.set_credentials(body.service_account_json, user.id)


@router.get("", response_model=list[models.ConnectedSheet])
def list_sheets() -> list[dict]:
    return service.list_sheets()


@router.patch("/{sheet_id}", response_model=models.ConnectedSheet)
def update_sheet(sheet_id: int, body: SheetPatch) -> dict:
    return service.update_sheet(sheet_id, body.model_dump(exclude_none=True))


@router.post("/{sheet_id}/refresh", response_model=models.ConnectedSheet)
def refresh_sheet(sheet_id: int):
    try:
        return service.refresh(sheet_id, manual=True)
    except service.Throttled as e:
        return JSONResponse(
            {"detail": "throttled", "retry_after": e.retry_after}, status_code=429,
            headers={"Retry-After": str(e.retry_after)},
        )


@router.get("/{sheet_id}/preview", response_model=models.SheetPreview)
def preview_sheet(sheet_id: int) -> dict:
    return service.preview(sheet_id)
