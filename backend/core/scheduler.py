"""The scheduler: one asyncio loop runs registered jobs in worker threads (docs/agents/scheduler.md).

- `Job(name, fn, every=<seconds> | at="HH:MM", app, timeout)`; `fn(cancel_event)` runs in a thread
  and should check `cancel_event` between steps.
- Every TICK seconds the loop starts due jobs, at most CONCURRENCY at once. A job never overlaps
  itself: the in-flight guard is shared with `run_now`, and a job still running at its next due
  time is logged `skipped`.
- A timeout cannot stop a thread. The run is marked `timed_out` and its cancel_event is set, but
  the guard and the semaphore slot are held until the thread actually returns.
- `at` jobs run once per install-local day (timezone from the `timezone` setting), with a single
  catch-up when the slot since the job's last run was missed. A job that has never run waits for
  its next slot, so a fresh install does not run every `at` job at boot. `every` jobs are not caught up.
- Startup marks stale `running`/`timed_out` rows `interrupted`. Runs only in the process that
  holds the data-dir lock (main.py starts it after db.init).
- A committed transaction that queued outbox rows nudges `core.outbox_drain` immediately.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from backend.core import clock, db, localtime

logger = logging.getLogger(__name__)

TICK = 30
CONCURRENCY = 4
_AT = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


@dataclass(frozen=True)
class Job:
    name: str
    fn: Callable[[threading.Event], Any]
    every: int | None = None  # seconds
    at: str | None = None
    app: str = "core"
    timeout: float = 300

    def __post_init__(self) -> None:
        if (self.every is None) == (self.at is None):
            raise ValueError(f"Job {self.name!r}: give exactly one of every= or at=")
        if self.at is not None and not _AT.match(self.at):
            raise ValueError(f"Job {self.name!r}: at must be 'HH:MM'")
        if self.every is not None and (not isinstance(self.every, int) or self.every <= 0):
            raise ValueError(f"Job {self.name!r}: every must be a positive whole number of seconds")


_JOBS: dict[str, Job] = {}


def register(job: Job) -> None:
    if not job.name.startswith(f"{job.app}."):
        raise ValueError(f"Job {job.name!r} must be named '{job.app}.<job>'")
    if job.name in _JOBS:
        raise ValueError(f"Job {job.name!r} is registered twice")
    _JOBS[job.name] = job


def clear() -> None:
    _JOBS.clear()


def jobs() -> dict[str, Job]:
    return dict(_JOBS)


def last_slot_day(at: str, now: datetime, zone: ZoneInfo) -> str:
    """The install-local day of the most recent `at` slot at or before `now`.

    Wall-clock comparison in the install zone, so a slot inside a DST gap still fires once that
    day and a slot inside a repeated hour fires on its first occurrence only."""
    local = now.astimezone(zone)
    hh, mm = map(int, at.split(":"))
    day = local.date()
    if local.replace(tzinfo=None) < datetime.combine(day, time(hh, mm)):
        day -= timedelta(days=1)
    return day.isoformat()


def due_jobs(registered: dict[str, Job], since: datetime) -> list[tuple[Job, str | None]]:
    """Jobs due now, each with the local day an `at` job's run covers (None for `every`).

    An `at` job is due when its latest slot has no run and came after the job's last run, or, for
    a job that has never run, after `since` (when the scheduler started). Slots are compared as
    install-local wall-clock times, like `last_slot_day`."""
    now, zone, due = clock.now(), localtime.tz(), []
    for job in registered.values():
        last = db.one("SELECT max(started_at) AS t FROM core_job_runs WHERE job = ?", (job.name,))["t"]
        if job.every is not None:
            if last is None or clock.parse(last) + timedelta(seconds=job.every) <= now:
                due.append((job, None))
            continue
        day = last_slot_day(job.at, now, zone)
        if db.one("SELECT 1 AS x FROM core_job_runs WHERE job = ? AND scheduled_for = ?", (job.name, day)):
            continue
        slot = datetime.combine(date.fromisoformat(day), time(*map(int, job.at.split(":"))))
        anchor = clock.parse(last) if last else since
        if slot >= anchor.astimezone(zone).replace(tzinfo=None):
            due.append((job, day))
    return due


def mark_interrupted() -> int:
    """Rows still `running`/`timed_out` with no finish belong to a process that is gone."""
    with db.transaction() as conn:
        return conn.execute(
            """UPDATE core_job_runs SET status = 'interrupted', finished_at = ?
                WHERE status IN ('running', 'timed_out') AND finished_at IS NULL""",
            (clock.now_iso(),),
        ).rowcount


def prune_job_runs(cancel: threading.Event | None = None) -> None:
    """Job core.job_runs_prune: keep 30 days of job history."""
    with db.transaction() as conn:
        conn.execute("DELETE FROM core_job_runs WHERE started_at < ? AND finished_at IS NOT NULL", (clock.ago(30 * 86400),))


def _insert_run(job: Job, trigger: str, status: str, scheduled_for: str | None) -> int:
    now = clock.now_iso()
    with db.transaction() as conn:
        return conn.execute(
            """INSERT INTO core_job_runs (job, app, trigger, status, scheduled_for, started_at, finished_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (job.name, job.app, trigger, status, scheduled_for, now, now if status == "skipped" else None),
        ).lastrowid


