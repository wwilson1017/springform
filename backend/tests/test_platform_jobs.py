import threading
import time

from fastapi.testclient import TestClient

from backend.core import clock, db as core_db, scheduler
from backend.core.scheduler import Job


def _wait(predicate, seconds: float = 5) -> None:
    deadline = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < deadline, "timed out waiting"
        time.sleep(0.02)


def test_jobs_list_run_now_and_runs(app, login_as):
    admin, member = login_as("admin"), login_as("member")
    started, release = threading.Event(), threading.Event()

    def slow(cancel):
        started.set()
        release.wait(5)

    scheduler.register(Job("core.test_slow", slow, every=3600, timeout=30))
    with core_db.transaction() as conn:  # it ran a moment ago, so the scheduler's first tick leaves it alone
        now = clock.now_iso()
        conn.execute(
            """INSERT INTO core_job_runs (job, app, trigger, status, started_at, finished_at)
               VALUES ('core.test_slow', 'core', 'schedule', 'ok', ?, ?)""",
            (now, now),
        )

    # The lifespan starts the real scheduler; the admin's session rides along as a bearer token.
    with TestClient(app, headers={"Authorization": f"Bearer {admin.cookies.get('sf_session')}"}) as c:
        assert member.get("/api/core/jobs").status_code == 403
        assert member.post("/api/core/jobs/core.test_slow/run").status_code == 403

        jobs = {j["name"]: j for j in c.get("/api/core/jobs").json()}
        assert jobs["core.requests_refresh"] | {"last_run": None, "in_flight": False} == {
            "name": "core.requests_refresh", "app": "core", "every": 900, "at": None, "timeout": 120,
            "last_run": None, "in_flight": False,
        }  # fmt: skip
        assert jobs["core.test_slow"]["last_run"]["status"] == "ok" and jobs["core.test_slow"]["in_flight"] is False

        r = c.post("/api/core/jobs/core.test_slow/run")
        assert (r.status_code, r.json()) == (202, {"started": True})
        assert started.wait(5)
        r = c.post("/api/core/jobs/core.test_slow/run")
        assert (r.status_code, r.json()) == (409, {"detail": "already_running"})
        slow_job = next(j for j in c.get("/api/core/jobs").json() if j["name"] == "core.test_slow")
        assert slow_job["in_flight"] is True and slow_job["last_run"]["status"] == "running"
        assert c.post("/api/core/jobs/core.nope/run").status_code == 404

        release.set()
        _wait(lambda: c.get("/api/core/jobs/runs?job=core.test_slow").json()[0]["status"] == "ok")
        runs = c.get("/api/core/jobs/runs", params={"job": "core.test_slow"}).json()
        assert [(r["trigger"], r["status"]) for r in runs] == [("manual", "ok"), ("schedule", "ok")]
        assert set(runs[0]) == {
            "id",
            "job",
            "app",
            "trigger",
            "status",
            "scheduled_for",
            "started_at",
            "finished_at",
            "error",
        }
        assert len(c.get("/api/core/jobs/runs", params={"limit": 1}).json()) == 1


def test_dead_outbox_rows_are_listed_without_their_payload(login_as):
    admin, member = login_as("admin"), login_as("member")
    with core_db.transaction() as conn:
        conn.execute(
            """INSERT INTO core_outbox (hook, payload, created_at, available_at, attempts, last_error, dead_at)
               VALUES ('after_record_changed:x', '{"secret": 1}', 'a', 'a', 5, 'boom', 'b'),
                      ('after_record_changed:y', '{}', 'a', 'a', 0, NULL, NULL)"""
        )
    rows = admin.get("/api/core/jobs/outbox/dead").json()
    assert rows == [
        {
            "id": 1,
            "hook": "after_record_changed:x",
            "attempts": 5,
            "last_error": "boom",
            "created_at": "a",
            "dead_at": "b",
        }
    ]
    assert member.get("/api/core/jobs/outbox/dead").status_code == 403
