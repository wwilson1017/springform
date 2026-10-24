"""Whisk tools. The acting user is the chat's or the MCP link's user, so every tool sees and
changes exactly what that person could in the app. Ported from CakeCRM's crm/tools.py
(docs/PROVENANCE.md); contact, company, note, custom-field and todo tools are core's and the
Todos app's now.

Writes are routine (no Approve card) except archiving and merging, which take a deal out of
view. Every deal in a result carries `url`, a link that opens it. AI-written deal fields are
recorded as provenance, so the deal shows an AI badge until a person confirms or edits them.
"""

from __future__ import annotations

from backend.apps.crm import activity, analytics, dashboard, deals, provenance, scoring
from backend.apps.crm.common import BULK_MOVE_MAX, ENTITY, OPEN_STAGES, STAGES
from backend.apps.crm.models import DealIn, DealPatch
from backend.core import db, entities, settings
from backend.core.agent.spec import ROUTINE, ToolSpec
from backend.core.errors import Invalid

URL_GUIDANCE = (
    " Every deal in the result carries a `url` that opens it in the CRM: give it when you name a specific deal. "
    "Never build one yourself."
)
_SEARCH_ARGS = {"q", "stage", "person_id", "organization_id", "owner_user_id", "sort_by", "sort_dir", "include_archived", "limit"}
_DEAL_ID = {"deal_id": {"type": "integer", "description": "The deal's id"}}
_CLOSED_ON = {"type": "string", "description": "The day it closed, YYYY-MM-DD. Default today; past days are fine; a future day is refused."}


def _link(value):
    """Add `url` to every deal (a dict with id, title and stage) in a result."""
    if isinstance(value, list):
        return [_link(v) for v in value]
    if isinstance(value, dict):
        out = {k: _link(v) for k, v in value.items()}
        if {"id", "title", "stage"} <= out.keys():
            out["url"] = settings.public_url() + entities.url_for(ENTITY, out["id"])
        return out
    return value


def _schema(model, **extra) -> dict:
    schema = model.model_json_schema()
    return {
        "type": "object", "properties": {**extra, **schema["properties"]}, "required": [*extra, *schema.get("required", [])],
        **({"$defs": schema["$defs"]} if "$defs" in schema else {}),
    }  # fmt: skip


def _deal(args: dict) -> list[tuple[str, int]]:
    return [(ENTITY, int(args["deal_id"]))]


def _open_stage(args: dict) -> str:
    if args.get("stage") not in OPEN_STAGES:
        raise Invalid(f"stage must be an open stage ({', '.join(OPEN_STAGES)}); close a deal with crm_mark_deal_won or crm_mark_deal_lost")
    return args["stage"]


def _create(conn, user, args: dict) -> dict:
    deal = deals.create_in(conn, user, args)
    provenance.record_fields_in(conn, ENTITY, deal["id"], set(args) - {"title"})
    return _link(deal)


def _update(conn, user, args: dict) -> dict:
    fields = {k: v for k, v in args.items() if k != "deal_id"}
    deal = deals.update_in(conn, user, int(args["deal_id"]), fields)
    provenance.record_fields_in(conn, ENTITY, deal["id"], fields)
    return _link(deal)


def _move(conn, user, args: dict) -> dict:
    deal = deals.update_in(conn, user, int(args["deal_id"]), {"stage": _open_stage(args)})
    provenance.record_fields_in(conn, ENTITY, deal["id"], ["stage"])
    return _link(deal)


def _bulk(conn, user, args: dict) -> dict:
    out = deals.bulk_move_in(conn, user, [int(i) for i in args["deal_ids"]], _open_stage(args))
    for deal_id in out["updated_ids"]:
        provenance.record_fields_in(conn, ENTITY, deal_id, ["stage"])
    return out


def _won(conn, user, args: dict) -> dict:
    deal = deals.mark_won_in(conn, user, int(args["deal_id"]), args.get("closed_on"))
    provenance.record_fields_in(conn, ENTITY, deal["id"], ["stage", "closed_on"])
    return _link(deal)


