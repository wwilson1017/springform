import asyncio

import pytest

from backend.apps.example import service as widgets
from backend.apps.example.models import WidgetIn
from backend.core import db, preview, registry, scheduler
from backend.core.auth.deps import User
from backend.core.files import service as files, storage


def _samples():
    tables = ["core_people", "core_organizations"]
    tables += [t for app in registry.installed() for t in app.modules["seed"].RESET_TABLES]
    return {table: db.rows(f'SELECT * FROM "{table}" ORDER BY rowid') for table in tables}


def _upload(user):
    widget = widgets.create_widget(user, WidgetIn(name="Visitor widget"))
    file = files.attach(user, "example.widget", widget["id"], "visitor.txt", b"visitor upload")
    return widget, file, storage.blob_path(file["sha256"])


def test_reset_restores_samples_and_removes_recent_uploads(app, monkeypatch, freeze):
    monkeypatch.setenv("PREVIEW_MODE", "1")
    freeze("2026-11-14T09:00:00Z")
    registry.seed_apps()
    preview.seed()
    before = _samples()
    admin = User.from_row(db.one("SELECT * FROM core_users WHERE role = 'admin'"))
    widget, file, path = _upload(admin)
    with db.transaction() as conn:
        conn.execute("UPDATE example_widgets SET name = 'Edited' WHERE id = 1")
    assert path.is_file()
    hooks = []
    original_hooks = registry.run_startup_hooks

    def startup():
        hooks.append(db.in_transaction())
        original_hooks()

    monkeypatch.setattr(registry, "run_startup_hooks", startup)
    assert preview.reset() == {"files": 1}
    assert _samples() == before
    assert db.one("SELECT id FROM example_widgets WHERE id = ?", (widget["id"],)) is None
    assert db.rows("SELECT * FROM core_files") == []
    assert db.rows("SELECT * FROM core_file_blobs") == []
    assert not list(storage.root().glob("??/*"))
    assert not path.exists()
    assert hooks == [False]


def test_non_preview_reset_changes_nothing(app, make_user):
    user = make_user("admin")
    widget, file, path = _upload(user)
    before = _samples()
    assert preview.reset() == {"skipped": "not_preview"}
    assert _samples() == before
    assert db.one("SELECT * FROM example_widgets WHERE id = ?", (widget["id"],)) == widget
    assert files.list_for(user, "example.widget", widget["id"]) == [file]
    assert path.read_bytes() == b"visitor upload"


@pytest.mark.parametrize("manual", [False, True])
def test_reset_keeps_history_and_runs_once_per_day(app, monkeypatch, freeze, manual):
    monkeypatch.setenv("PREVIEW_MODE", "1")
    preview.seed()
    job = scheduler.jobs()["core.preview_reset"]
    assert job.at == "09:00"
    assert job.fn is preview.reset

    def runs():
        return db.rows("SELECT id, status, scheduled_for FROM core_job_runs WHERE job = ? ORDER BY id", (job.name,))

    async def go():
        freeze("2026-11-14T08:59:00Z")
        runner = scheduler.Scheduler({job.name: job})
        await runner.tick_once()
        assert runs() == []
        freeze("2026-11-14T09:01:00Z")
        if manual:
            assert await runner.run_now(job.name)
        else:
            await runner.tick_once()
        await runner.wait_idle()
        first = runs()
        assert len(first) == 1 and first[0]["status"] == "ok"
        await runner.tick_once()
        await runner.wait_idle()
        assert runs() == first
        freeze("2026-11-15T09:01:00Z")
        await runner.tick_once()
        await runner.wait_idle()
        assert runs() == first + [{"id": first[0]["id"] + 1, "status": "ok", "scheduled_for": "2026-11-15"}]

    asyncio.run(go())


def test_failed_reset_keeps_uploaded_bytes(app, make_user, monkeypatch):
    user = make_user("admin")
    widget, file, path = _upload(user)
    monkeypatch.setenv("PREVIEW_MODE", "1")

    def fail(conn, *, keep_job_runs):
        conn.execute("DELETE FROM core_files")
        raise RuntimeError("reset failed")

    monkeypatch.setattr(registry, "factory_reset_in", fail)
    with pytest.raises(RuntimeError, match="reset failed"):
        preview.reset()
    assert files.list_for(user, "example.widget", widget["id"]) == [file]
    assert path.read_bytes() == b"visitor upload"
