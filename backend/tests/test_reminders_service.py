import pytest

from backend.core import db as core_db, entities, settings
from backend.core.notifications import service as notifications
from backend.core.reminders import service as reminders

W = "example.widget"


def _widget(client, **body) -> dict:
    r = client.post("/api/example/widgets", json={"name": "Gear", **body})
    assert r.status_code == 200, r.text
    return r.json()


def _remind(client, **body) -> dict:
    r = client.post("/api/core/reminders", json={"title": "Call back", **body})
    assert r.status_code == 200, r.text
    return r.json()


def _row(reminder_id: int) -> dict:
    return core_db.one("SELECT status, void_reason, fired_at, due_at FROM core_reminders WHERE id = ?", (reminder_id,))


def _notes() -> list[dict]:
    return core_db.rows("SELECT user_id, title, message, entity_type, entity_id, link FROM core_notifications ORDER BY id")


def test_routes_round_trip_and_ownership(login_as, freeze):
    freeze("2026-11-02T09:00:00Z")
    a, b = login_as("member"), login_as("member")
    w = _widget(a, name="Sprocket")
    r = _remind(a, note="ask about pricing", due_at="2026-11-03T15:00:00Z", entity_type=W, entity_id=w["id"])
    assert r == {
        "id": r["id"], "owner": {"id": a.user["id"], "name": a.user["name"]}, "mine": True,
        "entity_type": W, "entity_id": w["id"], "entity_title": "Sprocket", "link": f"/example/widgets/{w['id']}",
        "title": "Call back", "note": "ask about pricing", "due_at": "2026-11-03T15:00:00Z", "repeat": None,
        "series_id": r["id"], "status": "open", "void_reason": None, "fired_at": None,
        "created_at": "2026-11-02T09:00:00Z", "updated_at": "2026-11-02T09:00:00Z",
    }  # fmt: skip
    loose = _remind(a, title="Water plants", due_at="2026-11-02T12:00")  # no offset: the install zone (UTC)
    assert loose["due_at"] == "2026-11-02T12:00:00Z" and loose["link"] is None
    theirs = _remind(b, due_at="2026-11-04T09:00:00Z", entity_type=W, entity_id=w["id"])

    assert [x["id"] for x in a.get("/api/core/reminders").json()] == [loose["id"], r["id"]]
    assert [x["id"] for x in a.get("/api/core/reminders", params={"from": "2026-11-03", "to": "2026-11-04"}).json()] == [r["id"]]
    on_record = a.get("/api/core/reminders/for", params={"entity_type": W, "entity_id": w["id"]}).json()
    assert [(x["id"], x["mine"]) for x in on_record] == [(r["id"], True), (theirs["id"], False)]

    assert b.patch(f"/api/core/reminders/{r['id']}", json={"title": "mine now"}).status_code == 404
    assert b.post(f"/api/core/reminders/{r['id']}/done").status_code == 404
    assert b.delete(f"/api/core/reminders/{r['id']}").status_code == 404

    patched = a.patch(f"/api/core/reminders/{r['id']}", json={"title": "Call Ann", "repeat": {"freq": "weekly"}}).json()
    assert patched["title"] == "Call Ann"
    assert patched["repeat"] == {"freq": "weekly", "anchor": "2026-11-03", "time": "15:00", "tz": "UTC"}
    assert a.patch(f"/api/core/reminders/{r['id']}", json={"owner_user_id": b.user["id"]}).status_code == 422
    assert a.post(f"/api/core/reminders/{r['id']}/snooze", json={"until": "2026-11-01T00:00:00Z"}).status_code == 422
    snoozed = a.post(f"/api/core/reminders/{r['id']}/snooze", json={"until": "2026-11-05T08:00:00Z"}).json()
    assert (snoozed["status"], snoozed["due_at"]) == ("snoozed", "2026-11-05T08:00:00Z")
    assert a.post(f"/api/core/reminders/{loose['id']}/done").json()["status"] == "done"
    assert a.patch(f"/api/core/reminders/{loose['id']}", json={"title": "x"}).status_code == 409
    assert a.delete(f"/api/core/reminders/{loose['id']}").status_code == 204
    assert a.delete(f"/api/core/reminders/{loose['id']}").status_code == 404
    assert a.post("/api/core/reminders", json={"title": "x", "due_at": "soon"}).status_code == 422
    assert a.post("/api/core/reminders", json={"title": "x", "due_at": "2026-11-03T09:00:00Z", "entity_type": W}).status_code == 422


def test_private_record_refuses_another_member(login_as):
    owner, other = login_as("member"), login_as("member")
    w = _widget(owner, is_private=True)
    _remind(owner, due_at="2026-11-03T09:00:00Z", entity_type=W, entity_id=w["id"])
    body = {"title": "peek", "due_at": "2026-11-03T09:00:00Z", "entity_type": W, "entity_id": w["id"]}
    assert other.post("/api/core/reminders", json=body).status_code == 404
    assert other.get("/api/core/reminders/for", params={"entity_type": W, "entity_id": w["id"]}).status_code == 404
    assert other.get("/api/core/reminders").json() == []


