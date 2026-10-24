"""The restore test (docs/agents/deploy.md §8): snapshot + files + key into an empty volume, boot,
open an attachment, decrypt a stored credential; a wrong key fails before anything is written."""

import shutil

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from backend.core import db as core_db, scheduler, secrets, settings
from backend.core.backup import restore, service
from backend.tests.test_backup_service import add_file

ATTACHMENT = b"%PDF-1.7 a signed quote"


def _backed_up_install() -> tuple[str, str]:
    """An install holding an encrypted provider key and an attachment, backed up. Returns (manifest, sha)."""
    settings.set_setting("ai.anthropic_key", "sk-test-restore", None, is_secret=True)
    assert core_db.one("SELECT value FROM core_settings WHERE key = 'ai.anthropic_key'")["value"].startswith("enc:v1:")
    sha = add_file(ATTACHMENT)
    row = service.run("manual")
    assert row["status"] == "ok"
    return str(core_db.data_dir() / "backups" / row["manifest"]), sha


def test_restore_into_an_empty_volume_boots_opens_the_attachment_and_decrypts(db, tmp_path, monkeypatch, capsys):
    manifest, sha = _backed_up_install()
    source = core_db.data_dir()
    fingerprint = secrets.key_fingerprint()
    core_db.close()
    target = tmp_path / "restored"

    assert restore.main([manifest, str(target), "--key-file", str(source / ".encryption-key")]) == 0
    assert "Restored" in capsys.readouterr().out
    assert sorted(p.name for p in target.iterdir()) == [".encryption-key", "files", "springform.sqlite"]

    monkeypatch.setenv("DATA_DIR", str(target))
    monkeypatch.setattr(scheduler, "jobs", lambda: {})  # boot without a catch-up backup racing the asserts
    from backend.main import create_app

    with TestClient(create_app()) as client:  # the real lifespan: lock, SQLite checks, migrations, seeds
        assert core_db.data_dir() == target
        health = client.get("/api/health").json()
        assert health["last_backup_at"] is None  # the restored volume holds no sets yet
        row = core_db.one("SELECT sha256, byte_size FROM core_files WHERE entity_type = 'example_widget'")
        assert row["sha256"] == sha
        assert (target / "files" / sha[:2] / sha).read_bytes() == ATTACHMENT
        assert secrets.key_fingerprint() == fingerprint
        assert settings.get_setting("ai.anthropic_key") == "sk-test-restore"


def test_a_wrong_key_fails_before_anything_is_written(db, tmp_path, monkeypatch, capsys):
    manifest, _ = _backed_up_install()
    right = core_db.data_dir() / ".encryption-key"
    wrong = tmp_path / "wrong.key"
    wrong.write_text(Fernet.generate_key().decode())
    target = tmp_path / "restored"

    assert restore.main([manifest, str(target), "--key-file", str(wrong)]) == 1
    assert "restore failed: wrong key" in capsys.readouterr().err
    with pytest.raises(restore.RestoreError, match="no key"):
        restore.restore(manifest, target)
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())  # wins at boot, so it is checked too
    with pytest.raises(restore.RestoreError, match="wrong key: ENCRYPTION_KEY"):
        restore.restore(manifest, target, key_file=right)
    assert not target.exists()


def test_restore_refuses_a_damaged_set_or_a_used_target(db, tmp_path):
    manifest, sha = _backed_up_install()
    source = core_db.data_dir()
    key = source / ".encryption-key"

    used = tmp_path / "used"
    used.mkdir()
    (used / "springform.sqlite").write_bytes(b"live data")
    with pytest.raises(restore.RestoreError, match="not empty"):
        restore.restore(manifest, used, key_file=key)

    elsewhere = tmp_path / "offsite"
    shutil.copytree(source / "files", elsewhere / "files")
    (source / "files" / sha[:2] / sha).write_bytes(b"bit rot")
    with pytest.raises(restore.RestoreError, match="1 of 1 files are missing or damaged"):
        restore.restore(manifest, tmp_path / "a", key_file=key)
    partial = restore.restore(manifest, tmp_path / "b", key_file=key, allow_missing_blobs=True)
    assert partial["missing_blobs"] == [sha] and (tmp_path / "b" / "springform.sqlite").is_file()
    whole = restore.restore(manifest, tmp_path / "c", key_file=key, files_from=elsewhere)
    assert whole["missing_blobs"] == [] and (tmp_path / "c" / "files" / sha[:2] / sha).read_bytes() == ATTACHMENT

    snapshot = source / "backups" / partial["snapshot"]
    snapshot.write_bytes(snapshot.read_bytes() + b"\0")
    with pytest.raises(restore.RestoreError, match="damaged: its sha256"):
        restore.restore(manifest, tmp_path / "d", key_file=key, files_from=elsewhere)
    assert not (tmp_path / "a").exists() and not (tmp_path / "d").exists()
