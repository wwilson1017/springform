import json
import sys
import types

import pytest

from backend.core import db as core_db, entities
from backend.core.notifications import push, service as notifications
from backend.core.notifications.service import Channel

W = "example.widget"


def _widget(client, **body) -> dict:
    r = client.post("/api/example/widgets", json={"name": "Gear", **body})
    assert r.status_code == 200, r.text
    return r.json()


def _private(client, widget_id: int) -> None:
    assert client.patch(f"/api/example/widgets/{widget_id}", json={"is_private": True}).status_code == 200


def _deliveries() -> list[dict]:
    return core_db.rows("SELECT notification_id, channel, status, attempts, last_error, sent_at FROM core_notification_deliveries ORDER BY id")


@pytest.fixture
def fake_channel(monkeypatch):
    """A channel every user receives; `fail[0]` failures are raised before sends succeed."""
    sent, fail = [], [0]

    def send(payload):
        if fail[0]:
            fail[0] -= 1
            raise RuntimeError("push service down")
        sent.append(payload)

    monkeypatch.setitem(notifications._CHANNELS, "fake", Channel("fake", send, None))
    return sent, fail


def test_private_widget_notification_reaches_its_owner_only(login_as, freeze):
    freeze("2026-11-02T09:00:00Z")
    owner, other = login_as("member"), login_as("member")
    w = _widget(owner, is_private=True)
    [nid] = notifications.deliver("Ping", "hello", user_id=owner.user["id"], entity=(W, w["id"]))
    assert notifications.deliver("Ping", "hello", user_id=other.user["id"], entity=(W, w["id"])) == []
    assert owner.get("/api/core/notifications").json() == [{
        "id": nid, "title": "Ping", "message": "hello", "entity_type": W, "entity_id": w["id"],
        "link": f"/example/widgets/{w['id']}", "created_at": "2026-11-02T09:00:00Z", "read_at": None,
    }]  # fmt: skip
    assert other.get("/api/core/notifications").json() == []
    assert other.post(f"/api/core/notifications/{nid}/read").status_code == 404


def test_broadcast_expands_to_active_humans_and_read_state_is_per_user(login_as, make_user):
    a, b = login_as("member"), login_as("member")
    gone = make_user("member")
    with core_db.transaction() as conn:
        conn.execute("UPDATE core_users SET is_active = 0 WHERE id = ?", (gone.id,))
    w = _widget(a)
    notifications.deliver("Heads up", "public news", entity=(W, w["id"]))
    humans = {r["id"] for r in core_db.rows("SELECT id FROM core_users WHERE role != 'system' AND is_active = 1")}
    rows = core_db.rows("SELECT id, user_id FROM core_notifications")
    assert {r["user_id"] for r in rows} == humans and len(rows) == len(humans) == 3  # the setup admin, a, b
    mine = next(r["id"] for r in rows if r["user_id"] == a.user["id"])
    assert a.post(f"/api/core/notifications/{mine}/read").json()["read_at"] is not None
    assert a.get("/api/core/notifications/unread-count").json() == {"count": 0}
    assert b.get("/api/core/notifications/unread-count").json() == {"count": 1}
    assert b.get("/api/core/notifications", params={"unread": 1}).json()[0]["title"] == "Heads up"
    assert b.post("/api/core/notifications/read-all").json() == {"updated": 1}
    assert b.get("/api/core/notifications", params={"unread": 1}).json() == []


def test_record_gone_private_after_queueing_drops_the_delivery_and_hides_the_row(login_as, fake_channel):
    sent, _ = fake_channel
    owner, other = login_as("member"), login_as("member")
    w = _widget(owner)
    [nid] = notifications.deliver("New gear", "", user_id=other.user["id"], entity=(W, w["id"]))
    assert _deliveries()[0]["status"] == "queued"
    _private(owner, w["id"])
    assert notifications.flush()["dropped"] == 1 and sent == []
    assert _deliveries()[0] | {"sent_at": None} == {
        "notification_id": nid, "channel": "fake", "status": "dropped", "attempts": 0,
        "last_error": "recipient can no longer read the record", "sent_at": None,
    }  # fmt: skip
    assert other.get("/api/core/notifications").json() == []
    assert core_db.one("SELECT suppressed_at FROM core_notifications WHERE id = ?", (nid,))["suppressed_at"] is not None


