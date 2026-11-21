"""Check-in routes (agent.md §11): the caller's own scheduled Whisk check-ins."""

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from backend.core.auth.deps import User, current_user
from backend.core.checkins import service
from backend.core.platform.models import Out

router = APIRouter(prefix="/api/agent/checkins", tags=["core"])


class Checkin(Out):
    id: int
    name: str
    prompt: str
    schedule: str  # every:<minutes> | daily@HH:MM | weekly:<mon..sun>@HH:MM, install timezone
    enabled: bool
    next_run_at: str
    failures: int  # failed runs in a row
    last_run_at: str | None
    last_status: Literal["ok", "silent", "error"] | None
    last_error: str | None
    created_at: str


class CheckinIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=service.NAME_MAX)
    prompt: str = Field(min_length=1, max_length=service.PROMPT_MAX)
    schedule: str = Field(max_length=40)


class CheckinPatch(BaseModel):
    # simplification: pause/resume only; editing is delete and recreate. Upgrade: name/prompt/schedule here.
    model_config = ConfigDict(extra="forbid")
    enabled: bool


@router.get("", response_model=list[Checkin])
def list_checkins(user: User = Depends(current_user)) -> list[dict]:
    return service.list_for(user)


@router.post("", response_model=Checkin)
def create_checkin(body: CheckinIn, user: User = Depends(current_user)) -> dict:
    return service.create(user, body.name, body.prompt, body.schedule)


@router.patch("/{checkin_id}", response_model=Checkin)
def update_checkin(checkin_id: int, body: CheckinPatch, user: User = Depends(current_user)) -> dict:
    return service.set_enabled(user, checkin_id, body.enabled)


@router.post("/{checkin_id}/run", response_model=Checkin, status_code=202)
async def run_checkin(checkin_id: int, request: Request, user: User = Depends(current_user)) -> dict:
    """Make it due now and start the job; the reply arrives as a notification."""
    row = await asyncio.to_thread(service.run_now, user, checkin_id)
    running = getattr(request.app.state, "scheduler", None)
    if running is not None and service.JOB in running.jobs:
        # simplification: a pass that already made its last claim misses this one until the next
        # tick (60 s at most); upgrade: a "run again" flag on the in-flight guard.
        await running.run_now(service.JOB)
    return row


@router.delete("/{checkin_id}", status_code=204)
def delete_checkin(checkin_id: int, user: User = Depends(current_user)) -> Response:
    service.delete(user, checkin_id)
    return Response(status_code=204)
