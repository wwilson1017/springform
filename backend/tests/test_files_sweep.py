"""The files sweep: expiry, backup pinning, the publication interleaving, missing and orphan files."""

import json
import os
import threading
import time
from datetime import timedelta

import pytest

from backend.core import clock, db as core_db
from backend.core.files import api as files_api, jobs, storage, thumbnails

W = "example.widget"


def _widget(client) -> int:
    return client.post("/api/example/widgets", json={"name": "Gear"}).json()["id"]


def _blob(sha: str) -> dict | None:
    return core_db.one("SELECT unreferenced_since, missing_at FROM core_file_blobs WHERE sha256 = ?", (sha,))


def _unreferenced_blob(member, at: str) -> str:
    """A blob whose only file was deleted at `at`."""
    clock.freeze(at)
    f = files_api.attach(member.principal, W, _widget(member), "old.txt", b"old bytes")
    files_api.delete(member.principal, f["id"])
    assert _blob(f["sha256"])["unreferenced_since"] == at
    return f["sha256"]


def test_fresh_blob_survives_and_an_unreferenced_one_goes_after_seven_days(login_as, freeze):
    member = login_as("member")
    freeze("2026-11-01T00:00:00Z")
    kept = files_api.attach(member.principal, W, _widget(member), "keep.txt", b"keep")
    sha = _unreferenced_blob(member, "2026-11-01T00:00:00Z")

    freeze("2026-11-07T00:00:00Z")  # 6 days
    assert jobs.sweep()["expired"] == 0
    assert _blob(sha) is not None and storage.blob_path(sha).is_file()

    freeze("2026-11-09T00:00:00Z")  # 8 days
    assert jobs.sweep()["expired"] == 1
    assert _blob(sha) is None and not storage.blob_path(sha).exists()
    assert _blob(kept["sha256"]) is not None and storage.blob_path(kept["sha256"]).is_file()


def test_a_blob_listed_in_a_retained_backup_manifest_survives(login_as, freeze):
    member = login_as("member")
    sha = _unreferenced_blob(member, "2026-11-01T00:00:00Z")
    freeze("2026-11-20T00:00:00Z")
    backups = core_db.data_dir() / "backups"
    backups.mkdir()
    (backups / "2026-11-02T030000Z.manifest.json").write_text(json.dumps({"snapshot": "x.sqlite", "blobs": [sha]}))
    assert jobs.sweep()["expired"] == 0 and storage.blob_path(sha).is_file()

    (backups / "broken.manifest.json").write_text("{}")  # unreadable pins fail closed
    with pytest.raises(KeyError):
        jobs.sweep()
    assert _blob(sha) is not None

    for p in backups.iterdir():
        p.unlink()
    assert jobs.sweep()["expired"] == 1 and not storage.blob_path(sha).exists()


def test_sweep_holding_the_lock_then_an_upload_of_the_same_bytes_republishes(login_as, monkeypatch):
    member = login_as("member")
    w = _widget(member)
    sha = _unreferenced_blob(member, clock.to_iso(clock.now() - timedelta(days=8)))
    clock.freeze(None)  # real time from here, so the staged upload's tmp file is fresh

    in_lock, staged, go = threading.Event(), threading.Event(), threading.Event()
    real_pinned = jobs.pinned_blobs

    def pinned_while_holding_the_lock():
        in_lock.set()
        assert go.wait(5)
        return real_pinned()

    monkeypatch.setattr(jobs, "pinned_blobs", pinned_while_holding_the_lock)
    monkeypatch.setattr(thumbnails, "make", lambda path: staged.set())  # runs between staging and the transaction
    out: dict = {}
    sweeper = threading.Thread(target=lambda: out.update(sweep=jobs.sweep()))
    uploader = threading.Thread(target=lambda: out.update(file=files_api.attach(member.principal, W, w, "new.txt", b"old bytes")))

    sweeper.start()
    assert in_lock.wait(5)  # the sweep is inside its transaction
    uploader.start()
    assert staged.wait(5)  # the upload is staged and hashed
    uploader.join(0.3)
    assert uploader.is_alive()  # ...and cannot publish while the sweep holds the lock
    go.set()
    sweeper.join(5)
    uploader.join(5)

    assert out["sweep"]["expired"] == 1  # the sweep deleted the old blob first
    assert out["file"]["sha256"] == sha  # then the upload republished it
    assert _blob(sha) == {"unreferenced_since": None, "missing_at": None}
    assert storage.blob_path(sha).read_bytes() == b"old bytes"
    assert files_api.list_for(member.principal, W, w) == [out["file"]]


def test_a_missing_file_is_410_flagged_by_the_sweep_and_healed_by_reupload(login_as):
    member = login_as("member")
    w = _widget(member)
    upload = lambda: member.post(  # noqa: E731
        "/api/core/files", data={"entity_type": W, "entity_id": str(w)}, files={"file": ("a.txt", b"precious", "text/plain")}
    )
    f = upload().json()
    storage.blob_path(f["sha256"]).unlink()

    r = member.get(f"/api/core/files/{f['id']}/download")
    assert (r.status_code, r.json()) == (410, {"detail": "file_missing"})
    with pytest.raises(storage.Gone):
        files_api.read_bytes(member.principal, f["id"])
    assert jobs.sweep()["missing"] == 1
    assert _blob(f["sha256"])["missing_at"] is not None

    assert upload().status_code == 200  # the same bytes again: existing row, file back in place
    assert _blob(f["sha256"])["missing_at"] is None
    assert member.get(f"/api/core/files/{f['id']}/download").content == b"precious"


def test_sweep_removes_stale_orphans_and_tmp_uploads_only(db):
    old = time.time() - 2 * 86400
    paths = {
        "stale_orphan": storage.root() / "ab" / ("ab" + "0" * 62),
        "fresh_orphan": storage.root() / "cd" / ("cd" + "1" * 62),
        "stale_tmp": storage.tmp_dir() / "stale",
        "fresh_tmp": storage.tmp_dir() / "fresh",
    }
    for name, p in paths.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
        if name.startswith("stale"):
            os.utime(p, (old, old))
    assert jobs.sweep() == {"expired": 0, "missing": 0, "orphans": 1, "tmp": 1}
    assert {name: p.exists() for name, p in paths.items()} == {
        "stale_orphan": False, "fresh_orphan": True, "stale_tmp": False, "fresh_tmp": True,
    }