def test_fires_under_a_frozen_clock_with_its_notification_in_the_same_transaction(login_as, freeze, monkeypatch):
    freeze("2026-11-02T08:00:00Z")
    a = login_as("member")
    w = _widget(a, name="Sprocket")
    r = _remind(a, note="ask about pricing", due_at="2026-11-02T09:00:00Z", entity_type=W, entity_id=w["id"])
    freeze("2026-11-02T08:59:59Z")
    assert reminders.fire_due()["fired"] == 0

    freeze("2026-11-02T09:00:00Z")

    def broken(*args, **kwargs):
        raise RuntimeError("delivery failed")

    monkeypatch.setattr(notifications, "deliver_in", broken)
    with pytest.raises(RuntimeError):
        reminders.fire_due()
    assert _row(r["id"])["fired_at"] is None and _notes() == []  # rolled back together
    monkeypatch.undo()

    assert reminders.fire_due() == {"due": 1, "fired": 1, "voided": 0, "spawned": 0}
    assert _row(r["id"]) == {"status": "open", "void_reason": None, "fired_at": "2026-11-02T09:00:00Z", "due_at": "2026-11-02T09:00:00Z"}
    assert _notes() == [{
        "user_id": a.user["id"], "title": "Reminder: Call back", "message": "ask about pricing",
        "entity_type": W, "entity_id": w["id"], "link": f"/example/widgets/{w['id']}",
    }]  # fmt: skip
    assert reminders.fire_due()["fired"] == 0  # once only

    loose = _remind(a, title="Stretch", due_at="2026-11-02T09:00:00Z")
    reminders.fire_due()
    assert _row(loose["id"])["fired_at"] and _notes()[-1]["link"] == "/reminders"


def test_voided_at_fire_time_when_the_owner_lost_access(login_as, make_user, freeze):
    freeze("2026-11-02T08:00:00Z")
    owner, other = login_as("member"), login_as("member")
    w = _widget(owner)
    r = _remind(other, due_at="2026-11-02T09:00:00Z", entity_type=W, entity_id=w["id"])
    leaver = login_as("member")
    left = _remind(leaver, due_at="2026-11-02T09:00:00Z")
    assert owner.patch(f"/api/example/widgets/{w['id']}", json={"is_private": True}).status_code == 200
    with core_db.transaction() as conn:
        conn.execute("UPDATE core_users SET is_active = 0 WHERE id = ?", (leaver.user["id"],))
    freeze("2026-11-02T09:00:00Z")
    assert reminders.fire_due() == {"due": 2, "fired": 0, "voided": 2, "spawned": 0}
    assert _row(r["id"])["status"] == "voided" and _row(r["id"])["void_reason"] == "owner can no longer read the record"
    assert _row(left["id"])["void_reason"] == "owner is no longer active"
    assert _notes() == []


def test_repeat_spawns_the_next_occurrence_across_dst(login_as, freeze):
    settings.set_setting("timezone", "America/Chicago", None)
    freeze("2026-10-30T12:00:00Z")
    a = login_as("member")
    w = _widget(a)
    r = _remind(a, due_at="2026-10-31T09:00", repeat={"freq": "daily"}, entity_type=W, entity_id=w["id"])
    assert r["due_at"] == "2026-10-31T14:00:00Z"  # 09:00 CDT
    assert r["repeat"] == {"freq": "daily", "anchor": "2026-10-31", "time": "09:00", "tz": "America/Chicago"}
    freeze("2026-10-31T14:00:00Z")
    assert reminders.fire_due()["spawned"] == 1
    nxt = core_db.one("SELECT * FROM core_reminders WHERE id != ? ORDER BY id DESC LIMIT 1", (r["id"],))
    assert nxt["due_at"] == "2026-11-01T15:00:00Z"  # 09:00 CST, the day DST ends
    assert (nxt["owner_user_id"], nxt["entity_type"], nxt["entity_id"], nxt["series_id"], nxt["status"], nxt["fired_at"]) == (
        a.user["id"], W, w["id"], r["id"], "open", None,
    )

    # Snoozing the fired occurrence fires it again but never spawns a second successor.
    freeze("2026-10-31T15:00:00Z")
    a.post(f"/api/core/reminders/{r['id']}/snooze", json={"until": "2026-10-31T16:00:00Z"})
    freeze("2026-10-31T16:00:00Z")
    assert reminders.fire_due() == {"due": 1, "fired": 1, "voided": 0, "spawned": 0}

    # Completing an occurrence before it fires still schedules the one after.
    assert a.post(f"/api/core/reminders/{nxt['id']}/done").json()["status"] == "done"
    assert [x["due_at"] for x in a.get("/api/core/reminders", params={"status": "open"}).json()] == [
        "2026-10-31T16:00:00Z", "2026-11-02T15:00:00Z",
    ]  # fmt: skip


def test_delete_voids_and_merge_repoints(login_as):
    a = login_as("member")
    x, y, z = _widget(a), _widget(a), _widget(a)
    on_x = _remind(a, due_at="2026-11-03T09:00:00Z", entity_type=W, entity_id=x["id"])
    on_y = _remind(a, due_at="2026-11-03T09:00:00Z", entity_type=W, entity_id=y["id"])
    with core_db.transaction() as conn:
        entities.delete_record_in(conn, W, x["id"])
        entities.on_entity_merged_in(conn, W, z["id"], y["id"])
    assert _row(on_x["id"])["status"] == "voided" and _row(on_x["id"])["void_reason"] == "record deleted"
    assert [r["id"] for r in a.get("/api/core/reminders/for", params={"entity_type": W, "entity_id": z["id"]}).json()] == [on_y["id"]]