def _lost(conn, user, args: dict) -> dict:
    deal = deals.mark_lost_in(conn, user, int(args["deal_id"]), args.get("lost_reason") or "")
    provenance.record_fields_in(conn, ENTITY, deal["id"], ["stage", "lost_reason"])
    return _link(deal)


def _log(conn, user, args: dict) -> dict:
    return activity.log_in(conn, user, args["activity"], args.get("note") or "", deal_id=args.get("deal_id"), person_id=args.get("person_id"))


def _search(user, args: dict) -> list[dict]:
    """`mine` stands for the user's own id, which the model is never told."""
    filters = {k: v for k, v in args.items() if k in _SEARCH_ARGS}
    if args.get("mine"):
        filters["owner_user_id"] = user.id
    return deals.search(user, **filters)


def _analytics(user, args: dict) -> dict:
    """The lean shape: scalars and short lists, never the day-by-day series."""
    full = analytics.analytics(user, int(args.get("days") or 30), args.get("stale_days"))
    wl, act, aging = full["win_loss"], full["activity"], full["aging"]
    return _link({
        **{k: full[k] for k in ("window_days", "stale_days", "timezone")}, **wl,
        "activity_total": act["total"], "activity_by_type": act["by_type"][:10],
        "aging_buckets": {b["label"]: b["count"] for b in aging["buckets"]}, "stale_count": aging["stale_count"],
        "stale_deals": [{"id": d["id"], "title": d["title"], "stage": d["stage"], "days_since_touch": d["days_since_touch"]} for d in aging["stale_deals"][:5]],
        "per_rep": full["per_rep"],
    })  # fmt: skip


def _score(user, args: dict) -> dict:
    if args.get("deal_id"):
        deal = deals.get(user, int(args["deal_id"]))
        return {"deal_id": deal["id"], **scoring.deal_breakdown_in(db.get_conn(), deal["id"])}
    if args.get("person_id"):
        entities.authorize(user, db.get_conn(), "core.person", int(args["person_id"]), "read")
        stored = scoring.person_scores([int(args["person_id"])])
        return stored[0] if stored else {"person_id": int(args["person_id"]), "lead_score": None}
    raise Invalid("give deal_id or person_id")


def _read(name: str, description: str, handler, properties: dict | None = None, required: tuple = (), links: bool = True) -> ToolSpec:
    return ToolSpec(
        name=name, description=description + (URL_GUIDANCE if links else ""),
        input_schema={"type": "object", "properties": properties or {}, "required": list(required)},
        writes=False, handler=(lambda user, args: _link(handler(user, args))) if links else handler,
    )  # fmt: skip


def _write(name: str, description: str, handler_in, properties: dict, required: tuple, targets, *, routine: bool = True) -> ToolSpec:
    return ToolSpec(
        name=name, description=description, input_schema={"type": "object", "properties": properties, "required": list(required)},
        writes=True, confirm_tier=ROUTINE if routine else None, handler_in=handler_in, targets=targets,
    )  # fmt: skip


