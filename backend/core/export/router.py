from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from backend.core.auth.deps import User, current_user, require_admin
from backend.core.errors import NotFound
from backend.core.export import csv_export, service
from backend.core.reports import registry as reports

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
    """A report as CSV. Query parameters are the report's params (strings). Same visibility as the
    report list: the app's roles, and admins only for admin_only reports; 404 otherwise."""
    report = reports.get(key)
    if report is None or key not in {r.key for r in reports.for_user(user)}:
        raise NotFound("no such report")
    columns, rows = report.run(dict(request.query_params), user)
    return csv_export.stream_csv(columns, rows, f"{key}.csv")
