import pytest

from backend.apps.example import service as widgets
from backend.apps.example.models import WidgetIn
from backend.core import db as core_db, entities
from backend.core.contacts import api as contacts, service
from backend.core.errors import Conflict, Invalid, NotFound
from backend.core.timeline import api as timeline


@pytest.fixture
def user(app, make_user):
    return make_user("member")


def _person(user, name, **fields) -> int:
    return contacts.create_person(user, name=name, **fields)["id"]


def _org(user, name) -> int:
    return contacts.create_organization(user, name=name)["id"]


def test_merge_people_by_every_collision_rule(user):
    acme, globex = _org(user, "Acme Example"), _org(user, "Globex Sample")
    target = _person(user, "Ada Example", email="ada@example.com")
    source = _person(user, "Ada E.", email="ADA@example.com", phone="555-0101")
    kept = contacts.link(user, target, acme, "Buyer")  # the target's primary
    contacts.link(user, source, acme, "Buyer")  # collides: the target's row is kept
    contacts.link(user, source, globex, "Owner", is_primary=True)  # a source primary: cleared, then moved
    service.add_part(user, "channel", "person", source, kind="email", value="ada@work.example.com")
    home = service.add_part(user, "address", "person", target, line1="1 Sample Street")
    service.add_part(user, "address", "person", source, line1="2 Example Road")

    merged = contacts.merge_people(user, target, source)

    assert merged["id"] == target and merged["name"] == "Ada Example"  # the survivor is the target
    assert [(o["name"], o["role"], o["is_primary"]) for o in merged["organizations"]] == [
        ("Acme Example", "Buyer", True), ("Globex Sample", "Owner", False),
    ]
    assert core_db.one("SELECT id FROM core_person_organizations WHERE organization_id = ? AND role = 'Buyer'", (acme,))["id"] == kept["id"]
    assert [(c["kind"], c["value"], c["is_primary"]) for c in merged["channels"]] == [
        ("email", "ada@example.com", True), ("email", "ada@work.example.com", False),  # same address in another case dropped
        ("phone", "555-0101", True),  # the target had no phone, so the source's primary stays primary
    ]
    assert (merged["email"], merged["phone"]) == ("ada@example.com", "555-0101")
    assert [(a["line1"], a["is_primary"]) for a in merged["addresses"]] == [("1 Sample Street", True), ("2 Example Road", False)]
    assert merged["addresses"][0]["id"] == home["id"]
    gone = core_db.one("SELECT merged_into_id, archived_at, email, phone FROM core_people WHERE id = ?", (source,))
    assert gone["merged_into_id"] == target and gone["archived_at"] and (gone["email"], gone["phone"]) == (None, None)
    assert contacts.get_person(user, source) == {"merged_into": target}
    assert contacts.organizations_for(user, source) == contacts.organizations_for(user, target)  # reads follow the alias


def test_a_target_without_primaries_takes_the_sources(user):
    org = _org(user, "Acme Example")
    target, source = _person(user, "Target"), _person(user, "Source", email="source@example.com")
    contacts.link(user, source, org, "Buyer")
    service.add_part(user, "address", "person", source, line1="1 Sample Street")
    merged = contacts.merge_people(user, target, source)
    assert [(o["role"], o["is_primary"]) for o in merged["organizations"]] == [("Buyer", True)]
    assert merged["email"] == "source@example.com" and merged["addresses"][0]["is_primary"] is True


def test_aliases_stay_flat_and_ids_resolve_to_the_chain_head(user):
    a, b, c = (_person(user, n) for n in ("A", "B", "C"))
    contacts.merge_people(user, b, a)
    contacts.merge_people(user, c, b)  # b -> c, and a is re-pointed at c
    heads = {r["id"]: r["merged_into_id"] for r in core_db.rows("SELECT id, merged_into_id FROM core_people")}
    assert heads == {a: c, b: c, c: None}
    assert contacts.resolve("person", a) == c and contacts.get_person(user, a) == {"merged_into": c}
    d = _person(user, "D")
    assert contacts.merge_people(user, a, d)["id"] == c  # a target given as an alias resolves to its head
    assert contacts.resolve("person", d) == c
    with pytest.raises(Invalid, match="itself"):
        contacts.merge_people(user, b, a)  # both resolve to c
    with pytest.raises(Invalid, match="itself"):
        contacts.merge_people(user, c, c)
    with pytest.raises(NotFound):
        contacts.merge_people(user, c, 9999)
    with pytest.raises(Conflict, match="merged into"):  # writes to a merged id are refused
        contacts.update_person(user, a, name="X")


