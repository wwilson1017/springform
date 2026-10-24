import asyncio
import threading
import time
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from backend.core import clock, db as core_db, outbox, scheduler
from backend.core.scheduler import Job, Scheduler


def _runs(job: str) -> list[dict]:
    return core_db.rows(
        "SELECT triggered_by, status, scheduled_for, finished_at, error FROM core_job_runs WHERE job = ? ORDER BY id", (job,)
    )


def test_run_now_records_ok_and_error(db):
    ran = []
    jobs = {"core.ok": Job("core.ok", lambda cancel: ran.append(1), every=60), "core.bad": Job("core.bad", lambda cancel: 1 / 0, every=60)}

    async def go():
        s = Scheduler(jobs)
        assert await s.run_now("core.ok") and await s.run_now("core.bad")
        await s.wait_idle()

    asyncio.run(go())
    assert ran == [1]
    assert [(r["triggered_by"], r["status"]) for r in _runs("core.ok")] == [("manual", "ok")]
    bad = _runs("core.bad")[0]
    assert bad["status"] == "error" and "ZeroDivisionError" in bad["error"]


def test_a_job_that_ignores_its_timeout_never_overlaps_itself(db, freeze):
    release = threading.Event()

    def stubborn(cancel):
        release.wait(5)  # ignores cancel on purpose

    job = Job("core.stubborn", stubborn, every=60, timeout=0.05)
    freeze("2026-11-02T09:00:00Z")

    async def go():
        s = Scheduler({job.name: job})
        assert await s.run_now(job.name)
        await asyncio.sleep(0.2)
        freeze("2026-11-02T09:01:00Z")  # due again
        assert _runs(job.name)[0]["status"] == "timed_out" and _runs(job.name)[0]["finished_at"] is None
        assert s._cancel[job.name].is_set()
        assert await s.run_now(job.name) is False  # still in flight
        await s.tick_once()  # due again, still running: skipped, not started
        assert [r["status"] for r in _runs(job.name)] == ["timed_out", "skipped"]
        release.set()
        await s.wait_idle()
        assert _runs(job.name)[0]["finished_at"] is not None
        assert await s.run_now(job.name)  # slot released only now
        await s.wait_idle()

    asyncio.run(go())
    assert [r["status"] for r in _runs(job.name)] == ["timed_out", "skipped", "ok"]


def test_concurrency_is_bounded(db):
    active, peak, lock = [0], [0], threading.Lock()

    def work(cancel):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.05)
        with lock:
            active[0] -= 1

    jobs = {f"core.j{i}": Job(f"core.j{i}", work, every=60) for i in range(6)}

    async def go():
        s = Scheduler(jobs, concurrency=2)
        for name in jobs:
            await s.run_now(name)
        await s.wait_idle()

    asyncio.run(go())
    assert peak[0] == 2


def test_stale_running_rows_become_interrupted_on_start(db):
    with core_db.transaction() as conn:
        for status in ("running", "timed_out", "ok"):
            conn.execute(
                "INSERT INTO core_job_runs (job, app, triggered_by, status, started_at) VALUES ('core.x', 'core', 'schedule', ?, 'x')",
                (status,),
            )

    async def go():
        s = Scheduler({})
        await s.start()
        await s.stop()

    asyncio.run(go())
    assert [r["status"] for r in _runs("core.x")] == ["interrupted", "interrupted", "ok"]


def test_at_jobs_run_once_per_local_day_with_one_catch_up(db, freeze):
    job = Job("core.nightly", lambda cancel: None, at="03:00")
    with core_db.transaction() as conn:
        conn.execute("INSERT INTO core_settings (key, value, updated_at) VALUES ('timezone', '\"America/Chicago\"', 'x')")

    def due():
        return [(j.name, day) for j, day in scheduler.due_jobs({job.name: job})]

    freeze("2026-11-05T15:00:00Z")  # 09:00 in Chicago; down for days, so one catch-up for today only
    assert due() == [("core.nightly", "2026-11-05")]
    asyncio.run(_run_scheduled(job, "2026-11-05"))
    assert due() == []
    freeze("2026-11-06T08:00:00Z")  # 02:00 local: the slot has not come yet
    assert due() == []
    freeze("2026-11-06T09:00:00Z")  # 03:00 local
    assert due() == [("core.nightly", "2026-11-06")]


async def _run_scheduled(job, day):
    s = Scheduler({job.name: job})
    assert s._spawn(job, "schedule", day)
    await s.wait_idle()


