from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from backend.core.auth.deps import User, current_user, require_admin
from backend.core.export import csv_export, service
from backend.core.reports import service as report_service

router = APIRouter(tags=["core"])


@router.get("/api/core/export")
def export_zip(user: User = Depends(require_admin)) -> StreamingResponse:
    """The business-data export: one CSV per allowed table plus manifest.json, in a ZIP."""
    buf, filename = service.export(user)
    return StreamingResponse(
        iter(lambda: buf.read(65536), b""), media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/api/core/export/preview", dependencies=[Depends(require_admin)])
def export_preview() -> dict:
    return service.preview()


@router.get("/api/core/reports/{key}/csv")
def report_csv(key: str, request: Request, user: User = Depends(current_user)) -> StreamingResponse:
    """A report as CSV, through the same checks as the JSON route: unknown key 404, not allowed
    403, params coerced to the report's spec with defaults applied, bad params 422."""
    result = report_service.run(user, key, dict(request.query_params))
    return csv_export.stream_csv(result["columns"], result["rows"], f"{key}.csv")