def test_cycle_guard(user):
    a, b, c = _person(user, "A"), _person(user, "B"), _person(user, "C")
    with core_db.transaction() as conn:  # a corrupt chain, written by hand
        conn.execute("UPDATE core_people SET merged_into_id = ? WHERE id = ?", (b, a))
        conn.execute("UPDATE core_people SET merged_into_id = ? WHERE id = ?", (a, b))
    with pytest.raises(Conflict, match="loops"):
        contacts.resolve("person", a)
    with pytest.raises(Conflict, match="loops"):
        contacts.merge_people(user, c, a)


def test_merging_into_an_archived_record_is_refused(user):
    a, b = _person(user, "A"), _person(user, "B")
    service.archive(user, "person", a)
    with pytest.raises(Conflict, match="archived"):
        contacts.merge_people(user, a, b)
    assert contacts.merge_people(user, b, a)["id"] == b  # an archived source is fine


def test_merge_drives_subscribers_and_records_itself(user):
    target, source = _person(user, "Target"), _person(user, "Source")
    widget = widgets.create_widget(user, WidgetIn(name="Gear", person_id=source))
    timeline.add_note(user, "core.person", source, "met at the fair")
    contacts.merge_people(user, target, source)
    assert widgets.get_widget(user, widget["id"])["person_id"] == target  # the example app's subscriber
    entries = timeline.list_for(user, "core.person", target)
    assert [(e["kind"], e["body"], e["author"]["id"]) for e in entries] == [
        ("system", f"merged #{source} into this record", user.id), ("note", "met at the fair", user.id),
    ]
    log = core_db.rows("SELECT entity, entity_id, field, old, new, user_id FROM core_change_log WHERE field = 'merged_from'")
    assert log == [{"entity": "core.person", "entity_id": target, "field": "merged_from", "old": "null", "new": str(source), "user_id": user.id}]


def test_a_failing_subscriber_rolls_the_whole_merge_back(user, monkeypatch):
    org, target = _org(user, "Acme Example"), _person(user, "Target", email="t@example.com")
    source = _person(user, "Source", email="s@example.com")
    contacts.link(user, source, org, "Buyer")
    widgets.create_widget(user, WidgetIn(name="Gear", person_id=source))
    timeline.add_note(user, "core.person", source, "a note")

    def boom(conn, entity_type, target_id, source_id):
        raise RuntimeError("subscriber failed")

    monkeypatch.setitem(entities._SUBSCRIBERS, "on_entity_merged", [*entities._SUBSCRIBERS["on_entity_merged"], boom])
    tables = ("core_people", "core_person_organizations", "core_contact_channels", "core_timeline", "core_change_log", "example_widgets")
    before = [core_db.rows(f"SELECT * FROM {t} ORDER BY id") for t in tables]
    with pytest.raises(RuntimeError, match="subscriber failed"):
        contacts.merge_people(user, target, source)
    assert [core_db.rows(f"SELECT * FROM {t} ORDER BY id") for t in tables] == before


def test_merge_organizations_keeps_each_persons_primary(user):
    acme, acme_inc = _org(user, "Acme Example"), _org(user, "Acme Example Inc")
    ada, grace = _person(user, "Ada"), _person(user, "Grace")
    contacts.link(user, ada, acme_inc, "Buyer")  # moves, still Ada's primary
    contacts.link(user, grace, acme, "Owner")
    contacts.link(user, grace, acme_inc, "Owner", is_primary=True)  # collides with the kept row; was Grace's primary
    merged = contacts.merge_organizations(user, acme, acme_inc)
    assert [(p["name"], p["role"], p["is_primary"]) for p in merged["people"]] == [("Ada", "Buyer", True), ("Grace", "Owner", True)]
    assert contacts.get_organization(user, acme_inc) == {"merged_into": acme}
    assert contacts.create_organization(user, name="Acme Example Inc")["id"] > acme_inc  # a merged name is free again