def get_tools() -> list[ToolSpec]:
    return [
        _read(
            "crm_search_deals",
            "Search live deals by words in their title, notes, person or organization (prefix, case- and accent-insensitive), "
            "and/or filter by stage, person_id, organization_id or owner_user_id; mine=true for the user's own deals. "
            "Money is in cents ($1,250.00 is 125000).",
            _search,
            {"q": {"type": "string"}, "stage": {"type": "string", "enum": list(STAGES)}, "person_id": {"type": "integer"},
             "organization_id": {"type": "integer"}, "owner_user_id": {"type": "integer"},
             "mine": {"type": "boolean", "description": "Only deals the user owns"},
             "sort_by": {"type": "string", "enum": sorted(deals.SORTS)}, "sort_dir": {"type": "string", "enum": ["asc", "desc"]},
             "include_archived": {"type": "boolean", "description": "Also archived deals: the way back to one archived by mistake"},
             "limit": {"type": "integer", "minimum": 1, "maximum": 100}},
        ),  # fmt: skip
        _read("crm_get_deal", "One deal with its recent activity and stage history.", lambda user, args: deals.detail(user, int(args["deal_id"])), _DEAL_ID, ("deal_id",)),
        _read(
            "crm_get_pipeline", "The pipeline: the newest deals in each stage (at most limit_per_stage) and the open count and value per stage.",
            lambda user, args: deals.board(user, limit_per_stage=int(args.get("limit_per_stage") or 10)),
            {"limit_per_stage": {"type": "integer", "minimum": 1, "maximum": 50}},
        ),
        _read(
            "crm_get_activity_log", "Logged calls, emails and meetings, newest first, optionally one deal's or one person's.",
            lambda user, args: activity.list_(user, deal_id=args.get("deal_id"), person_id=args.get("person_id"), limit=args.get("limit") or 20),
            {**_DEAL_ID, "person_id": {"type": "integer"}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, links=False,
        ),  # fmt: skip
        _read("crm_dashboard", "The CRM's headline numbers, pipeline by stage, top deals and latest activity.", lambda user, args: dashboard.dashboard(user)),
        _read("crm_today", "What needs the user today: their hot deals that have gone quiet, their reminders due today, then the other hot deals.", lambda user, args: dashboard.today(user)),
        _read(
            "crm_analytics",
            "Outcomes over a window of days: wins, losses, win rate, deal sizes in cents, days to close, activity volume and types, "
            "deal aging, stale deals and per-person numbers.",
            _analytics, {"days": {"type": "integer", "minimum": 7, "maximum": 365}, "stale_days": {"type": "integer", "minimum": 1, "maximum": 365}},
        ),  # fmt: skip
        _read(
            "crm_get_pipeline_analytics",
            "Movement through the funnel from the stage history: time in each stage, conversion from each stage, how long wins took. "
            "The history starts when the CRM was installed: when history_covers_window is false, say how far back it goes.",
            lambda user, args: analytics.pipeline_analytics(user, int(args.get("days") or 90)), {"days": {"type": "integer", "minimum": 7, "maximum": 730}}, links=False,
        ),  # fmt: skip
        _read(
            "crm_get_deal_health", "A deal's lead score with its factors, and the flags to act on: stale, stuck_in_stage, no_next_step, overdue_todo, missing_person, missing_organization.",
            lambda user, args: analytics.deal_health(user, int(args["deal_id"])), _DEAL_ID, ("deal_id",),
        ),  # fmt: skip
        _read(
            "crm_get_stale_deals", "Live open deals nothing has happened on for `days` (default the install's staleness window), quietest first.",
            lambda user, args: analytics.stale_deals(user, args.get("days"), int(args.get("limit") or 25)),
            {"days": {"type": "integer", "minimum": 1, "maximum": 365}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}},
        ),  # fmt: skip
        _read("crm_find_duplicate_deals", "Live deals that share a title and a person: likely double entries to merge.", lambda user, args: analytics.duplicates(user)),
        _read(
            "crm_get_lead_score", "The 0-100 lead score of a deal (with its factors) or a person. Plain arithmetic, no AI.",
            _score, {**_DEAL_ID, "person_id": {"type": "integer"}}, links=False,
        ),  # fmt: skip
        _write(
            "crm_create_deal",
            "Create a deal. value_cents is money in cents ($1,250.00 is 125000). Link it to a person and/or organization by id "
            "(find them with core_search_contacts first; add a missing one with core_create_person or core_create_organization)." + URL_GUIDANCE,
            _create, _schema(DealIn)["properties"], ("title",), lambda args: [],  # links are checked for read access
        ),  # fmt: skip
        _write(
            "crm_update_deal",
            "Change a deal: only the fields given change, and null clears one. Moving it to won settles probability at 100 and records "
            "closed_on (default today); to lost, probability 0. Prefer crm_mark_deal_won and crm_mark_deal_lost for closing." + URL_GUIDANCE,
            _update, _schema(DealPatch, **_DEAL_ID)["properties"], ("deal_id",), _deal,
        ),  # fmt: skip
        _write(
            "crm_update_deal_stage", f"Move a deal between open stages ({', '.join(OPEN_STAGES)}). To close one use crm_mark_deal_won or crm_mark_deal_lost." + URL_GUIDANCE,
            _move, {**_DEAL_ID, "stage": {"type": "string", "enum": list(OPEN_STAGES)}}, ("deal_id", "stage"), _deal,
        ),  # fmt: skip
        _write(
            "crm_bulk_move_deals", f"Move several deals to one open stage in one call (at most {BULK_MOVE_MAX}). A deal that cannot move is listed in errors; the rest move.",
            _bulk, {"deal_ids": {"type": "array", "items": {"type": "integer"}, "maxItems": BULK_MOVE_MAX}, "stage": {"type": "string", "enum": list(OPEN_STAGES)}},
            ("deal_ids", "stage"), lambda args: [(ENTITY, int(i)) for i in args.get("deal_ids") or []],
        ),  # fmt: skip
        _write(
            "crm_mark_deal_won", "Close a deal as won: stage won, probability 100, and the day it closed. On a deal already won, a closed_on corrects its day." + URL_GUIDANCE,
            _won, {**_DEAL_ID, "closed_on": _CLOSED_ON}, ("deal_id",), _deal,
        ),  # fmt: skip
        _write(
            "crm_mark_deal_lost", "Close a deal as lost: stage lost, probability 0, and the reason. Always ask for the reason: it is what makes lost deals worth reviewing." + URL_GUIDANCE,
            _lost, {**_DEAL_ID, "lost_reason": {"type": "string", "description": "Why: price, timing, chose a competitor, no budget…"}}, ("deal_id",), _deal,
        ),  # fmt: skip
        _write(
            "crm_archive_deal",
            "Archive a deal: it leaves every list, board and total but is never deleted. Only for duplicates, test records and mistakes; "
            "a deal that really closed is won or lost instead. A reason is required: ask for it." + URL_GUIDANCE,
            lambda conn, user, args: _link(deals.archive_in(conn, user, int(args["deal_id"]), args.get("reason") or "")),
            {**_DEAL_ID, "reason": {"type": "string"}}, ("deal_id", "reason"), _deal, routine=False,
        ),  # fmt: skip
        _write(
            "crm_restore_deal", "Bring an archived deal back to the board." + URL_GUIDANCE,
            lambda conn, user, args: _link(deals.restore_in(conn, user, int(args["deal_id"]))), _DEAL_ID, ("deal_id",), _deal,
        ),  # fmt: skip
        _write(
            "crm_merge_deals",
            "Fold a duplicate deal (source) into the deal to keep (target): its notes, files, activity, reminders and to-dos move to the "
            "target, its custom fields fill only the target's blanks, and the source is archived. The target's own fields do not change." + URL_GUIDANCE,
            lambda conn, user, args: _link(deals.merge_in(conn, user, int(args["target_id"]), int(args["source_id"]))),
            {"target_id": {"type": "integer"}, "source_id": {"type": "integer"}}, ("target_id", "source_id"),
            lambda args: [(ENTITY, int(args["target_id"])), (ENTITY, int(args["source_id"]))], routine=False,
        ),  # fmt: skip
        _write(
            "crm_log_activity", "Log a call, email, meeting or other interaction that happened, on a deal and/or a person, credited to the user.",
            _log, {"activity": {"type": "string", "description": "call, email, meeting, …"}, "note": {"type": "string"}, **_DEAL_ID, "person_id": {"type": "integer"}},
            ("activity",), lambda args: [(ENTITY, int(args["deal_id"]))] if args.get("deal_id") else [],
        ),  # fmt: skip
    ]
