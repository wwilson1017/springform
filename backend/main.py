"""The Springform process. `create_app()` discovers and mounts apps at import; the lifespan runs
db checks -> migrations -> preview checks -> seeds -> setup token -> scheduler, and stops the
scheduler on exit.

Run with one worker (`uvicorn backend.main:app --workers 1`): the data-dir lock refuses a second.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.routing import APIRoute

from backend.core import REPO_ROOT, VERSION, db, errors, preview, registry, scheduler, settings
from backend.core.auth import bootstrap, csrf
from backend.core.auth.deps import User, current_user, require_admin
from backend.core.auth.router import router as auth_router
from backend.core.timeline.router import router as timeline_router

FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


def _operation_id(route: APIRoute) -> str:
    """Stable operationIds for type generation: `<tag>_<function>`."""
    return f"{route.tags[0]}_{route.name}" if route.tags else route.name


def create_app(apps_dir: Path = db.APPS_DIR) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db.init(settings.data_dir())
        db.migrate(db.app_dirs(apps_dir))
        preview.check_startup()
        registry.seed_apps()
        preview.seed()
        bootstrap.ensure_setup_token()
        app.state.scheduler = scheduler.Scheduler(scheduler.jobs())
        await app.state.scheduler.start()
        try:
            yield
        finally:
            await app.state.scheduler.stop()
            db.close()

    app = FastAPI(title="Springform", version=VERSION, lifespan=lifespan, generate_unique_id_function=_operation_id)
    errors.install(app)
    csrf.install(app)
    app.include_router(auth_router)
    app.include_router(timeline_router)

    @app.get("/up", response_class=PlainTextResponse, include_in_schema=False)
    def up() -> str:
        db.get_conn().execute("SELECT 1")
        return "ok"

    @app.get("/api/health", tags=["core"])
    def health() -> dict:
        conn = db.get_conn()
        return {
            "version": VERSION,
            "sqlite_version": conn.execute("SELECT sqlite_version()").fetchone()[0],
            "fts5": db.fts5_enabled(conn),
            "preview": settings.preview_mode(),
            "apps": [a.slug for a in registry.installed()],
            "last_backup_at": None,  # the backup workstream fills this
        }

    @app.get("/api/core/apps", tags=["core"])
    def list_apps(user: User = Depends(current_user)) -> list[dict]:
        return registry.list_for_user(user)

    @app.post("/api/core/jobs/{name}/run", tags=["core"], status_code=202, dependencies=[Depends(require_admin)])
    async def run_job(name: str, request: Request) -> JSONResponse:
        """Start a job now: 202 started, 409 already running, 404 unknown."""
        sched = getattr(request.app.state, "scheduler", None)
        if sched is None or name not in sched.jobs:
            raise HTTPException(404, detail="not_found")
        if not await sched.run_now(name):
            raise HTTPException(409, detail="already_running")
        return JSONResponse({"job": name, "started": True}, status_code=202)

    registry.install(app, apps_dir)
    if (FRONTEND_DIST / "index.html").is_file():
        _serve_frontend(app)
    return app


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
