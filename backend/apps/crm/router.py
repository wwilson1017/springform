"""The CRM API at /api/crm (mounted behind the manifest's roles). Errors are `{detail}`: 401 not
signed in, 403 refused (an admin-only route, or a readable deal you may not write), 404 missing
or not readable, 409 a state conflict (an archived deal's stage), 422 invalid. Every deal route
authorizes the deal through `entities.authorize` in its service. Handlers are plain `def`, so
FastAPI runs the SQLite work in its threadpool."""

from typing import Literal

from fastapi import APIRouter, Depends, File, Query, UploadFile

from backend.apps.crm import (
    activity,
    analytics,
    dashboard,
    deals,
    meta,
    provenance,
    reports,
    scoring,
    settings as crm_settings,
    smart_import,
    stage_criteria,
    touch_count,
)
from backend.apps.crm.models import (
    Activity,
    ActivityIn,
    ActivityPatch,
    Analytics,
    ArchiveIn,
    BackfillStatus,
    Badge,
    Board,
    BulkMoveIn,
    BulkMoveOut,
    CrmSettings,
    CrmSettingsPatch,
    Dashboard,
    Deal,
    DealDetail,
    DealHealth,
    DealIn,
    DealPatch,
    Deleted,
    DuplicateGroup,
    ImportConfirmIn,
    ImportParsed,
    ImportResult,
    LostIn,
    MergeIn,
    Meta,
    OrganizationRollup,
    PersonScore,
    PipelineAnalytics,
    Provenance,
    ProvenanceConfirmIn,
    ResetIn,
    ResetOut,
    ScoresBackfillOut,
    Stage,
    StageCriteria,
    StageCriteriaIn,
    StageEvent,
    StaleDeals,
    Today,
    TouchEvidence,
    WeeklyTouchDetail,
    WeeklyTouches,
    WonIn,
)
from backend.core import db
from backend.core.auth.deps import User, current_user, require_admin

router = APIRouter()
ProvenanceType = Literal["crm.deal", "core.person"]

# ── Deals ─────────────────────────────────────────────────────────────────────


@router.get("/deals", response_model=Board)
def board(
    stage: Stage | None = None,
    include_archived: bool = False,
    limit: int | None = Query(None, ge=1, le=500, description="Keyset page size; pages are ordered by id"),
    after_id: int | None = Query(None, ge=0, description="The last id of the previous page"),
    limit_per_stage: int | None = Query(None, ge=1, le=200),
    user: User = Depends(current_user),
) -> dict:
    """The pipeline board (see deals.board for the three bounding modes)."""
    return deals.board(
        user, stage=stage, include_archived=include_archived, limit=limit, after_id=after_id, limit_per_stage=limit_per_stage
    )


@router.get("/deals/search", response_model=list[Deal])
def search_deals(
    q: str | None = Query(None, max_length=200, description="Every word, as a prefix, in the deal or its person or organization"),
    stage: Stage | None = None,
    person_id: int | None = None,
    organization_id: int | None = None,
    owner_user_id: int | None = None,
    sort_by: Literal["updated_at", "created_at", "value_cents", "expected_close", "title", "stage", "probability", "lead_score"] = "updated_at",
    sort_dir: Literal["asc", "desc"] = "desc",
    limit: int = Query(25, ge=1, le=100),
    include_archived: bool = False,
    user: User = Depends(current_user),
) -> list[dict]:
    return deals.search(
        user, q, stage=stage, person_id=person_id, organization_id=organization_id, owner_user_id=owner_user_id,
        sort_by=sort_by, sort_dir=sort_dir, limit=limit, include_archived=include_archived,
    )  # fmt: skip


@router.get("/deals/duplicates", response_model=list[DuplicateGroup])
def duplicate_deals(user: User = Depends(current_user)) -> list[dict]:
    return analytics.duplicates(user)


@router.post("/deals", response_model=Deal)
def create_deal(body: DealIn, user: User = Depends(current_user)) -> dict:
    return deals.create(user, body.model_dump(exclude_unset=True))


@router.post("/deals/bulk-move", response_model=BulkMoveOut)
def bulk_move(body: BulkMoveIn, user: User = Depends(current_user)) -> dict:
    """Move many deals to one stage. A deal that cannot move is listed in errors; the rest move."""
    return deals.bulk_move(user, body.ids, body.stage, body.closed_on)


@router.get("/deals/{deal_id}", response_model=DealDetail)
def get_deal(deal_id: int, user: User = Depends(current_user)) -> dict:
    return deals.detail(user, deal_id)


@router.patch("/deals/{deal_id}", response_model=Deal)
def update_deal(deal_id: int, body: DealPatch, user: User = Depends(current_user)) -> dict:
    return deals.update(user, deal_id, body.model_dump(exclude_unset=True))


@router.post("/deals/{deal_id}/won", response_model=Deal)
def mark_won(deal_id: int, body: WonIn, user: User = Depends(current_user)) -> dict:
    return deals.mark_won(user, deal_id, body.closed_on)


