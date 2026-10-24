import json
import re
import shutil
from pathlib import Path

import httpx
import pytest

from backend.core import REPO_ROOT, clock, db as core_db
from backend.core.db import MigrationError, NestedTransaction


def _app(root: Path, slug: str, migrations: dict[str, str], requires_core: str = ">=0.1,<1") -> Path:
    app_dir = root / slug
    (app_dir / "migrations").mkdir(parents=True)
    (app_dir / "app.json").write_text(json.dumps({"slug": slug, "requires_core": requires_core}))
    for name, sql in migrations.items():
        (app_dir / "migrations" / name).write_text(sql)
    return app_dir


def _tables() -> set[str]:
    return {r["name"] for r in core_db.rows("SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_nested_transaction_raises(db):
    with db.transaction():
        with pytest.raises(NestedTransaction):
            with db.transaction():
                pass


def test_exception_rolls_the_whole_transaction_back(db):
    with pytest.raises(RuntimeError):
        with db.transaction() as conn:
            conn.execute("INSERT INTO core_apps_state (slug, hidden) VALUES ('x', 1)")
            raise RuntimeError("boom")
    assert db.one("SELECT count(*) AS n FROM core_apps_state")["n"] == 0
    assert not db.in_transaction()


def test_second_process_on_the_data_dir_is_refused(db, tmp_path):
    with pytest.raises(RuntimeError, match="Another Springform process"):
        core_db._acquire_lock(tmp_path / "data")


def test_unwritable_data_dir_is_refused(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("")
    with pytest.raises(RuntimeError, match="not writable"):
        core_db.init(blocker / "data")


def test_migrations_order_core_first_then_timestamp(tmp_path):
    b = _app(tmp_path, "bbb", {"20261101000000_bbb_init.sql": ""})
    a = _app(tmp_path, "aaa", {"20261102000000_aaa_init.sql": "", "20261101000000_aaa_init.sql": ""})
    names = [f.name for f in core_db.migration_files([b, a])]
    assert all(n.startswith("20261020") and "_core_" in n for n in names[:-3])
    assert names[-3:] == ["20261101000000_aaa_init.sql", "20261101000000_bbb_init.sql", "20261102000000_aaa_init.sql"]


def test_changed_applied_migration_fails_startup(tmp_path):
    app_dir = _app(tmp_path / "apps", "fx", {"20261101000000_fx_init.sql": "CREATE TABLE fx_a (id INTEGER);"})
    core_db.init(tmp_path / "data")
    core_db.migrate([app_dir])
    assert core_db.migrate([app_dir]) == []  # idempotent
    (app_dir / "migrations" / "20261101000000_fx_init.sql").write_text("CREATE TABLE fx_a (id INTEGER, b TEXT);")
    with pytest.raises(MigrationError, match="changed after it was applied"):
        core_db.migrate([app_dir])


def test_failing_migration_leaves_no_partial_ddl(tmp_path):
    app_dir = _app(tmp_path / "apps", "fx", {
        "20261101000000_fx_init.sql": "CREATE TABLE fx_a (id INTEGER); INSERT INTO fx_missing VALUES (1);",
    })
    core_db.init(tmp_path / "data")
    with pytest.raises(MigrationError, match="fx_init.sql failed"):
        core_db.migrate([app_dir])
    assert "fx_a" not in _tables()
    applied = [r["filename"] for r in core_db.rows("SELECT filename FROM _migrations_applied")]
    assert applied == sorted(f.name for f in core_db.CORE_MIGRATIONS.glob("*.sql"))
    assert not core_db.get_conn().in_transaction


def test_requires_core_refusal_names_the_app_before_applying_anything(tmp_path):
    app_dir = _app(tmp_path / "apps", "oldapp", {"20261101000000_oldapp_init.sql": "CREATE TABLE oldapp_a (id INTEGER);"}, "<0.1")
    core_db.init(tmp_path / "data")
    with pytest.raises(MigrationError, match="App 'oldapp' requires core '<0.1'"):
        core_db.migrate([app_dir])
    assert _tables() == set()


def test_core_migration_may_not_drop_or_rename(tmp_path):
    assert core_db.lint_core_migration("ALTER TABLE core_x DROP COLUMN y;") == ["DROP COLUMN"]
    assert core_db.lint_core_migration("DROP TABLE core_x;\nALTER TABLE a RENAME TO b;") == ["DROP TABLE", "RENAME"]
    assert core_db.lint_core_migration("-- we never DROP TABLE or RENAME here\nDROP INDEX core_i;") == []
    core_dir = tmp_path / "core"
    shutil.copytree(core_db.CORE_MIGRATIONS, core_dir)
    (core_dir / "20261020000200_core_bad.sql").write_text("ALTER TABLE core_settings RENAME TO core_prefs;")
    core_db.init(tmp_path / "data")
    with pytest.raises(MigrationError, match="core_bad.sql uses RENAME"):
        core_db.migrate([], core_dir)
    assert "core_settings" in _tables()


def test_no_sql_reads_the_database_clock():
    pattern = re.compile(r"CURRENT_(TIMESTAMP|DATE|TIME)\b|\b(datetime|date|time|julianday|strftime|unixepoch)\([^)]*'now'", re.I)
    this_file = Path(__file__).resolve()
    offenders = [
        str(p.relative_to(REPO_ROOT)) for p in (REPO_ROOT / "backend").rglob("*")
        if p.suffix in (".sql", ".py") and p.resolve() != this_file and pattern.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == [], "timestamps come from core.clock.now_iso(), never SQL"


def test_network_inside_a_transaction_is_refused(db):
    with db.transaction():
        with pytest.raises(AssertionError, match="network call inside transaction"):
            httpx.Client().get("http://127.0.0.1:9/")


def test_sqlite_assertion(db, monkeypatch, caplog):
    conn = core_db.get_conn()
    assert core_db.fts5_enabled(conn)
    monkeypatch.setattr(core_db, "MIN_SQLITE", (99, 0, 0))
    core_db.assert_sqlite(conn)
    assert "older than 99.0.0" in caplog.text
    monkeypatch.setenv("SPRINGFORM_REQUIRE_SQLITE", "1")
    with pytest.raises(RuntimeError, match="older than 99.0.0"):
        core_db.assert_sqlite(conn)


def test_clock_canonical_and_normalize(freeze):
    freeze("2026-11-02T09:00:00Z")
    assert clock.now_iso() == "2026-11-02T09:00:00Z"
    assert clock.ago(3600) == "2026-11-02T08:00:00Z"
    assert clock.normalize("2026-03-08T02:30:00", "America/Chicago") == "2026-03-08T08:30:00Z"  # DST gap
    assert clock.normalize("2026-07-01T12:00:00.123456+02:00") == "2026-07-01T10:00:00Z"
    assert clock.normalize("2026-07-01T12:00:00Z") == "2026-07-01T12:00:00Z"
    with pytest.raises(ValueError):
        clock.normalize("next tuesday")