def test_last_slot_day_is_dst_safe():
    chicago = ZoneInfo("America/Chicago")
    # 2026-03-08: local 02:00-03:00 does not exist (07:59 UTC is 01:59 CST, 08:00 UTC is 03:00 CDT);
    # a 02:30 slot still fires that day, as soon as 03:00 arrives.
    assert scheduler.last_slot_day("02:30", datetime(2026, 3, 8, 7, 59, tzinfo=UTC), chicago) == "2026-03-07"
    assert scheduler.last_slot_day("02:30", datetime(2026, 3, 8, 8, 0, tzinfo=UTC), chicago) == "2026-03-08"
    # 2026-11-01: local 01:00-02:00 happens twice (06:30 UTC is 01:30 CDT, 07:30 UTC is 01:30 CST);
    # both belong to the same day, so the slot cannot fire twice.
    assert scheduler.last_slot_day("01:30", datetime(2026, 11, 1, 6, 29, tzinfo=UTC), chicago) == "2026-10-31"
    assert scheduler.last_slot_day("01:30", datetime(2026, 11, 1, 6, 30, tzinfo=UTC), chicago) == "2026-11-01"
    assert scheduler.last_slot_day("01:30", datetime(2026, 11, 1, 7, 30, tzinfo=UTC), chicago) == "2026-11-01"


def test_every_jobs_are_due_after_their_interval(db, freeze):
    job = Job("core.often", lambda cancel: None, every=60)
    freeze("2026-11-02T09:00:00Z")
    assert len(scheduler.due_jobs({job.name: job})) == 1
    asyncio.run(_run_scheduled(job, None))
    freeze("2026-11-02T09:00:59Z")
    assert scheduler.due_jobs({job.name: job}) == []
    freeze("2026-11-02T09:01:00Z")
    assert len(scheduler.due_jobs({job.name: job})) == 1


def test_a_commit_with_outbox_rows_wakes_the_drainer(db):
    outbox.clear()
    done = threading.Event()
    outbox.consumer("t.wake")(lambda conn, payload: done.set())
    drain = Job("core.outbox_drain", outbox.drain, every=3600)

    async def go():
        s = Scheduler({drain.name: drain}, tick=3600)
        await s.start()
        await asyncio.sleep(0.1)  # the first tick runs the drain once
        await s.wait_idle()

        def write():
            with core_db.transaction() as conn:
                outbox.enqueue_in(conn, "t.wake", {})

        await asyncio.to_thread(write)
        for _ in range(50):
            if done.is_set():
                break
            await asyncio.sleep(0.02)
        await s.stop()

    asyncio.run(go())
    outbox.clear()
    assert done.is_set()
    assert [r["triggered_by"] for r in _runs("core.outbox_drain")] == ["schedule", "nudge"]


def test_job_validation():
    with pytest.raises(ValueError, match="exactly one"):
        Job("core.x", print)
    with pytest.raises(ValueError, match="HH:MM"):
        Job("core.x", print, at="3am")
    with pytest.raises(ValueError, match="int"):
        Job("core.x", print, every=0.5)
    scheduler.clear()
    with pytest.raises(ValueError, match="core.<job>"):
        scheduler.register(Job("tidy", print, every=1))
    assert clock.now_iso()


def test_run_now_route(app, monkeypatch):
    from fastapi.testclient import TestClient

    from backend.core.auth import bootstrap, service as auth_service

    release = threading.Event()
    scheduler.register(Job("core.slow", lambda cancel: release.wait(5), every=86400))
    with TestClient(app, headers={"Sec-Fetch-Site": "same-origin"}) as client:  # runs the real lifespan
        token = bootstrap.ensure_setup_token()
        client.post("/api/auth/setup", json={"token": token, "email": "a@example.com", "password": "long-enough-1"})
        time.sleep(0.3)  # the first tick has started core.slow, which waits on `release`
        assert client.post("/api/core/jobs/core.slow/run").json() == {"detail": "already_running"}
        assert client.post("/api/core/jobs/nope/run").status_code == 404
        with core_db.transaction() as conn:
            auth_service.create_user_in(conn, "m@example.com", "M", "member", "long-enough-1")
        member = TestClient(app, headers={"Sec-Fetch-Site": "same-origin"})
        member.post("/api/auth/login", json={"email": "m@example.com", "password": "long-enough-1"})
        assert member.post("/api/core/jobs/core.slow/run").status_code == 403
        release.set()
        deadline, status = time.time() + 5, None
        while status != 202 and time.time() < deadline:
            status = client.post("/api/core/jobs/core.slow/run").status_code
            time.sleep(0.05)
        assert status == 202
