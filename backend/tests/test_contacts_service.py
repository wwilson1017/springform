import pytest

from backend.core import db as core_db, preview
from backend.core.auth.deps import system_user
from backend.core.contacts import api as contacts, seed, service, startup
from backend.core.db import sqlite3
from backend.core.errors import Conflict, Forbidden, Invalid, NotFound
from backend.core.timeline import api as timeline


@pytest.fixture
def user(app, make_user):
    return make_user("member")


def _links(user, person_id):
    return [(o["name"], o["role"], o["is_primary"]) for o in contacts.organizations_for(user, person_id)]


def test_person_with_two_organizations_keeps_one_primary(user):
    acme = contacts.create_organization(user, name="Acme Example")["id"]
    globex = contacts.create_organization(user, name="Globex Sample")["id"]
    ada = contacts.create_person(user, given_name="Ada", family_name="Example")
    assert ada["name"] == "Ada Example"
    contacts.link(user, ada["id"], acme, "Buyer")  # a first link is primary
    contacts.link(user, ada["id"], acme, "Owner")  # same organization, second role
    contacts.link(user, ada["id"], globex, "Advisor")
    assert _links(user, ada["id"]) == [("Acme Example", "Buyer", True), ("Acme Example", "Owner", False), ("Globex Sample", "Advisor", False)]
    contacts.link(user, ada["id"], globex, "Advisor", is_primary=True)  # idempotent; promoting demotes the old primary
    assert _links(user, ada["id"]) == [("Globex Sample", "Advisor", True), ("Acme Example", "Buyer", False), ("Acme Example", "Owner", False)]
    assert [(p["name"], p["role"]) for p in contacts.people_for(user, acme)] == [("Ada Example", "Buyer"), ("Ada Example", "Owner")]
    with pytest.raises(sqlite3.IntegrityError), core_db.transaction() as conn:  # the index refuses two primaries
        conn.execute("UPDATE core_person_organizations SET is_primary = 1 WHERE person_id = ?", (ada["id"],))

    contacts.unlink(user, ada["id"], globex, "Advisor")  # removing the primary promotes the oldest remaining link
    assert _links(user, ada["id"])[0] == ("Acme Example", "Buyer", True)
    with pytest.raises(NotFound):
        contacts.unlink(user, ada["id"], globex, "Advisor")
    link = service.update_link(user, ada["id"], acme, "Owner", new_role="Partner", is_primary=True, started_on="2026-01-02")
    assert (link["role"], link["is_primary"], link["started_on"]) == ("Partner", True, "2026-01-02")
    assert _links(user, ada["id"]) == [("Acme Example", "Partner", True), ("Acme Example", "Buyer", False)]
    with pytest.raises(Conflict):
        service.update_link(user, ada["id"], acme, "Partner", new_role="Buyer")


def test_channel_changes_rewrite_the_email_and_phone_mirror(user):
    p = contacts.create_person(user, name="Grace Sample", email="grace@example.com", phone="555-0100")
    assert (p["email"], p["phone"]) == ("grace@example.com", "555-0100")
    work = service.add_part(user, "channel", "person", p["id"], kind="email", value="grace@work.example.com")
    assert work["is_primary"] is False and contacts.get_person(user, p["id"])["email"] == "grace@example.com"
    service.update_part(user, "channel", work["id"], is_primary=True)
    assert contacts.get_person(user, p["id"])["email"] == "grace@work.example.com"
    service.delete_part(user, "channel", work["id"])  # deleting the primary promotes the next oldest
    assert contacts.get_person(user, p["id"])["email"] == "grace@example.com"

    contacts.update_person(user, p["id"], email="grace@new.example.com", phone="")
    got = contacts.get_person(user, p["id"])
    assert (got["email"], got["phone"]) == ("grace@new.example.com", None)
    assert [(c["kind"], c["value"], c["is_primary"]) for c in got["channels"]] == [("email", "grace@new.example.com", True)]
    service.update_part(user, "channel", got["channels"][0]["id"], kind="url")  # moved out of the email slot
    assert contacts.get_person(user, p["id"])["email"] is None
    changed = [c["field"] for e in timeline.list_for(user, "core.person", p["id"]) for c in e["changes"] or []]
    assert changed.count("email") == 4 and "phone" in changed  # mirror changes reach the timeline

    org = contacts.create_organization(user, name="Acme Example", phone="555-0199")
    assert org["phone"] == "555-0199" and org["channels"][0]["is_primary"] is True


def test_search_folds_case_and_accents_and_skips_merged_and_archived(user):
    zoe = contacts.create_person(user, name="Zoë Ámbar", email="zoe@example.com")["id"]
    cafe = contacts.create_organization(user, name="Café Ñandú", domain="cafe.example.com")["id"]
    archived = contacts.create_person(user, name="Zoe Ambar Archived")["id"]
    service.archive(user, "person", archived)
    alias = contacts.create_person(user, name="Zoe Ambar Alias")["id"]
    contacts.merge_people(user, zoe, alias)
    assert [(h["kind"], h["id"]) for h in contacts.search(user, "ZOE ambar")] == [("person", zoe)]
    assert [h["id"] for h in contacts.search(user, "cafe nandu", kind="organization")] == [cafe]
    assert [h["id"] for h in contacts.search(user, "zoe@example")] == [zoe]  # email tokens
    assert contacts.search(user, "zo", kind="organization") == []
    assert contacts.search(user, '"; DROP TABLE core_people') == []  # quoted terms, never FTS syntax
    assert contacts.search(user, "  ") == []
    assert [p["id"] for p in service.list_records(user, "person", q="ámbar")["items"]] == [zoe]


