"""Whisk tools. The acting user is the chat's or the MCP link's user, so every tool sees and
changes exactly what that person could in the app. Ported in part from CakeCRM's crm/tools.py
(docs/PROVENANCE.md); todo, reminder and GTD tools are the Todos app's and core's now.
Writes record field provenance so the deal sheet shows an AI badge until a person confirms."""

from backend.apps.crm import deals, provenance
from backend.apps.crm.common import ENTITY, STAGES
from backend.apps.crm.models import DealIn, DealPatch
from backend.core.agent.spec import ROUTINE, ToolSpec

_ID = {"deal_id": {"type": "integer", "description": "The deal's id"}}


def _schema(model, **extra) -> dict:
    schema = model.model_json_schema()
    return {
        "type": "object",
        "properties": {**extra, **schema["properties"]},
        "required": [*extra, *schema.get("required", [])],
        **({"$defs": schema["$defs"]} if "$defs" in schema else {}),
    }


def _create(conn, user, args: dict) -> dict:
    deal = deals.create_in(conn, user, args)
    provenance.record_fields_in(conn, ENTITY, deal["id"], set(args) - {"title"})
    return deal


def _update(conn, user, args: dict) -> dict:
    fields = {k: v for k, v in args.items() if k != "deal_id"}
    deal = deals.update_in(conn, user, int(args["deal_id"]), fields)
    provenance.record_fields_in(conn, ENTITY, deal["id"], fields)
    return deal


def _the_deal(args: dict) -> list[tuple[str, int]]:
    return [(ENTITY, int(args["deal_id"]))]


def get_tools() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="crm_search_deals",
            description=(
                "Search live deals by words in their title, notes, person or organization (prefix, case- and "
                "accent-insensitive), and/or filter by stage, person_id, organization_id or owner_user_id. Money is in cents."
            ),
            input_schema={"type": "object", "properties": {
                "q": {"type": "string"}, "stage": {"type": "string", "enum": list(STAGES)},
                "person_id": {"type": "integer"}, "organization_id": {"type": "integer"}, "owner_user_id": {"type": "integer"},
                "include_archived": {"type": "boolean"}, "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            }},  # fmt: skip
            writes=False,
            handler=lambda user, args: deals.search(user, **args),
        ),
        ToolSpec(
            name="crm_get_deal",
            description="One deal with its recent activity and stage history.",
            input_schema={"type": "object", "properties": _ID, "required": ["deal_id"]},
            writes=False,
            handler=lambda user, args: deals.detail(user, int(args["deal_id"])),
        ),
        ToolSpec(
            name="crm_get_pipeline",
            description="The pipeline board: the newest deals per stage (at most limit_per_stage each) and open totals per stage.",
            input_schema={"type": "object", "properties": {"limit_per_stage": {"type": "integer", "minimum": 1, "maximum": 50}}},
            writes=False,
            handler=lambda user, args: deals.board(user, limit_per_stage=int(args.get("limit_per_stage") or 10)),
        ),
        ToolSpec(
            name="crm_create_deal",
            description=(
                "Create a deal. value_cents is money in cents ($1,250.00 is 125000). Link it to a person and/or "
                "organization by id (find them with the contacts tools first)."
            ),
            input_schema=_schema(DealIn),
            writes=True,
            confirm_tier=ROUTINE,
            handler_in=_create,
            targets=lambda args: [],  # touches no existing record; links are checked for read access
        ),
        ToolSpec(
            name="crm_update_deal",
            description=(
                "Change a deal: only the fields given change. Moving it to won settles probability at 100 and records "
                "closed_on (default today); to lost, probability 0. An archived deal must be restored before its stage changes."
            ),
            input_schema=_schema(DealPatch, **_ID),
            writes=True,
            confirm_tier=ROUTINE,
            handler_in=_update,
            targets=_the_deal,
        ),
    ]
