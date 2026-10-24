"""Whisk's contacts tools: find, read, create and link people and organizations through the
published contacts API, as the acting user (the chat's or the MCP link's). Writes confirm (an
Approve card: they add directory records every member sees) and run through `handler_in` in the
approval transaction. Every record in a result carries `url`, the link that opens it."""

from backend.core import db, entities
from backend.core.agent.spec import ToolSpec
from backend.core.contacts import api as contacts
from backend.core.timeline.tools import human, url

PERSON, ORGANIZATION = "core.person", "core.organization"
LINKED = " Every record in the result carries a `url` that opens it: give it when you name one. Never build one yourself."
_ID = {"id": {"type": "integer"}}


def _brief(kind: str, rec: dict) -> dict:
    return {"kind": kind, "id": rec["id"], "name": rec["name"], **{k: rec[k] for k in ("email", "phone") if rec.get(k)},
            "url": url(PERSON if kind == "person" else ORGANIZATION, rec["id"])}  # fmt: skip


def _address(a: dict) -> str:
    region = " ".join(filter(None, (a["region"], a["postal_code"])))
    return ", ".join(filter(None, (a["line1"], a["line2"], a["city"], region, a["country"])))


def _shape(kind: str, rec: dict) -> dict:
    """The detail without empty fields, its links, channels and one-line addresses, and urls."""
    parts = {"organizations", "people", "channels", "addresses", "merged_into_id"}
    out = {"kind": kind, **{k: v for k, v in rec.items() if k not in parts and v not in (None, "", [])}}
    if kind == "person":
        out["organizations"] = [
            {"id": o["organization_id"], "name": o["name"], "role": o["role"], "is_primary": o["is_primary"],
             "url": url(ORGANIZATION, o["organization_id"])}
            for o in rec["organizations"]
        ]  # fmt: skip
    else:
        out["people"] = [
            {**_brief("person", {"id": p["person_id"], **p}), "title": p["title"], "role": p["role"], "is_primary": p["is_primary"]}
            for p in rec["people"]
        ]
    out["channels"] = [{k: c[k] for k in ("kind", "value", "label", "is_primary")} for c in rec["channels"]]
    out["addresses"] = [{"kind": a["kind"], "address": _address(a), "is_primary": a["is_primary"]} for a in rec["addresses"]]
    out["url"] = url(PERSON if kind == "person" else ORGANIZATION, rec["id"])
    return out


def _search(user, args: dict) -> list[dict]:
    conn, kind = db.get_conn(), args.get("kind") or "any"
    hits = contacts.search_in(conn, user, args.get("query") or "", None if kind == "any" else kind, int(args.get("limit") or 10))
    out = [_brief(h["kind"], h) for h in hits]
    for hit in out:
        if hit["kind"] == "person":
            hit["organizations"] = [
                {"id": o["organization_id"], "name": o["name"], "role": o["role"]}
                for o in contacts.organizations_for_in(conn, user, hit["id"]) if o["archived_at"] is None
            ]  # fmt: skip
    return out


def _get(kind: str):
    read = contacts.get_person_in if kind == "person" else contacts.get_organization_in

    def handler(user, args: dict) -> dict:
        conn, record_id = db.get_conn(), int(args["id"])
        rec = read(conn, user, record_id)
        if "merged_into" not in rec:
            return _shape(kind, rec)
        return {**_shape(kind, read(conn, user, rec["merged_into"])), "merged_from": record_id}

    return handler


def _same_name_in(conn, user, kind: str, name: str) -> list[dict]:
    """Live records of `kind` named `name`, ignoring case."""
    key = name.strip().casefold()
    hits = contacts.search_in(conn, user, name, kind, 50) if key else []
    return [_brief(kind, h) for h in hits if h["name"].strip().casefold() == key]


def _create_person(conn, user, args: dict) -> dict:
    if not args.get("allow_duplicate") and (same := _same_name_in(conn, user, "person", args.get("name") or "")):
        return {"created": False, "reason": "A person with this name already exists. Use that record, or pass "
                "allow_duplicate=true if this is someone else.", "existing": same}  # fmt: skip
    person = contacts.create_person_in(conn, user, **{k: args[k] for k in ("name", "email", "phone", "title") if args.get(k)})
    if args.get("organization_id"):
        contacts.link_in(conn, user, person["id"], int(args["organization_id"]), args.get("role") or "")
        person = contacts.get_person_in(conn, user, person["id"])
    return {"created": True, **_shape("person", person)}