def test_find_duplicates_by_email_phone_and_name(user):
    a = contacts.create_person(user, name="Ada Example", email="ADA@example.com ", phone="(555) 010-0101")["id"]
    b = contacts.create_person(user, name="ada example ", email="ada@example.com")["id"]
    c = contacts.create_person(user, name="Someone Else", phone="555.010.0101")["id"]
    gone = contacts.create_person(user, name="Ada Example", email="ada@example.com")["id"]
    service.archive(user, "person", gone)  # archived records are not duplicates
    groups = contacts.find_duplicates(user, "person")
    assert [(g["match_on"], g["value"], g["count"], [r["id"] for r in g["records"]]) for g in groups] == [
        ("email", "ada@example.com", 2, [a, b]), ("phone", "5550100101", 2, [a, c]), ("name", "ada example", 2, [a, b]),
    ]
    assert groups[0]["records"][1] == {"id": b, "label": "ada example"}
    contacts.create_organization(user, name="Acme Example", domain="acme.example.com")
    contacts.create_organization(user, name="Acme Holdings", domain="ACME.example.com")
    assert [(g["match_on"], g["value"], g["count"]) for g in contacts.find_duplicates(user, "organization")] == [
        ("domain", "acme.example.com", 2)
    ]


def test_resolve_or_create_organizations(user):
    acme = contacts.create_organization(user, name="Acme Example")["id"]
    got = contacts.resolve_or_create_organizations(user, ["acme example", "  ACME EXAMPLE ", "Globex Sample", "", "Globex Sample"])
    assert got["acme example"] == got["  ACME EXAMPLE "] == acme and "" not in got
    assert contacts.get_organization(user, got["Globex Sample"])["name"] == "Globex Sample"
    assert core_db.one("SELECT count(*) AS n FROM core_organizations")["n"] == 2
    with pytest.raises(Conflict):
        contacts.create_organization(user, name=" ACME example")
    with pytest.raises(Conflict):
        contacts.update_organization(user, got["Globex Sample"], name="Acme EXAMPLE")
    old = contacts.create_organization(user, name="Acme Old Name")["id"]
    contacts.merge_organizations(user, acme, old)
    assert contacts.resolve_or_create_organizations(user, ["acme old name"]) == {"acme old name": acme}  # alias -> survivor


def test_names_match_beyond_ascii(user):
    """SQL lower() folds only ASCII, so "Café Ñandú" and "café ñandú" are compared in Python."""
    cafe = contacts.create_organization(user, name="Café Ñandú")["id"]
    with pytest.raises(Conflict):
        contacts.create_organization(user, name="café ñandú")
    with pytest.raises(Conflict):
        contacts.update_organization(user, contacts.create_organization(user, name="Other")["id"], name="CAFÉ ÑANDÚ")
    assert contacts.resolve_or_create_organizations(user, ["CAFÉ ñandú"]) == {"CAFÉ ñandú": cafe}
    a = contacts.create_person(user, name="Zoë Démo")["id"]
    b = contacts.create_person(user, name="ZOË DÉMO")["id"]
    assert [(g["match_on"], g["value"], [r["id"] for r in g["records"]]) for g in contacts.find_duplicates(user, "person")] == [
        ("name", "zoë démo", [a, b])
    ]


def test_validation_and_the_system_principal(user):
    with pytest.raises(Invalid, match="name is required"):
        contacts.create_person(user, name="  ")
    with pytest.raises(Invalid, match="unknown"):
        contacts.create_person(user, name="X", nickname="Y")
    with pytest.raises(Invalid, match="owner_user_id"):
        contacts.create_person(user, name="X", owner_user_id=0)
    p = contacts.create_person(user, name="X", tags=[" vip ", "vip", "", "wholesale"], owner_user_id=user.id)
    assert p["tags"] == ["vip", "wholesale"] and p["owner_user_id"] == user.id
    with pytest.raises(Invalid, match="kind"):
        service.add_part(user, "channel", "person", p["id"], kind="fax", value="1")
    with pytest.raises(Invalid, match="value"):
        service.add_part(user, "channel", "person", p["id"], kind="email", value=" ")
    with pytest.raises(NotFound):
        service.add_part(user, "address", "person", 9999, line1="1 Sample Street")
    system = system_user()  # jobs read like a member and never write
    assert contacts.get_person(system, p["id"])["name"] == "X"
    with pytest.raises(Forbidden):
        contacts.update_person(system, p["id"], name="Y")
    with pytest.raises(Forbidden):
        contacts.create_person(system, name="Z")


def test_preview_sample_seeds_once(app, monkeypatch):
    monkeypatch.setenv("PREVIEW_MODE", "1")
    preview.seed()  # the preview accounts
    startup.on_startup()
    startup.on_startup()
    assert core_db.one("SELECT count(*) AS n FROM core_people")["n"] == len(seed.PEOPLE)
    assert core_db.one("SELECT count(*) AS n FROM core_organizations")["n"] == len(seed.ORGANIZATIONS)
    assert {g["match_on"] for g in contacts.find_duplicates(system_user(), "person")} == {"email", "name"}
