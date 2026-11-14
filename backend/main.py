"""The Springform process. `create_app()` discovers and mounts apps at import; the lifespan runs
db checks and key files -> migrations -> preview checks -> seeds -> setup token -> startup hooks
-> scheduler, and stops the scheduler on exit.

Run with one worker (`uvicorn backend.main:app --workers 1`): the data-dir lock refuses a second.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.routing import APIRoute

from backend.core import REPO_ROOT, VERSION, db, errors, preview, registry, scheduler, secrets, settings
from backend.core.auth import bootstrap, csrf
from backend.core.auth.deps import User, current_user
from backend.core.backup import service as backup
from backend.core.platform.models import CoreApp, Health

FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


def _operation_id(route: APIRoute) -> str:
    """Stable operationIds for type generation: `<tag>_<function>`."""
    return f"{route.tags[0]}_{route.name}" if route.tags else route.name


def create_app(apps_dir: Path = db.APPS_DIR) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db.init(settings.data_dir())
        secrets.key(), settings.secret_key()  # first boot writes both key files; a bad one stops startup here
        db.migrate(db.app_dirs(apps_dir))
        preview.check_startup()
        registry.seed_apps()
        preview.seed()
        bootstrap.ensure_setup_token()
        registry.run_startup_hooks()
        app.state.scheduler = scheduler.Scheduler(scheduler.jobs())
        await app.state.scheduler.start()
        try:
            yield
        finally:
            await app.state.scheduler.stop()
            db.close()

    app = FastAPI(
        title="Springform", version=VERSION, lifespan=lifespan, generate_unique_id_function=_operation_id,
        docs_url=None, redoc_url=None, openapi_url=None,  # served signed-in only, by _serve_docs()
    )
    errors.install(app)
    csrf.install(app)
    # Core routers (`backend/core/<pkg>/router.py`), hooks, jobs and tools are picked up by
    # registry.install(), like an app's; nobody edits this file to add one.

    @app.get("/up", response_class=PlainTextResponse, include_in_schema=False)
    def up() -> str:
        db.get_conn().execute("SELECT 1")
        return "ok"

    @app.get("/api/health", tags=["core"], response_model=Health)
    def health() -> dict:
        conn = db.get_conn()
        return {
            "version": VERSION,
            "sqlite_version": conn.execute("SELECT sqlite_version()").fetchone()[0],
            "fts5": db.fts5_enabled(conn),
            "preview": settings.preview_mode(),
            "apps": [a.slug for a in registry.installed()],
            "last_backup_at": backup.last_backup_at(),
            "key_mismatch": backup.key_mismatch() is not None,
        }

    @app.get("/api/core/apps", tags=["core"], response_model=list[CoreApp])
    def list_apps(user: User = Depends(current_user)) -> list[dict]:
        return registry.list_for_user(user)

    _serve_docs(app)
    registry.install(app, apps_dir)
    if (FRONTEND_DIST / "index.html").is_file():
        _serve_frontend(app)
    return app


def _serve_docs(app: FastAPI) -> None:
    """FastAPI's /openapi.json, /docs and /redoc, for signed-in users only: a fork's schema describes
    its own apps. Signed out they 401 like any API route. `app.openapi()` (gen-types, tests) is unaffected."""
    signed_in = [Depends(current_user)]

    @app.get("/openapi.json", include_in_schema=False, dependencies=signed_in)
    def openapi() -> JSONResponse:
        return JSONResponse(app.openapi())

    @app.get("/docs", include_in_schema=False, dependencies=signed_in)
    def swagger_ui() -> HTMLResponse:
        return get_swagger_ui_html(openapi_url="/openapi.json", title=f"{app.title} - Swagger UI")

    @app.get("/redoc", include_in_schema=False, dependencies=signed_in)
    def redoc() -> HTMLResponse:
        return get_redoc_html(openapi_url="/openapi.json", title=f"{app.title} - ReDoc")


def _serve_frontend(app: FastAPI) -> None:
    """The built SPA: real files as themselves, every other non-/api path as index.html."""
    root = FRONTEND_DIST.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, detail="not_found")
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(root / "index.html")


app = create_app()
