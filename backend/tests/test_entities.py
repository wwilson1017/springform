import pytest

from backend.apps.example import service
from backend.apps.example.models import WidgetIn, WidgetPatch
from backend.core import clock, db as core_db, entities
from backend.core.auth.deps import system_user
from backend.core.errors import Forbidden, NotFound
from backend.core.timeline import api as timeline


def _person(name: str = "Ada") -> int:
    now = clock.now_iso()
    with core_db.transaction() as conn:
        return conn.execute(
            "INSERT INTO core_people (name, created_at, updated_at) VALUES (?, ?, ?)", (name, now, now)
        ).lastrowid


def test_authorize_404_for_missing_or_unreadable_403_for_unwritable(app, make_user):
    owner, other = make_user("member"), make_user("member")
    public = service.create_widget(owner, WidgetIn(name="Public"))
    private = service.create_widget(owner, WidgetIn(name="Private", is_private=True))
    conn = core_db.get_conn()
    assert entities.authorize(owner, conn, "example.widget", private["id"], "write").type == "example.widget"
    with pytest.raises(NotFound):
        entities.authorize(other, conn, "example.widget", 999, "read")
    with pytest.raises(NotFound):
        entities.authorize(other, conn, "nope.thing", public["id"], "read")
    with pytest.raises(NotFound):
        entities.authorize(other, conn, "example.widget", private["id"], "read")
    with pytest.raises(NotFound):  # unreadable stays invisible even when asking to write
        entities.authorize(other, conn, "example.widget", private["id"], "write")
    entities.authorize(other, conn, "example.widget", public["id"], "read")
    with pytest.raises(Forbidden):
        entities.authorize(other, conn, "example.widget", public["id"], "write")


def test_system_principal_reads_like_a_member_and_never_writes(app, make_user):
    owner = make_user("member")
    widget = service.create_widget(owner, WidgetIn(name="Gear"))
    secret = service.create_widget(owner, WidgetIn(name="Secret", is_private=True))
    system, conn = system_user(), core_db.get_conn()
    entities.authorize(system, conn, "example.widget", widget["id"], "read")
    with pytest.raises(NotFound):
        entities.authorize(system, conn, "example.widget", secret["id"], "read")
    with pytest.raises(Forbidden):
        entities.authorize(system, conn, "example.widget", widget["id"], "write")


def test_titles_for_drops_what_the_user_cannot_read(app, make_user):
    owner, other = make_user("member"), make_user("member")
    a = service.create_widget(owner, WidgetIn(name="Open"))
    b = service.create_widget(owner, WidgetIn(name="Hidden", is_private=True))
    conn = core_db.get_conn()
    assert entities.titles_for(owner, conn, "example.widget", [a["id"], b["id"], 999]) == {a["id"]: "Open", b["id"]: "Hidden"}
    assert entities.titles_for(other, conn, "example.widget", [a["id"], b["id"]]) == {a["id"]: "Open"}
    assert entities.url_for("example.widget", a["id"]) == f"/example/widgets/{a['id']}"
    assert entities.url_for("core.person", 3) == "/people/3"


def test_delete_cascades_through_subscribers(app, make_user):
    owner = make_user("member")
    widget = service.create_widget(owner, WidgetIn(name="Gear"))
    timeline.add_note(owner, "example.widget", widget["id"], "first note")
    service.update_widget(owner, widget["id"], WidgetPatch(color="red"))
    with core_db.transaction() as conn:
        entities.delete_record_in(conn, "example.widget", widget["id"])
    assert core_db.one("SELECT count(*) AS n FROM example_widgets")["n"] == 0
    assert core_db.one("SELECT count(*) AS n FROM core_timeline")["n"] == 0
    log = core_db.rows("SELECT field, deleted_at FROM core_change_log")
    assert [r["field"] for r in log] == ["color"] and log[0]["deleted_at"] is not None  # history kept, marked


def test_app_subscribers_follow_person_delete_and_merge(app, make_user):
    owner = make_user("member")
    ada, grace = _person("Ada"), _person("Grace")
    widget = service.create_widget(owner, WidgetIn(name="Gear", person_id=ada))
    with core_db.transaction() as conn:
        entities.on_entity_merged_in(conn, "core.person", grace, ada)
    assert service.get_widget(owner, widget["id"])["person_id"] == grace
    with core_db.transaction() as conn:
        entities.delete_record_in(conn, "core.person", grace)
    assert service.get_widget(owner, widget["id"])["person_id"] is None


def test_register_refuses_duplicates_and_foreign_tables(app):
    person = entities.get("core.person")
    with pytest.raises(ValueError, match="twice"):
        entities.register(person)
    with pytest.raises(ValueError, match="must start with 'shop_'"):
        entities.register(entities.Entity("shop.item", "core_people", "Item", "Items", str, person.title_fn))
    with pytest.raises(ValueError, match="Unknown hook"):
        entities.subscribe("on_saved", print)
