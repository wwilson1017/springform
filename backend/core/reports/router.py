from fastapi import APIRouter, Depends, Request

from backend.core.auth.deps import User, current_user
from backend.core.reports import models, service

router = APIRouter(prefix="/api/core/reports", tags=["core"])


@router.get("", response_model=list[models.ReportInfo])
def list_reports(user: User = Depends(current_user)) -> list[dict]:
    return service.list_for(user)


@router.get("/{key}", response_model=models.ReportResult)
def run_report(key: str, request: Request, user: User = Depends(current_user)) -> dict:
    """Params are the query string. # simplification: one value per param; a repeated param
    keeps its last value. Upgrade: an `array` param type read with getlist."""
    return service.run(user, key, dict(request.query_params))