def test_in_app_row_is_hidden_on_next_read_once_access_is_gone(login_as):
    owner, other = login_as("member"), login_as("member")
    w = _widget(owner)
    [nid] = notifications.deliver("New gear", "", user_id=other.user["id"], entity=(W, w["id"]))
    assert other.get("/api/core/notifications/unread-count").json() == {"count": 1}
    _private(owner, w["id"])
    assert other.get("/api/core/notifications/unread-count").json() == {"count": 0}
    assert core_db.one("SELECT suppressed_at FROM core_notifications WHERE id = ?", (nid,))["suppressed_at"] is not None
    assert other.get("/api/core/notifications").json() == []
    assert other.post(f"/api/core/notifications/{nid}/read").status_code == 404


def test_flush_sends_once_retries_and_gives_up(login_as, fake_channel):
    sent, fail = fake_channel
    member = login_as("member")
    [nid] = notifications.deliver("Hi", "there", user_id=member.user["id"], link="/somewhere")
    assert notifications.flush() == {"sent": 1, "retry": 0, "failed": 0, "dropped": 0}
    assert sent == [{
        "notification_id": nid, "user_id": member.user["id"], "title": "Hi", "message": "there",
        "link": "/somewhere", "entity_type": None, "entity_id": None,
    }]  # fmt: skip
    assert notifications.flush()["sent"] == 0 and len(sent) == 1
    assert _deliveries()[0]["status"] == "sent" and _deliveries()[0]["sent_at"] is not None

    notifications.deliver("Again", "", user_id=member.user["id"])
    fail[0] = 2
    assert notifications.flush()["retry"] == 1
    assert notifications.flush()["retry"] == 1
    assert notifications.flush()["sent"] == 1
    assert _deliveries()[1] | {"sent_at": None} == {
        "notification_id": nid + 1, "channel": "fake", "status": "sent", "attempts": 3, "last_error": None, "sent_at": None,
    }  # fmt: skip

    notifications.deliver("Doomed", "", user_id=member.user["id"])
    fail[0] = notifications.MAX_ATTEMPTS
    for _ in range(notifications.MAX_ATTEMPTS):
        notifications.flush()
    assert _deliveries()[2]["status"] == "failed" and _deliveries()[2]["attempts"] == notifications.MAX_ATTEMPTS
    assert notifications.flush() == {"sent": 0, "retry": 0, "failed": 0, "dropped": 0}


def test_crash_between_send_and_sent_at_resends_exactly_once(login_as, fake_channel, monkeypatch):
    sent, _ = fake_channel
    member = login_as("member")
    notifications.deliver("Hi", "", user_id=member.user["id"])
    real_finish = notifications._finish

    def crash(*args, **kwargs):
        raise SystemExit("process killed after the send")

    monkeypatch.setattr(notifications, "_finish", crash)
    with pytest.raises(SystemExit):
        notifications.flush()
    assert len(sent) == 1 and _deliveries()[0]["status"] == "queued"
    monkeypatch.setattr(notifications, "_finish", real_finish)
    notifications.flush()
    notifications.flush()
    assert len(sent) == 2  # at-least-once: one duplicate, carrying the same notification_id
    assert sent[0]["notification_id"] == sent[1]["notification_id"]
    assert _deliveries()[0]["status"] == "sent"


def _fake_pywebpush(monkeypatch, dead: set[str]) -> list[dict]:
    calls = []

    class WebPushException(Exception):
        def __init__(self, message, response=None):
            super().__init__(message)
            self.response = response

    def webpush(subscription_info, data, vapid_private_key, vapid_claims, timeout, ttl):
        calls.append({"endpoint": subscription_info["endpoint"], "data": json.loads(data), "key": vapid_private_key, "sub": vapid_claims["sub"]})
        if subscription_info["endpoint"] in dead:
            raise WebPushException("gone", response=types.SimpleNamespace(status_code=410))

    module = types.ModuleType("pywebpush")
    module.webpush, module.WebPushException = webpush, WebPushException
    monkeypatch.setitem(sys.modules, "pywebpush", module)
    return calls


