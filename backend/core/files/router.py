from urllib.parse import quote

from fastapi import APIRouter, Depends, File as FormFile, Form, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.core.auth.deps import User, current_user
from backend.core.files import service

router = APIRouter(prefix="/api/core/files", tags=["core"])
NOSNIFF = {"X-Content-Type-Options": "nosniff"}


class Uploader(BaseModel):
    id: int
    name: str


class File(BaseModel):
    id: int
    filename: str
    mime_type: str
    byte_size: int
    sha256: str
    created_at: str
    uploaded_by: Uploader | None
    has_thumb: bool


@router.get("", response_model=list[File])
def list_files(entity_type: str, entity_id: int, user: User = Depends(current_user)) -> list[dict]:
    return service.list_for(user, entity_type, entity_id)


@router.post("", response_model=File, status_code=201, responses={200: {"model": File, "description": "Already attached"}})
def upload_file(
    response: Response,
    entity_type: str = Form(),
    entity_id: int = Form(),
    file: UploadFile = FormFile(),
    user: User = Depends(current_user),
) -> dict:
    """201 with the new file; 200 with the existing one when the record already has these bytes."""
    # simplification: Starlette spools the whole multipart body before this runs, so the size cap
    # is enforced after receipt; upgrade path: a streaming multipart parser with a Content-Length precheck.
    out, created = service.upload(user, entity_type, entity_id, file.filename, file.content_type, file.file)
    if not created:
        response.status_code = 200
    return out


@router.get("/{file_id}/download", response_class=FileResponse)
def download_file(file_id: int, user: User = Depends(current_user)) -> FileResponse:
    meta, path = service.download(user, file_id)
    disposition = f"attachment; filename*=UTF-8''{quote(meta['filename'], safe='')}"
    return FileResponse(path, media_type=meta["mime_type"], headers={"Content-Disposition": disposition, **NOSNIFF})


@router.get("/{file_id}/thumb", response_class=Response, responses={200: {"content": {"image/jpeg": {}}}})
def file_thumb(file_id: int, user: User = Depends(current_user)) -> Response:
    return Response(service.thumb(user, file_id), media_type="image/jpeg", headers=NOSNIFF)


@router.delete("/{file_id}", status_code=204)
def delete_file(file_id: int, user: User = Depends(current_user)) -> None:
    service.delete(user, file_id)
