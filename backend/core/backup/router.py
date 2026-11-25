"""The Backups page API (admin only)."""

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from backend.core.auth.deps import User, require_admin
from backend.core.backup import models, offsite, service
from backend.core.errors import Conflict, NotFound
from backend.core.platform.models import Ok

router = APIRouter(prefix="/api/core/backups", tags=["core"], dependencies=[Depends(require_admin)])


@router.get("", response_model=models.BackupsOverview)
def list_backups() -> dict:
    return {**service.overview(), "offsite": offsite.status()}


@router.post(
    "/run",
    status_code=202,
    response_model=models.BackupRun | models.BackupRunUnrecorded,
    response_model_exclude_unset=True,
)
def run_backup() -> dict:
    # Runs in this request's worker thread; service.run's guard is shared with the nightly job.
    result = service.run("manual")
    if result is None:
        raise Conflict("backup_in_progress")
    return result


@router.post("/key", response_model=models.KeyReveal, response_model_exclude_unset=True)
def show_key(user: User = Depends(require_admin)) -> dict:
    return service.reveal_key(user.id)


@router.put("/destination", response_model=models.Offsite)
def save_destination(body: models.DestinationIn, user: User = Depends(require_admin)) -> dict:
    return offsite.save_destination(user.id, **body.model_dump())


@router.delete("/destination", response_model=models.Offsite)
def clear_destination() -> dict:
    return offsite.clear_destination()


@router.post("/destination/test", response_model=Ok)
def test_destination() -> dict:
    offsite.test_connection()
    return {"ok": True}


@router.put("/passphrase", response_model=models.Offsite)
def set_passphrase(body: models.PassphraseIn, user: User = Depends(require_admin)) -> dict:
    return offsite.set_passphrase(user.id, body.passphrase)


@router.delete("/passphrase", response_model=models.Offsite)
def clear_passphrase() -> dict:
    return offsite.clear_passphrase()


@router.get("/{stamp}/download")
def download_backup(stamp: str) -> FileResponse:
    """The snapshot; with a backup passphrase, an age-encrypted copy named `<stamp>.sqlite.age`."""
    path = service.snapshot_path(stamp)
    encrypted = offsite.encrypted_copy(path)
    if encrypted is None:
        return FileResponse(path, filename=path.name, media_type="application/octet-stream")
    return FileResponse(
        encrypted,
        filename=f"{path.name}.age",
        media_type="application/octet-stream",
        background=BackgroundTask(encrypted.unlink, missing_ok=True),
    )


@router.get("/{stamp}/manifest", response_model=models.BackupManifest)
def get_manifest(stamp: str) -> dict:
    manifest = service.read_manifest(stamp)
    if manifest is None:
        raise NotFound("backup_not_found")
    return manifest
