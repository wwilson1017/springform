from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from backend.core.auth.deps import User, current_user, require_admin
from backend.core.errors import Forbidden, NotFound
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
    """A report as CSV. Query parameters are the report's params (strings). Who may run it: one of
    the app's roles, and admin for admin_only reports. Unknown key 404, not allowed 403."""
    # simplification: params reach run() as raw strings; once the reports API (reports/service.py)
    # lands, call its run(user, key, request.query_params) so both routes coerce params the same way.
    report = reports.get(key)
    if report is None:
        raise NotFound("no such report")
    if key not in {r.key for r in reports.for_user(user)}:
        raise Forbidden("admin_only" if report.admin_only else "forbidden")
    columns, rows = report.run(dict(request.query_params), user)
    return csv_export.stream_csv(columns, rows, f"{key}.csv")
