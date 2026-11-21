"""Admin routes for Settings, GTD suite, under /api/core/gtd. Each answers with the card's whole state."""

from fastapi import APIRouter, Depends

from backend.core.auth.deps import require_admin
from backend.core.gtd import models, service

router = APIRouter(prefix="/api/core/gtd", tags=["core"], dependencies=[Depends(require_admin)])


@router.get("", response_model=models.GtdState)
def gtd_state() -> dict:
    return service.view()


@router.post("/connect", response_model=models.GtdState)
def gtd_connect() -> dict:
    """Ask the suite for a code; a connect already waiting is returned as is (no second code)."""
    return service.start()


@router.post("/connect/poll", response_model=models.GtdState)
def gtd_connect_poll() -> dict:
    """Ask the suite once whether the code was approved (no faster than its interval); on approval,
    store the server and its tiles. 409 `gtd_connect_expired` when the code is gone."""
    return service.poll()


@router.delete("", response_model=models.GtdState)
def gtd_disconnect() -> dict:
    """Remove the GTD server (its tiles and tools go with it), or cancel a connect waiting for approval."""
    return service.disconnect()
