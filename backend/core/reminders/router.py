from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from backend.core.auth.deps import User, current_user
from backend.core.reminders import service

router = APIRouter(prefix="/api/core/reminders", tags=["core"])
Freq = Literal["daily", "weekly", "monthly", "yearly"]


class RepeatIn(BaseModel):
    """Only `freq` is read; a stored Repeat sent back is accepted (its other keys are recomputed)."""

    freq: Freq


class Repeat(BaseModel):
    freq: Freq
    anchor: str  # the series' first local date, YYYY-MM-DD
    time: str  # local wall time, HH:MM
    tz: str  # IANA zone the anchor and time are read in


class Person(BaseModel):
    id: int
    name: str


class Reminder(BaseModel):
    id: int
    owner: Person
    mine: bool
    entity_type: str | None
    entity_id: int | None
    entity_title: str | None
    link: str | None
    title: str
    note: str
    due_at: str
    repeat: Repeat | None
    series_id: int
    status: Literal["open", "done", "voided", "snoozed"]
    void_reason: str | None
    fired_at: str | None
    created_at: str
    updated_at: str


class ReminderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(max_length=service.TITLE_MAX)
    note: str = Field(default="", max_length=service.NOTE_MAX)
    due_at: str = Field(max_length=40)
    repeat: RepeatIn | None = None
    entity_type: str | None = Field(default=None, max_length=100)
    entity_id: int | None = None


class ReminderPatch(BaseModel):
    """Only the fields sent change; `repeat: null` stops repeating."""

    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, max_length=service.TITLE_MAX)
    note: str | None = Field(default=None, max_length=service.NOTE_MAX)
    due_at: str | None = Field(default=None, max_length=40)
    repeat: RepeatIn | None = None


class SnoozeIn(BaseModel):
    until: str = Field(max_length=40)


@router.get("", response_model=list[Reminder])
def list_reminders(
    from_: str | None = Query(None, alias="from", max_length=40), to: str | None = Query(None, max_length=40),
    status: str | None = None, limit: int | None = None, user: User = Depends(current_user),
) -> list[dict]:
    """The caller's reminders with from <= due_at < to, soonest first."""
    return service.list_mine(user, from_=from_, to=to, status=status, limit=limit)


@router.post("", response_model=Reminder)
def create_reminder(body: ReminderIn, user: User = Depends(current_user)) -> dict:
    fields = body.model_dump()
    fields["repeat"] = body.repeat.freq if body.repeat else None
    return service.create(user, **fields)


@router.get("/for", response_model=list[Reminder])
def reminders_for_record(entity_type: str, entity_id: int, user: User = Depends(current_user)) -> list[dict]:
    return service.list_for_record(user, entity_type, entity_id)


@router.patch("/{reminder_id}", response_model=Reminder)
def update_reminder(reminder_id: int, body: ReminderPatch, user: User = Depends(current_user)) -> dict:
    fields = body.model_dump(exclude_unset=True)
    if "repeat" in fields:
        fields["repeat"] = body.repeat.freq if body.repeat else None
    return service.update(user, reminder_id, fields)


@router.post("/{reminder_id}/snooze", response_model=Reminder)
def snooze_reminder(reminder_id: int, body: SnoozeIn, user: User = Depends(current_user)) -> dict:
    return service.snooze(user, reminder_id, body.until)


@router.post("/{reminder_id}/done", response_model=Reminder)
def complete_reminder(reminder_id: int, user: User = Depends(current_user)) -> dict:
    return service.complete(user, reminder_id)


@router.delete("/{reminder_id}", status_code=204)
def delete_reminder(reminder_id: int, user: User = Depends(current_user)) -> Response:
    service.delete(user, reminder_id)
    return Response(status_code=204)