@router.post("/deals/{deal_id}/lost", response_model=Deal)
def mark_lost(deal_id: int, body: LostIn, user: User = Depends(current_user)) -> dict:
    return deals.mark_lost(user, deal_id, body.reason)


@router.post("/deals/{deal_id}/archive", response_model=Deal)
def archive_deal(deal_id: int, body: ArchiveIn, user: User = Depends(current_user)) -> dict:
    return deals.archive(user, deal_id, body.reason)


@router.post("/deals/{deal_id}/restore", response_model=Deal)
def restore_deal(deal_id: int, user: User = Depends(current_user)) -> dict:
    return deals.restore(user, deal_id)


@router.post("/deals/{deal_id}/merge", response_model=Deal)
def merge_deals(deal_id: int, body: MergeIn, user: User = Depends(current_user)) -> dict:
    """Fold body.source_id into this deal; the source is archived."""
    return deals.merge(user, deal_id, body.source_id)


@router.get("/deals/{deal_id}/stage-events", response_model=list[StageEvent])
def stage_events(deal_id: int, user: User = Depends(current_user)) -> list[dict]:
    return deals.stage_events_in(db.get_conn(), user, deal_id)


@router.get("/deals/{deal_id}/health", response_model=DealHealth)
def deal_health(deal_id: int, user: User = Depends(current_user)) -> dict:
    return analytics.deal_health(user, deal_id)


@router.get("/deals/{deal_id}/touch-evidence", response_model=TouchEvidence)
def touch_evidence(deal_id: int, user: User = Depends(current_user)) -> dict:
    return touch_count.evidence(user, deal_id)


@router.get("/people/{person_id}/deals", response_model=list[Deal])
def person_deals(person_id: int, include_archived: bool = False, user: User = Depends(current_user)) -> list[dict]:
    """The person page's Deals panel; 404 when the person is not readable."""
    return deals.for_record_in(db.get_conn(), user, "core.person", person_id, include_archived)


@router.get("/organizations/{organization_id}/deals", response_model=list[Deal])
def organization_deals(organization_id: int, include_archived: bool = False, user: User = Depends(current_user)) -> list[dict]:
    return deals.for_record_in(db.get_conn(), user, "core.organization", organization_id, include_archived)


@router.get("/organizations/{organization_id}/rollup", response_model=OrganizationRollup)
def organization_rollup(organization_id: int, user: User = Depends(current_user)) -> dict:
    return reports.organization_rollup(user, organization_id)


@router.get("/badge", response_model=Badge)
def badge(user: User = Depends(current_user)) -> dict:
    return deals.badge(user)


# ── Activity ──────────────────────────────────────────────────────────────────


@router.get("/activity", response_model=list[Activity])
def list_activity(
    deal_id: int | None = None, person_id: int | None = None, limit: int = Query(50, ge=1, le=500),
    user: User = Depends(current_user),
) -> list[dict]:
    return activity.list_(user, deal_id=deal_id, person_id=person_id, limit=limit)


@router.post("/activity", response_model=Activity)
def log_activity(body: ActivityIn, user: User = Depends(current_user)) -> dict:
    return activity.log(user, body.activity, body.note, deal_id=body.deal_id, person_id=body.person_id)


@router.patch("/activity/{activity_id}", response_model=Activity)
def update_activity(activity_id: int, body: ActivityPatch, user: User = Depends(current_user)) -> dict:
    return activity.update(user, activity_id, body.model_dump(exclude_unset=True))


@router.delete("/activity/{activity_id}", response_model=Deleted)
def delete_activity(activity_id: int, user: User = Depends(current_user)) -> dict:
    activity.delete(user, activity_id)
    return {"deleted": activity_id}


# ── Dashboard and analytics ───────────────────────────────────────────────────


@router.get("/dashboard", response_model=Dashboard)
def get_dashboard(user: User = Depends(current_user)) -> dict:
    return dashboard.dashboard(user)


@router.get("/dashboard/today", response_model=Today)
def today(user: User = Depends(current_user)) -> dict:
    return dashboard.today(user)


@router.get("/dashboard/weekly-touches", response_model=WeeklyTouches)
def weekly_touches(
    start: str | None = Query(None, max_length=10, description="YYYY-MM-DD, install-local"),
    end: str | None = Query(None, max_length=10, description="YYYY-MM-DD, inclusive"),
    user: User = Depends(current_user),
) -> dict:
    return dashboard.weekly_touches(user, start, end)


@router.get("/dashboard/weekly-touches/detail", response_model=WeeklyTouchDetail)
def weekly_touch_detail(
    owner: str = Query(pattern=r"^(\d{1,10}|unassigned)$", description="A user id, or 'unassigned'"),
    start: str | None = Query(None, max_length=10),
    end: str | None = Query(None, max_length=10),
    user: User = Depends(current_user),
) -> dict:
    return dashboard.weekly_touch_detail(user, owner, start, end)


