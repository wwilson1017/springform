"""The one SQLite database: connections, the write transaction, startup checks, migrations.

Rules (docs/agents/database-and-transactions.md):
- Every write goes through `transaction()`: a process-wide lock plus BEGIN IMMEDIATE, committed
  or rolled back as a unit. It is never nested; code that runs inside a caller's transaction
  takes `conn` (the `_in` functions).
- Reads use this thread's connection (`get_conn()`, `rows()`, `one()`). Inside a transaction the
  same thread gets the same connection, so a read there sees the transaction's own writes.
- No network or LLM call inside `transaction()`.

This is the only module that imports sqlite3; everything else uses `db.sqlite3`.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import re
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import Version

from backend.core import REPO_ROOT, VERSION
from backend.core.clock import now_iso

try:
    import pysqlite3 as sqlite3  # dev/CI: a SQLite with FTS5, newer than the system one
except ImportError:  # the Docker image links the stdlib module against its own SQLite
    import sqlite3

logger = logging.getLogger(__name__)

Conn = sqlite3.Connection
MIN_SQLITE = (3, 51, 3)
DB_FILENAME = "springform.sqlite"
CORE_MIGRATIONS = Path(__file__).resolve().parent / "migrations"
APPS_DIR = REPO_ROOT / "backend" / "apps"
_MIGRATION_NAME = re.compile(r"^\d{14}_[a-z0-9_]+\.sql$")
_NO_DROP = re.compile(r"\bDROP\s+(TABLE|COLUMN)\b|\bRENAME\b", re.IGNORECASE)


class NestedTransaction(RuntimeError):
    """`transaction()` was opened while this thread's connection was already in one."""


class MigrationError(RuntimeError):
    """Startup must stop: a migration failed, changed after it was applied, or an app is incompatible."""


_path: Path | None = None
_data_dir: Path | None = None
_generation = 0  # bumped by close() so threads drop stale connections
_local = threading.local()
_connections: list[Conn] = []
_state_lock = threading.Lock()
_write_lock = threading.Lock()
_lock_file = None
_commit_nudge: Callable[[], None] | None = None


def connect(path: Path | str) -> Conn:
    # isolation_level=None: no implicit transactions; transaction() issues BEGIN IMMEDIATE itself.
    conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init(data_dir: Path | str, *, lock: bool = True) -> None:
    """Open the database under `data_dir`. Refuses to start when the directory is not writable,
    when another process holds the data directory (lock=True), or when SQLite is too old."""
    global _path, _data_dir
    close()
    data_dir = Path(data_dir)
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        probe = data_dir / ".write-test"
        probe.write_bytes(b"")
        probe.unlink()
    except OSError as e:
        raise RuntimeError(
            f"DATA_DIR ({data_dir.resolve()}) is not writable: {e}. "
            "Mount a persistent volume there, or point DATA_DIR at a writable directory."
        ) from None
    if lock:
        _acquire_lock(data_dir)
    _path, _data_dir = data_dir / DB_FILENAME, data_dir
    assert_sqlite(get_conn())
    logger.info("Database at %s", _path)


def _acquire_lock(data_dir: Path) -> None:
    global _lock_file
    f = open(data_dir / ".springform.lock", "a")  # noqa: SIM115 — held for the process lifetime
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.close()
        raise RuntimeError(
            f"Another Springform process is using {data_dir.resolve()}. "
            "Run exactly one process (uvicorn --workers 1) per data directory."
        ) from None
    _lock_file = f


def data_dir() -> Path:
    if _data_dir is None:
        raise RuntimeError("Database not initialized; call db.init() first")
    return _data_dir


def assert_sqlite(conn: Conn) -> None:
    """SQLite >= 3.51.3 (WAL-reset corruption fix) with FTS5, read from the connection in use."""
    version = conn.execute("SELECT sqlite_version()").fetchone()[0]
    if not fts5_enabled(conn):
        raise RuntimeError(f"SQLite {version} was built without FTS5; Springform needs it for search.")
    if tuple(int(p) for p in version.split(".")) < MIN_SQLITE:
        wanted = ".".join(map(str, MIN_SQLITE))
        message = f"SQLite {version} is older than {wanted} (the WAL-reset corruption fix)."
        # simplification: pysqlite3-binary 0.5.4.post2 (dev/CI) bundles 3.51.1, so only the Docker
        # image (SPRINGFORM_REQUIRE_SQLITE=1) refuses; make this unconditional once a >= 3.51.3 wheel ships.
        if os.environ.get("SPRINGFORM_REQUIRE_SQLITE") == "1":
            raise RuntimeError(message)
        logger.warning("%s Fine for development; production images must not run this.", message)


def fts5_enabled(conn: Conn) -> bool:
    return any(r[0] == "ENABLE_FTS5" for r in conn.execute("PRAGMA compile_options"))


def get_conn() -> Conn:
    """This thread's connection."""
    if _path is None:
        raise RuntimeError("Database not initialized; call db.init() first")
    if getattr(_local, "generation", None) != _generation:
        conn = connect(_path)
        with _state_lock:
            _connections.append(conn)
        _local.conn, _local.generation = conn, _generation
    return _local.conn


def log_db() -> Conn:
    """Where job and request logs go. One file in v0.1; the seam lets a later release split it out."""
    return get_conn()


def close() -> None:
    """Close every thread's connection and release the data-dir lock (shutdown, tests)."""
    global _path, _data_dir, _generation, _lock_file
    with _state_lock:
        for conn in _connections:
            conn.close()
        _connections.clear()
        _generation += 1
        _path = _data_dir = None
    if _lock_file is not None:
        _lock_file.close()  # closing the descriptor releases the flock
        _lock_file = None


