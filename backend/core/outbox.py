"""Durable after-commit work (docs/agents/database-and-transactions.md, "Transaction composition").

A write that needs follow-up work after it commits calls `enqueue_in(conn, hook, payload)` in
its own transaction, so the row exists exactly when the write does. One drainer, the scheduler
job `core.outbox_drain`, claims rows one at a time and runs the hook's consumer:
- local consumer `fn(conn, payload)`: its DB effects and `processed_at` commit in one
  transaction, so it runs exactly once. It must use `_in` functions, never `transaction()`.
- external consumer `fn(outbox_id, payload)` (HTTP, LLM): runs outside any transaction and is
  at-least-once; use the outbox id as the idempotency key where the remote supports one.
A failure bumps `attempts` and backs off; after MAX_ATTEMPTS the row is dead (`dead_at`). A
claim older than CLAIM_TIMEOUT (a crashed drainer) is claimed again.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass

from backend.core import clock, db

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
CLAIM_TIMEOUT = 300  # seconds; the core.outbox_drain job timeout
BACKOFF = 30  # seconds before the first retry, doubling after each failure


@dataclass(frozen=True)
class Consumer:
    fn: Callable
    external: bool


class ClaimLost(RuntimeError):
    """Another drainer re-claimed this row after our claim went stale."""


_CONSUMERS: dict[str, Consumer] = {}


def register(hook: str, fn: Callable, *, external: bool = False) -> None:
    if hook in _CONSUMERS:
        raise ValueError(f"Outbox hook {hook!r} already has a consumer")
    _CONSUMERS[hook] = Consumer(fn, external)


def clear() -> None:
    _CONSUMERS.clear()


def enqueue_in(conn: db.Conn, hook: str, payload: dict) -> int:
    now = clock.now_iso()
    cur = conn.execute(
        "INSERT INTO core_outbox (hook, payload, created_at, available_at) VALUES (?, ?, ?, ?)",
        (hook, json.dumps(payload), now, now),
    )
    db.mark_outbox_pending()
    return cur.lastrowid


def claim() -> dict | None:
    """Atomically claim the oldest due row, or None when nothing is claimable."""
    with db.transaction() as conn:
        now, stale = clock.now_iso(), clock.ago(CLAIM_TIMEOUT)
        row = conn.execute(
            """SELECT id FROM core_outbox
                WHERE processed_at IS NULL AND dead_at IS NULL AND available_at <= ?
                  AND (claimed_at IS NULL OR claimed_at < ?)
                ORDER BY id LIMIT 1""",
            (now, stale),
        ).fetchone()
        if row is None:
            return None
        cur = conn.execute(
            "UPDATE core_outbox SET claimed_at = ? WHERE id = ? AND (claimed_at IS NULL OR claimed_at < ?)",
            (now, row["id"], stale),
        )
        if cur.rowcount != 1:
            return None
        return dict(conn.execute("SELECT * FROM core_outbox WHERE id = ?", (row["id"],)).fetchone())


def _mark_processed_in(conn: db.Conn, row: dict) -> None:
    cur = conn.execute(
        "UPDATE core_outbox SET processed_at = ?, last_error = NULL WHERE id = ? AND claimed_at = ?",
        (clock.now_iso(), row["id"], row["claimed_at"]),
    )
    if cur.rowcount != 1:
        raise ClaimLost(f"outbox row {row['id']} was claimed by another drainer")


def process(row: dict) -> bool:
    """Run one claimed row's consumer. True when it was processed."""
    consumer = _CONSUMERS.get(row["hook"])
    payload = json.loads(row["payload"])
    try:
        if consumer is None:
            raise LookupError(f"no consumer registered for outbox hook {row['hook']!r}")
        if consumer.external:
            consumer.fn(row["id"], payload)
            with db.transaction() as conn:
                _mark_processed_in(conn, row)
        else:
            with db.transaction() as conn:
                consumer.fn(conn, payload)
                _mark_processed_in(conn, row)
        return True
    except ClaimLost:
        logger.warning("outbox row %s: claim lost to another drainer", row["id"])
        return False
    except Exception as e:
        _fail(row, e)
        return False


def _fail(row: dict, error: Exception) -> None:
    attempts = row["attempts"] + 1
    dead = attempts >= MAX_ATTEMPTS
    logger.warning("outbox row %s (%s) failed, attempt %s: %r", row["id"], row["hook"], attempts, error)
    with db.transaction() as conn:
        conn.execute(
            """UPDATE core_outbox SET attempts = ?, last_error = ?, claimed_at = NULL, available_at = ?, dead_at = ?
                WHERE id = ? AND claimed_at = ?""",
            (
                attempts, repr(error)[:2000], clock.later(BACKOFF * 2 ** (attempts - 1)),
                clock.now_iso() if dead else None, row["id"], row["claimed_at"],
            ),
        )


def drain(cancel: threading.Event | None = None) -> int:
    """Process claimable rows until none are left (or cancel is set). Returns how many succeeded.
    Never call it inside a transaction."""
    done = 0
    while not (cancel and cancel.is_set()):
        row = claim()
        if row is None:
            break
        done += process(row)
    return done
