"""The Todos API at /api/todos (mounted behind the manifest's roles). Ported from todo-gtd's
build_router: the list in the address became the signed-in user. Errors are `{detail}`: 401 not
signed in, 403 refused, 404 missing or not visible, 409 a context merge to confirm, 422 invalid.
Handlers are plain `def`, so FastAPI runs the SQLite work in its threadpool."""

from fastapi import APIRouter, Depends, Query

from backend.apps.todos import service
from backend.apps.todos.models import (
    Area,
    AreaIn,
    AreaPatch,
    Badge,
    BulkIn,
    BulkOut,
    Changes,
    ContextRenameIn,
    ContextRenameOut,
    Deleted,
    Filters,
    Item,
    ItemIn,
    ItemPatch,
    Moved,
    Project,
    ProjectIn,
    ProjectPatch,
    Review,
    ReviewStatus,
    Status,
    TransferIn,
    Visibility,
)
from backend.core.auth.deps import User, current_user, require_admin

router = APIRouter()

# ── Todos ─────────────────────────────────────────────────────────────────────


@router.get("/items", response_model=list[Item])
def list_items(
    status: Status | None = None,
    project_id: int | None = None,
    area_id: int | None = None,
    context: str | None = None,
    tag: str | None = None,
    person: str | None = None,
    starred: bool | None = None,
    due_before: str | None = None,
    due_after: str | None = None,
    search: str | None = None,
    assignee_user_id: int | None = None,
    visibility: Visibility | None = None,
    mine: bool = Query(False, description="Only the caller's work: their private todos, team todos assigned to them, unassigned team todos"),
    include_deferred: bool = Query(False, description="Keep todos whose revisit date is still ahead"),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(current_user),
) -> list[dict]:
    return service.list_items(
        user, status=status, project_id=project_id, area_id=area_id, context=context, tag=tag, person=person,
        starred=starred, due_before=due_before, due_after=due_after, search=search,
        assignee_user_id=assignee_user_id, visibility=visibility, mine=mine, include_deferred=include_deferred,
        limit=limit, offset=offset,
    )  # fmt: skip


@router.post("/items", response_model=Item)
def create_item(body: ItemIn, user: User = Depends(current_user)) -> dict:
    fields = body.model_dump()
    return service.create_item(user, fields.pop("title"), **fields, source="ui")


@router.post("/items/bulk", response_model=BulkOut)
def bulk_update(body: BulkIn, user: User = Depends(current_user)) -> dict:
    """The same change on many todos; all or nothing. Ids the caller cannot see come back in not_found."""
    return service.bulk_update(user, body.ids, body.fields)


@router.get("/items/{item_id}", response_model=Item)
def get_item(item_id: int, user: User = Depends(current_user)) -> dict:
    return service.get_item(user, item_id)


@router.patch("/items/{item_id}", response_model=Item)
def update_item(item_id: int, body: ItemPatch, user: User = Depends(current_user)) -> dict:
    return service.update_item(user, item_id, body.model_dump(exclude_unset=True))


@router.post("/items/{item_id}/complete", response_model=Item)
def complete_item(item_id: int, user: User = Depends(current_user)) -> dict:
    """Mark done; a repeating todo spawns its next occurrence."""
    return service.complete(user, item_id)


@router.delete("/items/{item_id}", response_model=Deleted)
def delete_item(item_id: int, user: User = Depends(current_user)) -> dict:
    service.delete_item(user, item_id)
    return {"deleted": item_id}


@router.get("/today", response_model=list[Item])
def today(user: User = Depends(current_user)) -> list[dict]:
    return service.today_view(user)


@router.get("/for/{entity_type}/{entity_id}", response_model=list[Item])
def for_record(entity_type: str, entity_id: int, include_done: bool = False, user: User = Depends(current_user)) -> list[dict]:
    """Team todos and the caller's private ones linked to a record; 404 when the record is not readable."""
    return service.list_for_record(user, entity_type, entity_id, include_done)


@router.get("/changes", response_model=Changes)
def changes(
    since_rev: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=500),
    head: bool = Query(False, description="Only the current cursor: next_since_rev, no rows"),
    user: User = Depends(current_user),
) -> dict:
    return service.changes(user, since_rev, limit, head_only=head)


@router.get("/filters", response_model=Filters)
def filters(user: User = Depends(current_user)) -> dict:
    return service.filters(user)


@router.post("/contexts/rename", response_model=ContextRenameOut)
def rename_context(body: ContextRenameIn, user: User = Depends(current_user)) -> dict:
    """409 when the new name is already a context; send merge=true to confirm."""
    return service.rename_context(user, body.old, body.new, merge=body.merge)


@router.get("/badge", response_model=Badge)
def badge(user: User = Depends(current_user)) -> dict:
    return service.badge(user)


# ── Weekly review ─────────────────────────────────────────────────────────────


@router.get("/review", response_model=Review)
def review(user: User = Depends(current_user)) -> dict:
    return service.review(user)


@router.post("/review/done", response_model=ReviewStatus)
def mark_review_done(user: User = Depends(current_user)) -> dict:
    return service.mark_review_done(user)


# ── Projects and areas ────────────────────────────────────────────────────────


@router.get("/projects", response_model=list[Project])
def list_projects(
    status: str | None = None, area_id: int | None = None, user: User = Depends(current_user)
) -> list[dict]:
    return service.list_projects(user, status, area_id)


@router.post("/projects", response_model=Project)
def create_project(body: ProjectIn, user: User = Depends(current_user)) -> dict:
    fields = body.model_dump()
    return service.create_project(user, fields.pop("name"), **fields)


@router.get("/projects/{project_id}", response_model=Project)
def get_project(project_id: int, user: User = Depends(current_user)) -> dict:
    return service.get_container(user, "project", project_id)


@router.patch("/projects/{project_id}", response_model=Project)
def update_project(project_id: int, body: ProjectPatch, user: User = Depends(current_user)) -> dict:
    return service.update_container(user, "project", project_id, body.model_dump(exclude_unset=True))


@router.delete("/projects/{project_id}", response_model=Deleted)
def delete_project(project_id: int, user: User = Depends(current_user)) -> dict:
    service.delete_container(user, "project", project_id)
    return {"deleted": project_id}


@router.get("/areas", response_model=list[Area])
def list_areas(status: str | None = None, user: User = Depends(current_user)) -> list[dict]:
    return service.list_areas(user, status)


@router.post("/areas", response_model=Area)
def create_area(body: AreaIn, user: User = Depends(current_user)) -> dict:
    fields = body.model_dump()
    return service.create_area(user, fields.pop("name"), **fields)


@router.get("/areas/{area_id}", response_model=Area)
def get_area(area_id: int, user: User = Depends(current_user)) -> dict:
    return service.get_container(user, "area", area_id)


@router.patch("/areas/{area_id}", response_model=Area)
def update_area(area_id: int, body: AreaPatch, user: User = Depends(current_user)) -> dict:
    return service.update_container(user, "area", area_id, body.model_dump(exclude_unset=True))


@router.delete("/areas/{area_id}", response_model=Deleted)
def delete_area(area_id: int, user: User = Depends(current_user)) -> dict:
    service.delete_container(user, "area", area_id)
    return {"deleted": area_id}


# ── Admin ─────────────────────────────────────────────────────────────────────


@router.post("/transfer", response_model=Moved)
def transfer(body: TransferIn, admin: User = Depends(require_admin)) -> dict:
    """Give one person's private areas, projects and todos to another (after a deactivation)."""
    return service.transfer(admin, body.from_user_id, body.to_user_id)