def in_transaction() -> bool:
    """True when this thread's connection is inside a transaction."""
    conn = getattr(_local, "conn", None)
    return conn is not None and getattr(_local, "generation", None) == _generation and conn.in_transaction


@contextmanager
def transaction() -> Iterator[Conn]:
    """The one write path: write lock + BEGIN IMMEDIATE; COMMIT, or ROLLBACK on any exception.

    The lock is per process; another process on the same file (the CLI) is serialized by
    SQLite itself, since BEGIN IMMEDIATE waits up to busy_timeout for the other writer."""
    conn = get_conn()
    if conn.in_transaction:
        raise NestedTransaction(
            "transaction() is already open on this thread; pass conn to an _in function instead"
        )
    with _write_lock:
        _local.outbox_pending = False
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.execute("COMMIT")  # inside the try: a failed COMMIT (deferred FK) rolls back too
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            _local.outbox_pending = False
            raise
    if getattr(_local, "outbox_pending", False):
        _local.outbox_pending = False
        _nudge()


def mark_outbox_pending() -> None:
    """Called by outbox.enqueue_in: nudge the drainer once this transaction commits."""
    _local.outbox_pending = True


def set_commit_nudge(fn: Callable[[], None] | None) -> None:
    """The scheduler installs the function that wakes the outbox drainer."""
    global _commit_nudge
    _commit_nudge = fn


def _nudge() -> None:
    # Fire-and-forget: the transaction is committed, so nothing here may make it look failed.
    try:
        if _commit_nudge is not None:
            _commit_nudge()
    except Exception:
        logger.debug("outbox nudge failed", exc_info=True)


def rows(sql: str, params: tuple | list | dict = ()) -> list[dict]:
    return [dict(r) for r in get_conn().execute(sql, params)]


def one(sql: str, params: tuple | list | dict = ()) -> dict | None:
    row = get_conn().execute(sql, params).fetchone()
    return dict(row) if row is not None else None


# ── Migrations ────────────────────────────────────────────────────────────────


def app_dirs(apps_dir: Path = APPS_DIR) -> list[Path]:
    """Installed apps: folders under apps_dir that carry an app.json."""
    return sorted(p.parent for p in apps_dir.glob("*/app.json"))


def migration_files(app_dirs_: list[Path], core_dir: Path = CORE_MIGRATIONS) -> list[Path]:
    """Core migrations first, then every app's, ordered by (timestamp, path)."""
    core = sorted(core_dir.glob("*.sql"))
    apps = sorted((f for d in app_dirs_ for f in d.glob("migrations/*.sql")), key=lambda p: (p.name[:14], str(p)))
    return core + apps


def lint_core_migration(sql: str) -> list[str]:
    """Within a major version core never drops or renames (docs: core schema compatibility).
    A major release's `*_baseline.sql` is exempt: migrate skips the lint for it."""
    code = "\n".join(line.split("--", 1)[0] for line in sql.splitlines())
    return sorted({m.group(0).upper() for m in _NO_DROP.finditer(code)})


def check_requires_core(app_dirs_: list[Path], version: str = VERSION) -> None:
    for d in app_dirs_:
        spec = json.loads((d / "app.json").read_text(encoding="utf-8")).get("requires_core")
        try:
            ok = bool(spec) and SpecifierSet(spec).contains(Version(version), prereleases=True)
        except InvalidSpecifier:
            ok = False
        if not ok:
            raise MigrationError(
                f"App '{d.name}' requires core {spec!r}, but this is Springform {version}. "
                "Upgrade the app or install a matching Springform release."
            )


def migrate(app_dirs_: list[Path] | None = None, core_dir: Path = CORE_MIGRATIONS) -> list[str]:
    """Apply pending migrations, one transaction per file. Returns the filenames applied.

    Startup only. Fails (MigrationError) when an installed app's requires_core excludes this
    version (checked before anything is applied), when an applied file has changed, when a file
    is misnamed, or when a core migration drops or renames."""
    app_dirs_ = app_dirs(APPS_DIR) if app_dirs_ is None else app_dirs_
    check_requires_core(app_dirs_)
    files = migration_files(app_dirs_, core_dir)
    for f in files:
        if not _MIGRATION_NAME.match(f.name):
            raise MigrationError(f"Migration {f} is misnamed; expected YYYYMMDDHHMMSS_<slug>_<name>.sql")
    names = [f.name for f in files]
    if len(set(names)) != len(names):
        raise MigrationError("Two migration files share a filename; prefix app migrations with the slug")

    conn = get_conn()
    applied_now: list[str] = []
    with _write_lock:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS _migrations_applied ("
            "filename TEXT PRIMARY KEY, sha256 TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        applied = {r["filename"]: r["sha256"] for r in conn.execute("SELECT filename, sha256 FROM _migrations_applied")}
        for f in files:
            sql = f.read_text(encoding="utf-8")
            digest = hashlib.sha256(sql.encode()).hexdigest()
            if f.name in applied:
                if applied[f.name] != digest:
                    raise MigrationError(f"Migration {f.name} changed after it was applied; add a new migration instead")
                continue
            is_core = f.parent.resolve() == core_dir.resolve()
            if is_core and not f.name.endswith("_baseline.sql") and (found := lint_core_migration(sql)):
                raise MigrationError(f"Core migration {f.name} uses {', '.join(found)}; core schema changes are additive")
            logger.info("Applying migration %s", f.name)
            try:
                conn.executescript(
                    f"BEGIN IMMEDIATE;\n{sql}\n;\n"
                    f"INSERT INTO _migrations_applied (filename, sha256, applied_at) "
                    f"VALUES ('{f.name}', '{digest}', '{now_iso()}');\nCOMMIT;"
                )
            except Exception as e:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise MigrationError(f"Migration {f.name} failed: {e}") from e
            applied_now.append(f.name)
    return applied_now