@router.get("/analytics", response_model=Analytics)
def get_analytics(
    days: int = Query(30, ge=7, le=365), stale_days: int | None = Query(None, ge=1, le=365), user: User = Depends(current_user)
) -> dict:
    return analytics.analytics(user, days, stale_days)


@router.get("/analytics/pipeline", response_model=PipelineAnalytics)
def get_pipeline_analytics(days: int = Query(90, ge=7, le=730), user: User = Depends(current_user)) -> dict:
    return analytics.pipeline_analytics(user, days)


@router.get("/stale-deals", response_model=StaleDeals)
def stale_deals(
    days: int | None = Query(None, ge=1, le=365), limit: int = Query(25, ge=1, le=200), user: User = Depends(current_user)
) -> dict:
    return analytics.stale_deals(user, days, limit)


# ── Scores and touch counts ───────────────────────────────────────────────────


@router.get("/scores/people", response_model=list[PersonScore])
def person_scores(ids: str = Query(pattern=r"^\d{1,10}(,\d{1,10}){0,199}$", description="Comma-separated person ids"), user: User = Depends(current_user)) -> list[dict]:
    """Stored lead scores for the given people (never-scored people are absent)."""
    return scoring.person_scores([int(i) for i in ids.split(",")])


@router.post("/scores/backfill", response_model=ScoresBackfillOut)
def scores_backfill(user: User = Depends(require_admin)) -> dict:
    return scoring.backfill()


@router.get("/touch-count/backfill", response_model=BackfillStatus)
def touch_backfill_status(user: User = Depends(current_user)) -> dict:
    return touch_count.status()


@router.post("/touch-count/backfill", response_model=BackfillStatus)
def touch_backfill(scope: Literal["missing", "all"] = "missing", user: User = Depends(require_admin)) -> dict:
    """Queue deals for the crm.touch_count job: never-counted ones, or every live deal."""
    return touch_count.request_backfill(scope)


# ── Provenance ────────────────────────────────────────────────────────────────


@router.get("/provenance/{entity_type}/{entity_id}", response_model=Provenance)
def get_provenance(entity_type: ProvenanceType, entity_id: int, user: User = Depends(current_user)) -> dict:
    """The fields Whisk wrote that nobody has confirmed or edited since."""
    return provenance.get(user, entity_type, entity_id)


@router.post("/provenance/{entity_type}/{entity_id}/confirm", response_model=Provenance)
def confirm_provenance(
    entity_type: ProvenanceType, entity_id: int, body: ProvenanceConfirmIn, user: User = Depends(current_user)
) -> dict:
    return provenance.confirm(user, entity_type, entity_id, body.fields)


# ── Stage criteria ────────────────────────────────────────────────────────────


@router.get("/stage-criteria", response_model=list[StageCriteria])
def list_stage_criteria(user: User = Depends(current_user)) -> list[dict]:
    return stage_criteria.list_criteria()


@router.put("/stage-criteria/{stage}", response_model=StageCriteria)
def set_stage_criteria(stage: Stage, body: StageCriteriaIn, user: User = Depends(require_admin)) -> dict:
    return stage_criteria.set_criteria(stage, body.summary, body.checklist)


@router.delete("/stage-criteria/{stage}", response_model=StageCriteria)
def reset_stage_criteria(stage: Stage, user: User = Depends(require_admin)) -> dict:
    """Back to the standard wording."""
    return stage_criteria.reset_criteria(stage)


# ── Import ────────────────────────────────────────────────────────────────────


@router.post("/import/parse", response_model=ImportParsed)
def import_parse(file: UploadFile = File(...), user: User = Depends(current_user)) -> dict:
    """Read a CSV or vCard file into people to review; nothing is saved."""
    return smart_import.parse(user, file.filename or "", file.file.read(smart_import.MAX_BYTES + 1))


@router.post("/import/confirm", response_model=ImportResult)
def import_confirm(body: ImportConfirmIn, user: User = Depends(current_user)) -> dict:
    """Create the reviewed people and link their organizations."""
    return smart_import.confirm(user, [p.model_dump() for p in body.people])


# ── Settings, first run, reset ────────────────────────────────────────────────


@router.get("/settings", response_model=CrmSettings)
def get_settings(user: User = Depends(require_admin)) -> dict:
    return crm_settings.current()


@router.patch("/settings", response_model=CrmSettings)
def update_settings(body: CrmSettingsPatch, user: User = Depends(require_admin)) -> dict:
    return crm_settings.update(user, body.model_dump(exclude_unset=True, exclude_none=True))


@router.get("/meta", response_model=Meta)
def get_meta(user: User = Depends(current_user)) -> dict:
    return meta.get()


@router.post("/meta/dismiss-onboarding", response_model=Meta)
def dismiss_onboarding(user: User = Depends(current_user)) -> dict:
    return meta.dismiss_onboarding()


@router.post("/reset", response_model=ResetOut)
def reset(body: ResetIn, user: User = Depends(require_admin)) -> dict:
    """Delete every deal and activity (with their notes, files and history); keep people and
    organizations. Body {"confirm": "RESET"}."""
    return meta.reset(user)