def _create_organization(conn, user, args: dict) -> dict:
    if same := _same_name_in(conn, user, "organization", args.get("name") or ""):
        return {"created": False, "reason": "An organization with this name already exists.", "existing": same[0]}
    fields = {k: args[k] for k in ("name", "domain", "website", "industry") if args.get(k)}
    return {"created": True, **_shape("organization", contacts.create_organization_in(conn, user, **fields))}


def _link(conn, user, args: dict) -> dict:
    person_id, organization_id = int(args["person_id"]), int(args["organization_id"])
    link = contacts.link_in(conn, user, person_id, organization_id, args.get("role") or "", is_primary=bool(args.get("primary")))
    names = {t: entities.titles_for(user, conn, t, [i]).get(i) for t, i in ((PERSON, person_id), (ORGANIZATION, organization_id))}
    return {
        "role": link["role"], "is_primary": link["is_primary"],
        "person": {"id": person_id, "name": names[PERSON], "url": url(PERSON, person_id)},
        "organization": {"id": organization_id, "name": names[ORGANIZATION], "url": url(ORGANIZATION, organization_id)},
    }  # fmt: skip


def _read(name: str, description: str, handler, properties: dict, required: tuple) -> ToolSpec:
    return ToolSpec(
        name=name, description=description + LINKED, input_schema={"type": "object", "properties": properties, "required": list(required)},
        writes=False, handler=handler, enabled=human,
    )  # fmt: skip


def _write(name: str, description: str, handler_in, properties: dict, required: tuple, targets) -> ToolSpec:
    return ToolSpec(
        name=name, description=description + LINKED, input_schema={"type": "object", "properties": properties, "required": list(required)},
        writes=True, handler_in=handler_in, targets=targets, enabled=human,
    )  # fmt: skip


def get_tools() -> list[ToolSpec]:
    return [
        _read(
            "core_search_contacts",
            "Find people and organizations in the contacts directory by name, email, phone, job title or notes "
            "(every word must match one record, as a prefix; case and accents are ignored). People come with their "
            "organizations. To see who works at an organization, find it, then read it with core_get_organization.",
            _search,
            {"query": {"type": "string"}, "kind": {"type": "string", "enum": ["person", "organization", "any"]},
             "limit": {"type": "integer", "minimum": 1, "maximum": 50}},
            ("query",),
        ),  # fmt: skip
        _read("core_get_person", "One person: their details, organizations and roles, emails, phones and addresses.", _get("person"), _ID, ("id",)),
        _read(
            "core_get_organization", "One organization: its details, its people and their roles, emails, phones and addresses.",
            _get("organization"), _ID, ("id",),
        ),  # fmt: skip
        _write(
            "core_create_person",
            "Add a person to the contacts directory, optionally linked to an organization (by id) with a role. Search "
            "first: a person with the same name is not created twice unless allow_duplicate is true.",
            _create_person,
            {"name": {"type": "string"}, "email": {"type": "string"}, "phone": {"type": "string"},
             "title": {"type": "string", "description": "Job title"}, "organization_id": {"type": "integer"},
             "role": {"type": "string", "description": "Their role at the organization"},
             "allow_duplicate": {"type": "boolean", "description": "Create it even though a person has this name"}},
            ("name",),
            lambda args: [(ORGANIZATION, int(args["organization_id"]))] if args.get("organization_id") else [],
        ),  # fmt: skip
        _write(
            "core_create_organization",
            "Add an organization to the contacts directory. Names are unique: an existing one is returned instead.",
            _create_organization,
            {"name": {"type": "string"}, "domain": {"type": "string", "description": "e.g. example.com"},
             "website": {"type": "string"}, "industry": {"type": "string"}},
            ("name",), lambda args: [],
        ),  # fmt: skip
        _write(
            "core_link_person_organization",
            "Link a person to an organization with a role (e.g. owner, buyer). primary=true makes it the person's main "
            "organization; a person's first link is primary anyway.",
            _link,
            {"person_id": {"type": "integer"}, "organization_id": {"type": "integer"}, "role": {"type": "string"},
             "primary": {"type": "boolean"}},
            ("person_id", "organization_id"),
            lambda args: [(PERSON, int(args["person_id"])), (ORGANIZATION, int(args["organization_id"]))],
        ),  # fmt: skip
    ]
