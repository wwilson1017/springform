# Scheduler

**What this covers:** §11 in full: the `Job` shape, the loop, concurrency and the per-job guard, timeout semantics and `cancel_event`, shutdown, the `core_job_runs` status enum, `at` vs `every`, catch-up, timezone, `run_now`, and the core job list with cadences.
**Who reads it:** W3 (scheduler, Jobs page), anyone writing `jobs.py` in an app, and owners of core jobs (backup, sheets, requests, reminders, notifications, outbox, files, agent).

Code: `backend/core/scheduler.py` (~300). The loop shape is todo-gtd's `_tick` (`backend/main.py`).

## 1. `Job`

```python
Job(name, fn, every | at, app, timeout=300)
```

| Field | Contract |
|---|---|
| `name` | `<slug>.<job>` for apps (contract test); `core.<job>` for core, including a core package's `jobs.py`. |
| `fn` | The job function, `fn(cancel_event: threading.Event)`; the event is its only argument. Runs in `asyncio.to_thread`. Checks `cancel_event` between steps. |
| `every` | An interval in seconds (`int`). Not caught up when missed. |
| `at` | `"HH:MM"` install-local. Runs once per install-local day. |
| `app` | Owning app slug (or core). |
| `timeout` | Seconds, default **300**. |

Apps declare `JOBS = [Job(name="<slug>.<job>", fn, every=…|at="HH:MM")]` in `jobs.py`.

## 2. The loop

1. One asyncio loop ticks every **30 s**.
2. Each tick computes due jobs from `core_job_runs`.
3. Due jobs run **concurrently under a semaphore of 4**, each in `asyncio.to_thread`.
4. A **per-job in-flight guard**, shared with `run_now`, means a job never overlaps itself. This guard is what makes `core.outbox_drain` single-flight.
5. The scheduler runs only in the process holding the `/data/.springform.lock` `flock`.

## 3. Timeouts

**A timeout cannot stop a thread.** So:

1. The in-flight guard and the semaphore slot are held **until the thread actually returns**.
2. On timeout the run is marked `timed_out` (it is still running).
3. The job's `cancel_event` is set. Job functions check it between steps, and every core job's I/O is bounded.
4. A job that is still running at its next due time is logged `skipped`.

## 4. Shutdown and startup

1. Shutdown sets every `cancel_event`, waits up to **10 s** (matching uvicorn's `--timeout-graceful-shutdown 10`, `deploy.md`), then marks what is still running `interrupted`.
2. On startup, stale `running` and `timed_out` rows become `interrupted`.

## 5. `core_job_runs`

```sql
core_job_runs(id, job, app, trigger, status, scheduled_for, started_at, finished_at, error)
```

`trigger` is `schedule`, `manual` or `nudge`. `scheduled_for` is the install-local day an `at` job's run covers.

`status`:

```
running | ok | error | timed_out | interrupted | skipped
```

## 6. `at` and `every`

| Kind | Rule |
|---|---|
| `at` | Once per install-local day, computed in the install timezone, **DST-safe**. A **single catch-up** if the slot was missed (restart or downtime). |
| `every` | Not caught up. |

Timezone: `core_settings.timezone` (IANA, default `UTC`). Nothing hardcoded.

## 7. `run_now`

`POST /api/core/jobs/{name}/run` (admin) runs a job now, through the same in-flight guard (it never overlaps a running instance). It returns **202**, or **409** when the job is already in flight. The Jobs page lists runs and offers "run now"; "Back up now" on the Backups page runs `core.backup` the same way.

## 8. Core jobs

| Job | Cadence | What |
|---|---|---|
| `core.backup` | `at` 03:00 | `VACUUM INTO` snapshot + manifest (`deploy.md`). |
| `core.sheets_refresh` | every 1 h | Refresh connected sheets (`sheets-and-export.md`). |
| `core.requests_refresh` | every 15 min | Refresh the Requests board from GitHub (`frontend-shell.md`). |
| `core.reminders.fire_due` | every 60 s | Fire due reminders (`records.md`). |
| `core.notifications.flush` | every 30 s | Send queued external deliveries (`records.md`). |
| `core.outbox_drain` | every 30 s + nudge after `COMMIT` | The single outbox drainer (`database-and-transactions.md`). |
| `core.files.sweep` | `at` 03:30 | Delete unreferenced, unpinned blobs (`records.md`). |
| `core.job_runs_prune` | `at` 04:00 | Keep 30 days of `core_job_runs`. |
| `core.login_attempts_prune` | hourly | Prune `core_login_attempts`. |
| `core.agent_nightly` | `at` 02:00, gated by the setting `agent.nightly_enabled` | Observer + dreaming; exits early with zero keys (`agent.md`). |

App jobs named in the plan: `crm.touch_count` every 2 min (drains ≤20 deals, LLM call outside the transaction, skipped with zero keys).

All `at` times are install-local.

Open (pinned by the implementing workstream, which updates this doc): the hourly outbound-MCP discovery (`mcp.md`) has no job in this list.

## 9. Step 1

Step 1 ships a minimal scheduler: `Job`, the loop, `run_now`. W3 completes it.

## Tests that pin this

- Stale `running` → `interrupted`.
- Missed `at` catches up once.
- Overlapping job skipped.
- A job that ignores its timeout: no second instance starts and the slot is released only when it ends.
- Two drainers started by hand claim disjoint rows.
- Reminders fire under a frozen clock → notification row in the same transaction.

## Source

Build plan: §11 (all), SQLite rules (outbox drainer, single process, `core.job_runs_prune`), §1 (backup job), §7 (`crm.touch_count`), §10 (Jobs page), Step 1, Verification.
