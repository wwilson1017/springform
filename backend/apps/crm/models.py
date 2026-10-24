"""Request and response shapes for /api/crm. Money is integer cents (`*_cents`); dates the user
picks are YYYY-MM-DD; instants are canonical UTC (`YYYY-MM-DDTHH:MM:SSZ`). Patch models are
all-optional: the router sends `model_dump(exclude_unset=True)`, so an omitted field is
untouched and an explicit null clears it."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.apps.crm.common import BULK_MOVE_MAX, MAX_REASON, MAX_TEXT, MAX_TITLE

Stage = Literal["lead", "qualified", "proposal", "negotiation", "won", "lost"]
Temperature = Literal["hot", "warm", "cold"]
Day = Field(default=None, max_length=10, description="YYYY-MM-DD")
MAX_CENTS = 10**15  # a quadrillion cents: past any real deal, well inside SQLite's 64-bit integer


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ── Deals ─────────────────────────────────────────────────────────────────────


class DealIn(_In):
    title: str = Field(min_length=1, max_length=MAX_TITLE)
    stage: Stage = "lead"
    value_cents: int = Field(default=0, ge=-MAX_CENTS, le=MAX_CENTS)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    probability: int = Field(default=0, ge=0, le=100)
    expected_close: str | None = Day
    closed_on: str | None = Field(default=None, max_length=10, description="YYYY-MM-DD; only for a deal created won (default today)")
    notes: str = Field(default="", max_length=MAX_TEXT)
    person_id: int | None = None
    organization_id: int | None = None
    owner_user_id: int | None = None
    deal_temperature: Temperature | None = None


class DealPatch(_In):
    title: str | None = Field(default=None, min_length=1, max_length=MAX_TITLE)
    stage: Stage | None = None
    value_cents: int | None = Field(default=None, ge=-MAX_CENTS, le=MAX_CENTS)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    probability: int | None = Field(default=None, ge=0, le=100)
    expected_close: str | None = Day
    closed_on: str | None = Field(
        default=None, max_length=10,
        description="YYYY-MM-DD. With a move into won: the day it was won (default today). Alone: edits a won deal's day.",
    )
    notes: str | None = Field(default=None, max_length=MAX_TEXT)
    person_id: int | None = None
    organization_id: int | None = None
    owner_user_id: int | None = None
    deal_temperature: Temperature | None = None


class Deal(BaseModel):
    id: int
    title: str
    stage: Stage
    status: Literal["open", "won", "lost"]
    value_cents: int
    currency: str
    probability: int
    expected_close: str | None
    closed_on: str | None
    lost_reason: str
    deal_temperature: Temperature | None
    notes: str
    person_id: int | None
    person_name: str | None
    organization_id: int | None
    organization_name: str | None
    owner_user_id: int | None
    owner_name: str | None
    lead_score: int | None
    lead_score_at: str | None
    ai_touch_count: int | None
    ai_touch_count_at: str | None
    last_activity_at: str | None = Field(description="Newest activity or timeline note on the deal")
    archived_at: str | None
    archived_by: int | None
    archived_reason: str | None
    created_at: str
    updated_at: str


class StageSummary(BaseModel):
    stage: Stage
    count: int
    total_value_cents: int


class Board(BaseModel):
    deals: list[Deal]
    stage_summary: list[StageSummary] | None = Field(description="Open stages, live deals; null on a continuation page")
    total_pipeline_value_cents: int | None
    deals_truncated: bool | None = Field(default=None, description="Only with limit_per_stage")


class StageEvent(BaseModel):
    id: int
    old_stage: str
    new_stage: Stage
    user_id: int | None
    user_name: str | None
    changed_at: str


class Activity(BaseModel):
    id: int
    activity: str
    note: str
    deal_id: int | None
    deal_title: str | None
    person_id: int | None
    person_name: str | None
    actor_user_id: int | None
    actor_name: str | None
    created_at: str


class DealDetail(Deal):
    activity: list[Activity]
    stage_events: list[StageEvent]


class BulkMoveIn(_In):
    ids: list[int] = Field(min_length=1, max_length=BULK_MOVE_MAX)
    stage: Stage
    closed_on: str | None = Field(default=None, max_length=10, description="For a move into won; default today")


class BulkMoveOut(BaseModel):
    ok: bool
    updated: int
    updated_ids: list[int]
    errors: list[str]


class WonIn(_In):
    closed_on: str | None = Field(default=None, max_length=10, description="Default today; on an already-won deal, edits the day")


class LostIn(_In):
    reason: str = Field(default="", max_length=MAX_REASON)


class ArchiveIn(_In):
    reason: str = Field(min_length=1, max_length=MAX_REASON)


class MergeIn(_In):
    source_id: int = Field(description="The deal folded into this one and archived")


class Deleted(BaseModel):
    deleted: int


class Badge(BaseModel):
    count: int
    label: str | None = None


# ── Activity ──────────────────────────────────────────────────────────────────


class ActivityIn(_In):
    activity: str = Field(min_length=1, max_length=100, description="call, email, meeting, …")
    note: str = Field(default="", max_length=MAX_TEXT)
    deal_id: int | None = None
    person_id: int | None = None


class ActivityPatch(_In):
    activity: str | None = Field(default=None, min_length=1, max_length=100)
    note: str | None = Field(default=None, max_length=MAX_TEXT)


# ── Dashboard, Today, touches ─────────────────────────────────────────────────


class Dashboard(BaseModel):
    total_people: int
    total_organizations: int
    pipeline_by_stage: list[StageSummary] = Field(description="Every stage, live deals")
    total_pipeline_value_cents: int = Field(description="Open stages only")
    won_this_month_cents: int = Field(description="Won deals whose closed_on is in the install-local month")
    recent_activity: list[Activity]
    top_deals: list[Deal] = Field(description="Open deals past lead, ranked by value weighted by probability")


class TodayItem(BaseModel):
    kind: Literal["deal", "reminder"]
    rank: int | None = Field(description="1 hot and stale deal, 2 reminder due today; null: only in the expanded list")
    reason: str
    deal: Deal | None = None
    reminder: dict | None = Field(default=None, description="core reminder shape")


class Today(BaseModel):
    date: str
    next_refresh_at: str
    items: list[TodayItem]


class TouchWindow(BaseModel):
    start: str
    end: str
    label: str
    custom: bool


class TouchedDeal(BaseModel):
    id: int
    title: str
    value_cents: int
    stage: Stage
    owner_user_id: int | None
    touch_count: int | None
    touched_at: str | None
    person_name: str | None
    organization_name: str | None


class TouchRep(BaseModel):
    user_id: int | None = Field(description="null: the unassigned pile")
    name: str
    open_deals: int
    touches: int
    deals: list[TouchedDeal]


class WeeklyTouches(BaseModel):
    window: TouchWindow
    reps: list[TouchRep]
    total_touches: int
    total_open_deals: int


class WeeklyTouchDetail(BaseModel):
    window: TouchWindow
    rep: TouchRep
    deals: list[TouchedDeal]
    truncated: bool


# ── Analytics ─────────────────────────────────────────────────────────────────


class WinLoss(BaseModel):
    deals_won: int
    deals_lost: int
    open_deals: int
    win_rate_pct: float | None
    avg_won_deal_cents: int | None
    avg_open_deal_cents: int | None
    avg_days_to_close: float | None
    total_pipeline_value_cents: int


class DayCount(BaseModel):
    day: str = Field(description="YYYY-MM-DD in the install timezone")
    count: int


class TypeCount(BaseModel):
    activity: str
    count: int


class ActivityStats(BaseModel):
    daily: list[DayCount]
    by_type: list[TypeCount]
    total: int


class AgeBucket(BaseModel):
    label: str
    min_days: int
    max_days: int | None
    count: int


class StaleDeal(BaseModel):
    id: int
    title: str
    value_cents: int
    stage: Stage
    person_name: str | None
    organization_name: str | None
    owner_user_id: int | None
    days_since_touch: int
    age_days: int


class Aging(BaseModel):
    buckets: list[AgeBucket]
    stale_count: int
    stale_deals: list[StaleDeal]


class RepStats(BaseModel):
    user_id: int | None
    name: str
    deals_open: int
    open_value_cents: int
    deals_won: int
    deals_lost: int
    won_value_cents: int
    activity_count: int
    records_touched: int


class Analytics(BaseModel):
    window_days: int
    stale_days: int
    timezone: str
    win_loss: WinLoss
    activity: ActivityStats
    aging: Aging
    per_rep: list[RepStats]


class StageDuration(BaseModel):
    stage: Stage
    samples: int = Field(description="Finished stays in the stage that started in the window")
    avg_days: float | None
    median_days: float | None


class StageConversion(BaseModel):
    stage: Stage
    entered: int = Field(description="Deals whose first entry into the stage is in the window")
    still_here: int
    advanced: int
    won: int
    lost: int
    progression_rate: float | None = Field(description="(advanced + won) / entered, 0-1")
    win_rate: float | None = Field(description="won / entered, 0-1")


class Velocity(BaseModel):
    won_in_window: int
    avg_days_to_won: float | None


class PipelineAnalytics(BaseModel):
    window_days: int
    history_since: str | None
    history_days: int | None
    history_covers_window: bool
    time_in_stage: list[StageDuration]
    conversion: list[StageConversion]
    velocity: Velocity


class StaleDeals(BaseModel):
    stale_days: int
    total_stale: int
    count: int
    deals: list[StaleDeal]


class DealHealth(BaseModel):
    deal: Deal
    score: int | None
    factors: dict[str, float]
    stale_days: int
    flags: list[str]


class DuplicateRecord(BaseModel):
    id: int
    label: str


class DuplicateGroup(BaseModel):
    match_on: str
    value: str
    count: int
    records: list[DuplicateRecord]


# ── Scores, touch counts, provenance ──────────────────────────────────────────


class PersonScore(BaseModel):
    person_id: int
    lead_score: int
    lead_score_at: str


class TouchEvent(BaseModel):
    source: Literal["note", "activity", "deal_notes", "stage_move"]
    source_id: int | None
    event_at: str = Field(description="Canonical instant; empty for the deal's own notes field")
    line: str = Field(description="The live evidence line")
    state: Literal["touch", "not_touch", "not_evaluated", "edited_since", "excluded_empty", "stage_move"]
    reason: str = Field(description="Why it is not a touch (not_touch, stage_move)")


class TouchEvidence(BaseModel):
    deal_id: int
    open: bool = Field(description="Live and open: only these are still counted")
    stage: Stage
    ai_touch_count: int | None
    computed_at: str | None
    verdict_state: Literal["none", "current", "stale", "superseded"]
    counted: int | None
    evaluated: int
    truncated: bool = Field(description="The deal has older evidence than the window shows")
    events: list[TouchEvent]


class BackfillStatus(BaseModel):
    pending: int = Field(description="Deals waiting for a touch count (dirty or never counted)")
    running: bool
    last_run_at: str | None
    configured: bool = Field(description="An AI provider is configured; without one the job skips")


class ScoresBackfillOut(BaseModel):
    deals: int
    people: int


class ProvenanceField(BaseModel):
    source: str
    populated_at: str
    value_snapshot: str | None


class Provenance(BaseModel):
    entity_type: str
    entity_id: int
    fields: dict[str, ProvenanceField] = Field(description="Only live, unconfirmed AI-written fields")


class ProvenanceConfirmIn(_In):
    fields: list[str] | None = Field(default=None, description="Default: every badged field")


# ── Stage criteria ────────────────────────────────────────────────────────────


class StageCriteria(BaseModel):
    stage: Stage
    summary: str
    checklist: list[str]
    is_default: bool
    updated_at: str | None


class StageCriteriaIn(_In):
    summary: str = Field(min_length=1, max_length=2000)
    checklist: list[str] = Field(max_length=30)


# ── Import ────────────────────────────────────────────────────────────────────


class ImportPerson(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(default="", max_length=320)
    phone: str = Field(default="", max_length=100)
    organization: str = Field(default="", max_length=200)
    title: str = Field(default="", max_length=200)
    source: str = Field(default="", max_length=100)
    notes: str = Field(default="", max_length=MAX_TEXT)
    tags: list[str] = Field(default_factory=list, max_length=50)


class ImportParsed(BaseModel):
    people: list[ImportPerson]
    method: Literal["csv", "vcf", "ai"]
    warnings: list[str]


class ImportConfirmIn(_In):
    people: list[ImportPerson] = Field(min_length=1, max_length=2000)


class ImportResult(BaseModel):
    created: int
    organizations_linked: int
    skipped: list[str] = Field(description="One line per row not imported, with the reason")
    person_ids: list[int]


# ── Organization report ───────────────────────────────────────────────────────


class OrganizationRollup(BaseModel):
    organization_id: int
    name: str
    people: list[dict] = Field(description="core person rows linked to the organization")
    deals: list[Deal]
    open_deals: int
    open_value_cents: int
    won_value_cents: int
    last_activity_at: str | None
    recent_activity: list[Activity]


# ── Settings and meta ─────────────────────────────────────────────────────────


class CrmSettings(BaseModel):
    stale_days: int
    touch_count_enabled: bool
    default_currency: str


class CrmSettingsPatch(_In):
    stale_days: int | None = Field(default=None, ge=1, le=365)
    touch_count_enabled: bool | None = None
    default_currency: str | None = Field(default=None, min_length=3, max_length=3)


class Meta(BaseModel):
    empty: bool = Field(description="No deals, activity, people or organizations yet")
    sample_data_loaded: bool
    onboarding_dismissed: bool


class ResetIn(_In):
    confirm: Literal["RESET"]


class ResetOut(BaseModel):
    deals: int
    activity: int
