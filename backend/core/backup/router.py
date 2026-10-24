"""The Backups page API (admin only)."""

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from backend.core.auth.deps import User, require_admin
from backend.core.backup import service
from backend.core.errors import Conflict, NotFound

router = APIRouter(prefix="/api/core/backups", tags=["core"], dependencies=[Depends(require_admin)])


@router.get("")
def list_backups() -> dict:
    return service.overview()


@router.post("/run", status_code=202)
def run_backup() -> dict:
    # Runs in this request's worker thread; service.run's guard is shared with the nightly job.
    result = service.run("manual")
    if result is None:
        raise Conflict("backup_in_progress")
    return result


@router.post("/key")
def show_key(user: User = Depends(require_admin)) -> dict:
    return service.reveal_key(user.id)


@router.get("/{stamp}/download")
def download_backup(stamp: str) -> FileResponse:
    path = service.snapshot_path(stamp)
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


@router.get("/{stamp}/manifest")
def get_manifest(stamp: str) -> dict:
    manifest = service.read_manifest(stamp)
    if manifest is None:
        raise NotFound("backup_not_found")
    return manifest
