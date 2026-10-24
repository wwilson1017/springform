import hashlib
import json
import os
import shutil
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from cryptography.fernet import Fernet

from backend.core import VERSION, clock, db as core_db, scheduler, secrets
from backend.core.backup import jobs, service


def add_file(content: bytes, entity_id: int = 1) -> str:
    """A core_files row and its blob at the content-addressed path, as the files service leaves them."""
    sha = hashlib.sha256(content).hexdigest()
    path = core_db.data_dir() / "files" / sha[:2] / sha
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    now = clock.now_iso()
    with core_db.transaction() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO core_file_blobs (sha256, byte_size, created_at) VALUES (?, ?, ?)", (sha, len(content), now)
        )
        conn.execute(
            """INSERT INTO core_files (entity_type, entity_id, filename, mime_type, byte_size, sha256, created_at)
               VALUES ('example_widget', ?, 'note.txt', 'text/plain', ?, ?, ?)""",
            (entity_id, len(content), sha, now),
        )
    return sha


def _out() -> Path:
    return core_db.data_dir() / "backups"


def test_a_backup_is_a_complete_recovery_set(db):
    a, b = add_file(b"alpha"), add_file(b"beta")
    add_file(b"alpha", entity_id=2)  # the same blob on a second record is listed once
    row = service.run("manual")
    assert row["status"] == "ok" and row["error"] is None
    stamp = row["snapshot"].removesuffix(".sqlite")
    snapshot = _out() / row["snapshot"]
    assert sorted(p.name for p in _out().iterdir()) == [f"{stamp}.manifest.json", f"{stamp}.sqlite"]
    assert json.loads((_out() / row["manifest"]).read_text()) == {
        "version": 1,
        "springform_version": VERSION,
        "created_at": row["started_at"],
        "snapshot": {"filename": snapshot.name, "sha256": service.sha256_file(snapshot), "byte_size": snapshot.stat().st_size},
        "blobs": sorted([a, b]),
        "key_fingerprint": secrets.key_fingerprint(),
        "key_source": "file",
    }
    assert row["sha256"] == service.sha256_file(snapshot) and row["byte_size"] == snapshot.stat().st_size
    copy = core_db.sqlite3.connect(snapshot)
    assert copy.execute("SELECT count(*) FROM core_files").fetchone()[0] == 3
    copy.close()
    assert service.list_sets() == [{
        "stamp": stamp, "created_at": row["started_at"], "snapshot_bytes": snapshot.stat().st_size,
        "blob_count": 2, "status": "ok", "manifest_ok": True,
    }]


def test_keeps_the_newest_seven_sets_and_clears_abandoned_files(db, freeze):
    _out().mkdir()
    hour_ago = time.time() - 3700
    old_orphan, fresh_orphan, old_tmp = (_out() / n for n in ("20200101T000000Z.sqlite", "20200101T000001Z.sqlite", "x.sqlite.tmp"))
    for p in (old_orphan, fresh_orphan, old_tmp):
        p.write_bytes(b"partial")
    os.utime(old_orphan, (hour_ago, hour_ago))
    os.utime(old_tmp, (hour_ago, hour_ago))
    stamps = []
    for day in range(1, 10):
        freeze(f"2026-11-0{day}T03:00:00Z")
        stamps.append(service.run()["snapshot"].removesuffix(".sqlite"))
    assert sorted(p.name.removesuffix(".manifest.json") for p in _out().glob("*.manifest.json")) == stamps[2:]
    assert sorted(p.name for p in _out().glob("*.sqlite")) == [fresh_orphan.name] + [f"{s}.sqlite" for s in stamps[2:]]
    assert not old_orphan.exists() and not old_tmp.exists()
    assert [s["stamp"] for s in service.list_sets()][:2] == [stamps[-1], stamps[-2]]
    assert next(s for s in service.list_sets() if s["stamp"] == "20200101T000001Z")["manifest_ok"] is False


def test_low_free_space_skips_the_backup_and_says_why(db, monkeypatch):
    monkeypatch.setattr(shutil, "disk_usage", lambda path: SimpleNamespace(free=50 * 2**20))
    row = service.run()
    assert row["status"] == "skipped" and "low disk space: 50 MB free" in row["error"]
    assert service.list_sets() == [] and service.last_backup_at() is None