def test_push_subscribe_send_and_dead_subscription(login_as, monkeypatch):
    live, dead = "https://push.example.com/live", "https://push.example.com/dead"
    calls = _fake_pywebpush(monkeypatch, {dead})
    member, other = login_as("member"), login_as("member")
    key = member.get("/api/core/notifications/push/public-key").json()["public_key"]
    assert other.get("/api/core/notifications/push/public-key").json() == {"public_key": key}
    stored = core_db.one("SELECT value, is_secret FROM core_settings WHERE key = ?", (push.PRIVATE_KEY,))
    assert stored["is_secret"] == 1 and stored["value"].startswith("enc:v1:")

    keys = {"p256dh": "BPk", "auth": "au"}
    for endpoint in (live, dead):
        assert member.post("/api/core/notifications/push/subscribe", json={"endpoint": endpoint, "keys": keys}).json() == {"ok": True}
    for bad in ("http://push.example.com/x", "https://127.0.0.1/x", "https://localhost/x"):
        assert member.post("/api/core/notifications/push/subscribe", json={"endpoint": bad, "keys": keys}).status_code == 422

    assert notifications.deliver("Nobody subscribed", "", user_id=other.user["id"]) and _deliveries() == []
    [nid] = notifications.deliver("Hi", "body", user_id=member.user["id"], link="/x")
    assert notifications.flush()["sent"] == 1
    assert [c["endpoint"] for c in calls] == [live, dead]
    assert calls[0]["data"] == {"notification_id": nid, "title": "Hi", "body": "body", "url": "/x"}
    assert calls[0]["key"] == push.vapid_keys()[1] and calls[0]["sub"] == "mailto:push@springform.invalid"
    failed = {r["endpoint"]: r["failed_at"] for r in core_db.rows("SELECT endpoint, failed_at FROM core_push_subscriptions")}
    assert failed[live] is None and failed[dead] is not None

    notifications.deliver("Second", "", user_id=member.user["id"])
    notifications.flush()
    assert [c["endpoint"] for c in calls[2:]] == [live]

    unsubscribe = lambda client, endpoint: client.request("DELETE", "/api/core/notifications/push/subscribe", json={"endpoint": endpoint})  # noqa: E731
    assert unsubscribe(other, live).json() == {"removed": False}
    assert unsubscribe(member, live).json() == {"removed": True}
    assert notifications.deliver("Third", "", user_id=member.user["id"]) and len(_deliveries()) == 2  # no live subscription left


def test_delete_hides_and_merge_repoints(login_as, fake_channel):
    member = login_as("member")
    a, b, c = _widget(member), _widget(member), _widget(member)
    [on_a] = notifications.deliver("A", "", user_id=member.user["id"], entity=(W, a["id"]))
    [on_b] = notifications.deliver("B", "", user_id=member.user["id"], entity=(W, b["id"]))
    with core_db.transaction() as conn:
        entities.delete_record_in(conn, W, a["id"])
        entities.on_entity_merged_in(conn, W, c["id"], b["id"])
    assert [n["id"] for n in member.get("/api/core/notifications").json()] == [on_b]
    moved = core_db.one("SELECT entity_id, link FROM core_notifications WHERE id = ?", (on_b,))
    assert moved == {"entity_id": c["id"], "link": f"/example/widgets/{c['id']}"}
    assert notifications.flush() == {"sent": 1, "retry": 0, "failed": 0, "dropped": 1}


def test_links_are_in_app_paths_only(login_as):
    member = login_as("member")
    for link, kept in [("/crm/1", "/crm/1"), ("//evil.example", None), ("https://evil.example", None), ("/a b", None), ("/\\evil", None)]:
        [nid] = notifications.deliver("t", "", user_id=member.user["id"], link=link)
        assert core_db.one("SELECT link FROM core_notifications WHERE id = ?", (nid,))["link"] == kept
