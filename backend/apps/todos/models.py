"""Request and response shapes. Field caps mirror the service's limits; the service validates
again, because bulk updates and Whisk tools pass untyped dicts. Patch models are all-optional:
the router sends `model_dump(exclude_unset=True)`, so an omitted field is untouched and an
explicit null clears it."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.apps.todos.common import MAX_BULK, MAX_SHORT_CHARS, MAX_TAGS, MAX_TEXT_CHARS

Status = Literal["inbox", "next_action", "waiting_for", "delegated", "someday_maybe", "done", "dropped"]
ProjectStatus = Literal["active", "someday", "completed", "dropped"]
AreaStatus = Literal["active", "dropped"]
Visibility = Literal["private", "team"]


def Short():  # capitalised: reads as a type in the field lists below
    return Field(default=None, max_length=MAX_SHORT_CHARS)


def Text():
    return Field(default=None, max_length=MAX_TEXT_CHARS)


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ItemIn(_In):
    title: str = Field(max_length=MAX_TEXT_CHARS)
    notes: str = Field(default="", max_length=MAX_TEXT_CHARS)
    project_id: int | None = None
    area_id: int | None = None
    context: str = Field(default="", max_length=MAX_SHORT_CHARS)
    tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS)
    people: list[str] = Field(default_factory=list, max_length=MAX_TAGS)
    status: Status = "inbox"
    star: bool = False
    due_date: str | None = Field(default=None, max_length=10, description="YYYY-MM-DD")
    revisit_on: str | None = Field(default=None, max_length=10, description="YYYY-MM-DD; hidden from the working lists until then")
    repeat: str = Field(default="", max_length=20, description="'', daily, weekdays, weekly, monthly, yearly or every:N")
    auto_star_on_due: bool = False
    visibility: Visibility | None = Field(default=None, description="Defaults to the todos.default_visibility setting")
    owner_user_id: int | None = Field(default=None, description="Defaults to the caller")
    assignee_user_id: int | None = None
    entity_type: str | None = Field(default=None, max_length=100, description="A linked record, e.g. core.person")
    entity_id: int | None = None


class ItemPatch(_In):
    title: str | None = Text()
    notes: str | None = Text()
    project_id: int | None = None
    area_id: int | None = None
    context: str | None = Short()
    tags: list[str] | None = Field(default=None, max_length=MAX_TAGS)
    people: list[str] | None = Field(default=None, max_length=MAX_TAGS)
    status: Status | None = None
    star: bool | None = None
    due_date: str | None = Field(default=None, max_length=10)
    revisit_on: str | None = Field(default=None, max_length=10)
    repeat: str | None = Field(default=None, max_length=20)
    auto_star_on_due: bool | None = None
    visibility: Visibility | None = None
    owner_user_id: int | None = None
    assignee_user_id: int | None = None
    entity_type: str | None = Field(default=None, max_length=100)
    entity_id: int | None = None


class BulkIn(_In):
    ids: list[int] = Field(max_length=MAX_BULK)
    fields: dict = Field(description="Any ItemPatch fields")


class ContextRenameIn(_In):
    old: str = Field(max_length=MAX_SHORT_CHARS)
    new: str = Field(max_length=MAX_SHORT_CHARS)
    merge: bool = False


class ProjectIn(_In):
    name: str = Field(max_length=MAX_SHORT_CHARS)
    notes: str = Field(default="", max_length=MAX_TEXT_CHARS)
    status: ProjectStatus = "active"
    purpose: str = Field(default="", max_length=MAX_TEXT_CHARS)
    outcome: str = Field(default="", max_length=MAX_TEXT_CHARS)
    area_id: int | None = None
    visibility: Visibility | None = None
    assignee_user_id: int | None = None


class ProjectPatch(_In):
    name: str | None = Short()
    notes: str | None = Text()
    status: ProjectStatus | None = None
    purpose: str | None = Text()
    outcome: str | None = Text()
    area_id: int | None = None
    visibility: Visibility | None = None
    owner_user_id: int | None = None
    assignee_user_id: int | None = None


class AreaIn(_In):
    name: str = Field(max_length=MAX_SHORT_CHARS)
    notes: str = Field(default="", max_length=MAX_TEXT_CHARS)
    visibility: Visibility | None = None
    assignee_user_id: int | None = None


class AreaPatch(_In):
    name: str | None = Short()
    notes: str | None = Text()
    status: AreaStatus | None = None
    visibility: Visibility | None = None
    owner_user_id: int | None = None
    assignee_user_id: int | None = None


class TransferIn(_In):
    from_user_id: int
    to_user_id: int


# ── Responses ─────────────────────────────────────────────────────────────────


class Item(BaseModel):
    id: int
    title: str
    notes: str
    status: Status
    star: bool
    due_date: str | None
    revisit_on: str | None
    repeat: str
    auto_star_on_due: bool
    context: str
    tags: list[str]
    people: list[str]
    project_id: int | None
    project_name: str | None
    area_id: int | None = Field(description="The todo's own area; null means its project's")
    effective_area_id: int | None
    area_name: str | None
    owner_user_id: int
    owner_name: str | None
    visibility: Visibility
    assignee_user_id: int | None
    assignee_name: str | None
    entity_type: str | None
    entity_id: int | None
    source: Literal["ui", "agent", "app"]
    created_at: str
    updated_at: str
    completed_at: str | None
    rev: int


class Project(BaseModel):
    id: int
    name: str
    notes: str
    purpose: str
    outcome: str
    status: ProjectStatus
    area_id: int | None
    area_name: str | None
    owner_user_id: int
    visibility: Visibility
    assignee_user_id: int | None
    open_count: int = Field(description="Open todos in it that the caller can see")
    created_at: str
    updated_at: str
    rev: int


class Area(BaseModel):
    id: int
    name: str
    notes: str
    status: AreaStatus
    owner_user_id: int
    visibility: Visibility
    assignee_user_id: int | None
    created_at: str
    updated_at: str
    rev: int


class BulkOut(BaseModel):
    updated: list[int]
    not_found: list[int]


class ContextRenameOut(BaseModel):
    old: str
    new: str
    updated: int
    merged: bool


class Deleted(BaseModel):
    deleted: int


class Badge(BaseModel):
    count: int
    label: str | None = None


class Tombstone(BaseModel):
    id: int
    rev: int


class Removed(BaseModel):
    items: list[Tombstone]
    projects: list[Tombstone]
    areas: list[Tombstone]


class Changes(BaseModel):
    since_rev: int
    next_since_rev: int
    more: bool
    reset: bool
    changed: bool
    items: list[Item]
    projects: list[Project]
    areas: list[Area]
    removed: Removed


class Section(BaseModel):
    count: int
    items: list[Item]


class ReviewStatus(BaseModel):
    review_due: bool
    days_since_review: int | None
    last_review_at: str | None


class Review(ReviewStatus):
    today: str
    inbox: Section
    completed_last_week: Section
    dated_today_or_overdue: Section
    projects_without_next_action: list[Project]
    waiting_for: Section
    routines: Section
    upcoming: Section
    stale: Section
    areas: list[Area]


class NamedId(BaseModel):
    id: int
    name: str


class Filters(BaseModel):
    contexts: list[str]
    tags: list[str]
    people: list[str]
    areas: list[NamedId]
    status_counts: dict[str, int]
    tz: str
    members: list[NamedId]


class Moved(BaseModel):
    items: int
    projects: int
    areas: int