def test_the_job_never_raises(db):
    (core_db.data_dir() / "backups").write_text("a file where the backups directory should be")
    jobs.backup_job(threading.Event())
    row = core_db.one("SELECT status, error, snapshot FROM core_backups")
    assert row["status"] == "error" and "FileExistsError" in row["error"] and row["snapshot"] is None
    core_db.close()  # not even a database to record into
    assert service.run()["status"] == "error"


def test_one_backup_at_a_time(db):
    with service._running:
        assert service.run() is None
    assert core_db.one("SELECT count(*) AS n FROM core_backups")["n"] == 0


def test_health_reports_the_newest_complete_set_and_the_job_is_scheduled(client, freeze):
    assert client.get("/api/health").json()["last_backup_at"] is None
    freeze("2026-11-02T03:00:00Z")
    service.run()
    freeze("2026-11-03T03:00:00Z")
    newest = service.run()
    assert client.get("/api/health").json()["last_backup_at"] == "2026-11-03T03:00:00Z"
    (_out() / newest["manifest"]).unlink()  # a set without its manifest is not a backup
    assert client.get("/api/health").json()["last_backup_at"] == "2026-11-02T03:00:00Z"
    job = scheduler.jobs()["core.backup"]
    assert (job.at, job.app, job.fn) == ("03:00", "core", jobs.backup_job)


def test_backup_routes_are_admin_only(client, login_as):
    member = login_as("member")
    for method, path in [
        ("get", "/api/core/backups"), ("post", "/api/core/backups/run"), ("post", "/api/core/backups/key"),
        ("get", "/api/core/backups/20261101T030000Z/download"), ("get", "/api/core/backups/20261101T030000Z/manifest"),
    ]:
        assert getattr(member, method)(path).status_code == 403, path
        assert getattr(client, method)(path).status_code == 401, path


def test_back_up_now_then_list_download_and_read_the_manifest(login_as):
    admin = login_as("admin")
    r = admin.post("/api/core/backups/run")
    assert r.status_code == 202 and r.json()["status"] == "ok"
    stamp = r.json()["snapshot"].removesuffix(".sqlite")
    body = admin.get("/api/core/backups").json()
    assert [(s["stamp"], s["status"], s["manifest_ok"], s["blob_count"]) for s in body["sets"]] == [(stamp, "ok", True, 0)]
    assert body["last_backup_at"] == r.json()["started_at"] and body["last_run"]["id"] == r.json()["id"]
    assert (body["key_source"], body["key_shown"]) == ("file", False)

    download = admin.get(f"/api/core/backups/{stamp}/download")
    assert download.status_code == 200
    assert download.headers["content-disposition"] == f'attachment; filename="{stamp}.sqlite"'
    assert download.content == (_out() / f"{stamp}.sqlite").read_bytes()
    manifest = admin.get(f"/api/core/backups/{stamp}/manifest")
    assert manifest.json() == json.loads((_out() / f"{stamp}.manifest.json").read_text())
    for path in ("/api/core/backups/nope/download", "/api/core/backups/20990101T000000Z/download",
                 "/api/core/backups/20990101T000000Z/manifest"):
        assert admin.get(path).status_code == 404, path

    with service._running:  # the nightly job holds the guard
        r = admin.post("/api/core/backups/run")
    assert (r.status_code, r.json()) == (409, {"detail": "backup_in_progress"})


def test_the_key_is_shown_once(login_as):
    admin = login_as("admin")
    r = admin.post("/api/core/backups/key")
    assert r.status_code == 200
    assert r.json() == {"key_source": "file", "key": secrets.key().decode(), "fingerprint": secrets.key_fingerprint()}
    assert admin.get("/api/core/backups").json()["key_shown"] is True
    again = admin.post("/api/core/backups/key")
    assert (again.status_code, again.json()) == (410, {"detail": "key_already_shown"})


def test_an_environment_key_is_never_returned(login_as, monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("ENCRYPTION_KEY", key)
    admin = login_as("admin")
    for _ in range(2):
        r = admin.post("/api/core/backups/key")
        assert r.status_code == 200 and key not in r.text
        assert r.json() == {"key_source": "env", "fingerprint": secrets.key_fingerprint()}
    body = admin.get("/api/core/backups").json()
    assert (body["key_source"], body["key_shown"]) == ("env", False)
    row = admin.post("/api/core/backups/run").json()
    manifest = json.loads((_out() / row["manifest"]).read_text())
    assert (manifest["key_source"], manifest["key_fingerprint"]) == ("env", secrets.key_fingerprint())
    assert not (core_db.data_dir() / ".encryption-key").exists()
