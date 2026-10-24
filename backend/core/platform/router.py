"""Routes for settings, workspace, apps admin, jobs and the change log. `GET /api/core/apps` lives
in main.py; this adds the admin writes beside it. Function names carry their area so the
`core_<function>` operationIds stay unique across core packages."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.core import registry
from backend.core.auth.deps import User, current_user, require_admin
from backend.core.platform import models, service

settings_router = APIRouter(prefix="/api/core/settings", tags=["core"])
workspace_router = APIRouter(prefix="/api/core/workspace", tags=["core"])
apps_router = APIRouter(prefix="/api/core/apps", tags=["core"])
jobs_router = APIRouter(prefix="/api/core/jobs", tags=["core"], dependencies=[Depends(require_admin)])
changelog_router = APIRouter(prefix="/api/core/changelog", tags=["core"])


class SettingsIn(BaseModel):
    values: dict[str, Any]


class AppPatch(BaseModel):
    hidden: bool | None = None


class AppOrder(BaseModel):
    slugs: list[str]


@settings_router.get("", response_model=models.CoreSettings)
def settings_get(user: User = Depends(require_admin)) -> dict:
    return service.settings_view()


@settings_router.put("", response_model=models.CoreSettings)
def settings_put(body: SettingsIn, user: User = Depends(require_admin)) -> dict:
    return service.update_settings(user.id, body.values)


@settings_router.delete("/{key}", response_model=models.CoreSettings)
def settings_reset(key: str, user: User = Depends(require_admin)) -> dict:
    return service.reset_setting(key)


@workspace_router.get("", response_model=models.Workspace)
def workspace_get(user: User = Depends(current_user)) -> dict:
    return service.workspace()


@apps_router.patch("/{slug}", response_model=list[models.CoreApp])
def apps_patch(slug: str, body: AppPatch, user: User = Depends(require_admin)) -> list[dict]:
    registry.get_app(slug)
    if body.hidden is not None:
        service.set_hidden(slug, body.hidden)
    return registry.list_for_user(user)


@apps_router.put("/order", response_model=list[models.CoreApp])
def apps_order(body: AppOrder, user: User = Depends(require_admin)) -> list[dict]:
    service.set_order(body.slugs)
    return registry.list_for_user(user)


@jobs_router.get("", response_model=list[models.JobInfo])
def jobs_list() -> list[dict]:
    return service.jobs_list()


@jobs_router.get("/runs", response_model=list[models.JobRun])
def jobs_runs(job: str | None = None, limit: int | None = None) -> list[dict]:
    return service.job_runs(job, limit)


@jobs_router.get("/outbox/dead", response_model=list[models.DeadOutboxRow])
def jobs_dead_outbox(limit: int | None = None) -> list[dict]:
    return service.dead_outbox(limit)


@jobs_router.post("/{name}/run", status_code=202, response_model=models.JobStarted)
async def jobs_run_now(name: str, request: Request) -> dict:
    running = getattr(request.app.state, "scheduler", None)
    if running is None:
        raise HTTPException(503, detail="scheduler_not_running")
    if name not in running.jobs:
        raise HTTPException(404, detail="unknown_job")
    if not await running.run_now(name):
        raise HTTPException(409, detail="already_running")
    return {"started": True}


@changelog_router.get("", response_model=list[models.ChangeRow])
def changelog_list(
    app: str | None = None,
    user_id: int | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    before: int | None = None,
    limit: int | None = None,
    user: User = Depends(current_user),
) -> list[dict]:
    return service.changelog_list(
        user, app=app, user_id=user_id, entity_type=entity_type, entity_id=entity_id, before=before, limit=limit
    )


router = APIRouter()
for _sub in (settings_router, workspace_router, apps_router, jobs_router, changelog_router):
    router.include_router(_sub)
