from fastapi import APIRouter, Depends, Request

from backend.core.auth.deps import User, current_user
from backend.core.reports import service

router = APIRouter(prefix="/api/core/reports", tags=["core"])


@router.get("")
def list_reports(user: User = Depends(current_user)) -> list[dict]:
    return service.list_for(user)


@router.get("/{key}")
def run_report(key: str, request: Request, user: User = Depends(current_user)) -> dict:
    """Params are the query string. # simplification: one value per param; a repeated param
    keeps its last value. Upgrade: an `array` param type read with getlist."""
    return service.run(user, key, dict(request.query_params))