def _update_run(run_id: int, status: str, error: str | None = None, finished: bool = True) -> None:
    with db.transaction() as conn:
        conn.execute(
            "UPDATE core_job_runs SET status = ?, error = coalesce(?, error), finished_at = ? WHERE id = ?",
            (status, error, clock.now_iso() if finished else None, run_id),
        )


class Scheduler:
    def __init__(self, registered: dict[str, Job], *, tick: float = TICK, concurrency: int = CONCURRENCY):
        self.jobs = registered
        self.tick = tick
        self._sem = asyncio.Semaphore(concurrency)
        self._guard = threading.Lock()
        self._inflight: set[str] = set()
        self._cancel: dict[str, threading.Event] = {name: threading.Event() for name in registered}
        self._tasks: set[asyncio.Task] = set()
        self._nudged = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_task: asyncio.Task | None = None
        self.since = clock.now()  # a never-run `at` job waits for a slot after this

    async def start(self) -> None:
        await asyncio.to_thread(mark_interrupted)
        self._loop = asyncio.get_running_loop()
        db.set_commit_nudge(self.nudge)
        self._loop_task = asyncio.create_task(self._run_loop())

    async def stop(self, grace: float = 10) -> None:
        db.set_commit_nudge(None)
        if self._loop_task:
            self._loop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._loop_task
        for event in self._cancel.values():
            event.set()
        if self._tasks:
            await asyncio.wait(self._tasks, timeout=grace)
        # simplification: a job thread that ignores cancel_event keeps the process alive at exit (the
        # default executor joins its threads); core jobs bound their I/O. Upgrade path: a daemon-thread executor.
        for task in list(self._tasks):
            task.cancel()
        await asyncio.to_thread(mark_interrupted)

    def nudge(self) -> None:
        """Thread-safe: wake the loop to drain the outbox now."""
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._nudged.set)

    async def run_now(self, name: str) -> bool:
        """Start a job now. False when it is already running. KeyError for an unknown name."""
        return self._spawn(self.jobs[name], "manual", None)

    async def tick_once(self) -> None:
        for job, day in await asyncio.to_thread(due_jobs, self.jobs, self.since):
            if not self._spawn(job, "schedule", day):
                await asyncio.to_thread(_insert_run, job, "schedule", "skipped", day)

    async def wait_idle(self) -> None:
        """Wait for every started run to finish (tests)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def _run_loop(self) -> None:
        while True:
            try:
                await self.tick_once()
            except Exception:
                logger.exception("scheduler tick failed")
            try:
                await asyncio.wait_for(self._nudged.wait(), self.tick)
            except TimeoutError:
                continue
            self._nudged.clear()
            # simplification: a nudge that lands while the drain is already running is dropped, so a row
            # committed after the drain's last claim waits for the next tick (<= TICK s); upgrade path: a
            # "run again" flag on the in-flight guard.
            if drain := self.jobs.get("core.outbox_drain"):
                self._spawn(drain, "nudge", None)

    def _spawn(self, job: Job, trigger: str, scheduled_for: str | None) -> bool:
        with self._guard:
            if job.name in self._inflight:
                return False
            self._inflight.add(job.name)
        task = asyncio.create_task(self._run(job, trigger, scheduled_for))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return True

    async def _run(self, job: Job, trigger: str, scheduled_for: str | None) -> None:
        try:
            async with self._sem:
                run_id = await asyncio.to_thread(_insert_run, job, trigger, "running", scheduled_for)
                cancel = self._cancel.setdefault(job.name, threading.Event())
                cancel.clear()
                work = asyncio.ensure_future(asyncio.to_thread(job.fn, cancel))
                try:
                    await asyncio.wait_for(asyncio.shield(work), job.timeout)
                except TimeoutError:
                    cancel.set()
                    await asyncio.to_thread(_update_run, run_id, "timed_out", f"timed out after {job.timeout}s", False)
                    with contextlib.suppress(Exception):
                        await work  # hold the guard and the slot until the thread really ends
                    await asyncio.to_thread(_update_run, run_id, "timed_out")
                except Exception as e:
                    logger.exception("job %s failed", job.name)
                    await asyncio.to_thread(_update_run, run_id, "error", repr(e)[:2000])
                else:
                    await asyncio.to_thread(_update_run, run_id, "ok")
        except Exception:
            logger.exception("job %s could not be run", job.name)
        finally:
            with self._guard:
                self._inflight.discard(job.name)
