import threading

import pytest

from backend.core import clock, db as core_db, entities, outbox
from backend.core.timeline import api as timeline


@pytest.fixture
def fresh(db):
    outbox.clear()
    yield
    outbox.clear()


def _enqueue(hook: str, payload: dict) -> int:
    with core_db.transaction() as conn:
        return outbox.enqueue_in(conn, hook, payload)


def _row(row_id: int) -> dict:
    return core_db.one("SELECT * FROM core_outbox WHERE id = ?", (row_id,))


def test_claim_is_atomic_and_a_stale_claim_is_reclaimed(fresh, freeze):
    freeze("2026-11-02T09:00:00Z")
    row_id = _enqueue("t.hook", {"n": 1})
    claimed = outbox.claim()
    assert claimed["id"] == row_id and claimed["claimed_at"] == "2026-11-02T09:00:00Z"
    assert outbox.claim() is None
    freeze("2026-11-02T09:10:01Z")  # older than CLAIM_TIMEOUT: its drainer is presumed dead
    assert outbox.claim()["id"] == row_id


def test_two_drainers_claim_disjoint_rows(fresh):
    seen, lock = [], threading.Lock()

    def consume(conn, payload):
        conn.execute("SELECT 1")
        with lock:
            seen.append(payload["n"])

    outbox.consumer("t.count")(consume)
    for n in range(40):
        _enqueue("t.count", {"n": n})
    workers = [threading.Thread(target=outbox.drain) for _ in range(2)]
    for w in workers:
        w.start()
    for w in workers:
        w.join()
    assert sorted(seen) == list(range(40))
    assert core_db.one("SELECT count(*) AS n FROM core_outbox WHERE processed_at IS NULL")["n"] == 0


def test_local_consumer_effect_and_processed_at_commit_together(fresh):
    def write_then_fail(conn, payload):
        conn.execute("INSERT INTO core_apps_state (slug) VALUES ('effect')")
        raise RuntimeError("after the effect")

    outbox.consumer("t.local")(write_then_fail)
    row_id = _enqueue("t.local", {})
    assert outbox.drain() == 0
    assert core_db.one("SELECT count(*) AS n FROM core_apps_state")["n"] == 0  # rolled back with the failure
    row = _row(row_id)
    assert row["processed_at"] is None and row["attempts"] == 1 and "after the effect" in row["last_error"]


def test_external_consumer_runs_outside_any_transaction_with_its_id(fresh):
    calls = []
    @outbox.consumer("t.remote", external=True)
    def remote(payload):
        calls.append((payload, core_db.in_transaction()))

    row_id = _enqueue("t.remote", {"x": 1})
    assert outbox.drain() == 1
    assert calls == [({"x": 1, "outbox_id": row_id}, False)]
    assert _row(row_id)["processed_at"] is not None


def test_dead_after_five_attempts_with_backoff(fresh, freeze):
    freeze("2026-11-02T09:00:00Z")
    outbox.consumer("t.broken")(lambda conn, payload: 1 / 0)
    row_id = _enqueue("t.broken", {})
    waits = []
    for attempt in range(1, 6):
        assert outbox.drain() == 0
        row = _row(row_id)
        assert row["attempts"] == attempt
        assert outbox.claim() is None  # backing off
        waits.append(clock.parse(row["available_at"]) - clock.now())
        freeze(row["available_at"])
    assert [w.total_seconds() for w in waits[:4]] == [30, 120, 600, 3600]
    assert row["dead_at"] is not None
    assert outbox.claim() is None


def test_unknown_hook_counts_as_a_failure(fresh):
    row_id = _enqueue("t.nobody", {})
    outbox.drain()
    assert "no consumer" in _row(row_id)["last_error"]


def test_commit_nudges_the_drainer_and_rollback_does_not(fresh):
    nudges = []
    core_db.set_commit_nudge(lambda: nudges.append(1))
    with core_db.transaction() as conn:
        conn.execute("INSERT INTO core_apps_state (slug) VALUES ('plain')")
    assert nudges == []  # nothing queued, nothing to wake
    _enqueue("t.any", {})
    assert nudges == [1]
    with pytest.raises(RuntimeError):
        with core_db.transaction() as conn:
            outbox.enqueue_in(conn, "t.any", {})
            raise RuntimeError
    assert nudges == [1]


def test_a_failing_nudge_never_fails_the_commit(fresh):
    core_db.set_commit_nudge(lambda: 1 / 0)
    row_id = _enqueue("t.any", {})
    assert _row(row_id) is not None


def test_failing_sync_subscriber_rolls_the_whole_write_back(app, make_user):
    from backend.apps.example import service
    from backend.apps.example.models import WidgetIn, WidgetPatch

    owner = make_user("member")
    widget = service.create_widget(owner, WidgetIn(name="Gear"))
    seen = []
    entities.subscribe("after_record_changed", lambda payload: seen.append(payload))

    def refuse(conn, entity_type, entity_id, **kw):
        raise RuntimeError("subscriber refused")

    entities.subscribe("on_record_changed", refuse)
    with pytest.raises(RuntimeError, match="subscriber refused"):
        service.update_widget(owner, widget["id"], WidgetPatch(name="Cog"))
    assert service.get_widget(owner, widget["id"])["name"] == "Gear"
    for table in ("core_timeline", "core_change_log", "core_outbox"):
        assert core_db.one(f"SELECT count(*) AS n FROM {table}")["n"] == 0, table


def test_after_record_changed_runs_once_after_commit(app, make_user, freeze):
    freeze("2026-11-02T09:00:00Z")
    owner = make_user("member")
    seen = []

    def after(payload):
        assert not core_db.in_transaction()
        seen.append(payload)

    entities.subscribe("after_record_changed", after)
    with core_db.transaction() as conn:
        conn.execute(
            "INSERT INTO example_widgets (id, name, owner_user_id, created_at, updated_at) VALUES (7, 'a', ?, 'x', 'x')",
            (owner.id,),
        )
        timeline.record_changes_in(conn, "example.widget", 7, {"name": "a"}, {"name": "b"}, owner.id)
        assert seen == []
    assert outbox.drain() == 1
    assert seen == [{
        "entity_type": "example.widget", "entity_id": 7, "changes": {"name": ["a", "b"]}, "user_id": owner.id,
        "at": "2026-11-02T09:00:00Z", "outbox_id": seen[0]["outbox_id"],
    }]
    assert outbox.drain() == 0
