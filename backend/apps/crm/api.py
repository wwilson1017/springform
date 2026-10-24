"""Published functions: the only module other apps may import (`from backend.apps.crm.api import …`).
Each has an `_in(conn, …)` form for callers already in a transaction. `user` is the acting
`User`; every call authorizes. Results are Deal dicts (models.Deal). Errors: NotFound (404),
Forbidden (403), Invalid (422), Conflict (409)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.apps.crm import deals
from backend.core import db

if TYPE_CHECKING:
    from backend.core.auth.deps import User


def get_deal_in(conn: db.Conn, user: User, deal_id: int) -> dict:
    return deals.get_in(conn, user, deal_id)


def get_deal(user: User, deal_id: int) -> dict:
    return get_deal_in(db.get_conn(), user, deal_id)


def deals_for_person_in(conn: db.Conn, user: User, person_id: int, include_archived: bool = False) -> list[dict]:
    """The person's deals, open first. NotFound when the person is not readable."""
    return deals.for_record_in(conn, user, "core.person", person_id, include_archived)


def deals_for_person(user: User, person_id: int, include_archived: bool = False) -> list[dict]:
    return deals_for_person_in(db.get_conn(), user, person_id, include_archived)


def deals_for_organization_in(conn: db.Conn, user: User, organization_id: int, include_archived: bool = False) -> list[dict]:
    return deals.for_record_in(conn, user, "core.organization", organization_id, include_archived)


def deals_for_organization(user: User, organization_id: int, include_archived: bool = False) -> list[dict]:
    return deals_for_organization_in(db.get_conn(), user, organization_id, include_archived)


def create_deal_in(conn: db.Conn, user: User, title: str, **fields) -> dict:
    """Fields as POST /api/crm/deals: stage, value_cents, currency, probability, expected_close,
    closed_on, notes, person_id, organization_id, owner_user_id, deal_temperature."""
    return deals.create_in(conn, user, {"title": title, **fields})


def create_deal(user: User, title: str, **fields) -> dict:
    with db.transaction() as conn:
        return create_deal_in(conn, user, title, **fields)
