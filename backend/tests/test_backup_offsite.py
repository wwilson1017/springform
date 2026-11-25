"""The off-site copy against a local S3-compatible fake: upload order, restore from the bucket
(plain and age-encrypted), dedupe, prune, passphrase generations, failures and the routes."""

import importlib
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit
from xml.sax.saxutils import escape

import pytest

from backend.core import db as core_db, secrets, settings
from backend.core.backup import age, offsite, restore, service
from backend.core.errors import AppError, Conflict, Invalid
from backend.tests.test_backup_service import add_file

# pyrage (rage, an independent age implementation) is compiled and ships no type stubs.
pyrage = importlib.import_module("pyrage")
SECRET = "s3cr3t-Value-xyz"
PASSPHRASE = "correct horse battery"


class FakeS3:
    """Path-style S3: PUT, GET, DELETE, ListObjectsV2 two keys a page. `refuse` answers every call
    with it; `deny_reads` refuses only object GETs (listing still works)."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.log: list[tuple[str, str]] = []
        self.refuse: int | None = None
        self.deny_reads = False
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def _key(self) -> tuple[str, dict]:
                url = urlsplit(self.path)
                bucket, _, key = unquote(url.path).lstrip("/").partition("/")
                assert bucket == "bucket"
                return key, parse_qs(url.query)

            def _send(self, code: int, body: bytes = b"") -> None:
                self.send_response(code)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _refused(self) -> bool:
                if fake.refuse:
                    msg = f"<Error><Code>AccessDenied</Code><Message>bad key {SECRET}</Message></Error>"
                    self._send(fake.refuse, msg.encode())
                return bool(fake.refuse)

            def do_PUT(self):
                key, _ = self._key()
                assert "Transfer-Encoding" not in self.headers  # a signed length, never chunked
                body = self.rfile.read(int(self.headers["Content-Length"]))
                if self._refused():
                    return
                fake.objects[key] = body
                fake.log.append(("PUT", key))
                self._send(200)

            def do_DELETE(self):
                key, _ = self._key()
                if self._refused():
                    return
                fake.objects.pop(key, None)
                fake.log.append(("DELETE", key))
                self._send(204)

            def do_GET(self):
                key, q = self._key()
                if self._refused():
                    return
                if "list-type" not in q:
                    if fake.deny_reads:
                        return self._send(403, b"<Error><Code>AccessDenied</Code></Error>")
                    body = fake.objects.get(key)
                    return self._send(200, body) if body is not None else self._send(404)
                keys = sorted(k for k in fake.objects if k.startswith(q.get("prefix", [""])[0]))
                start = int(q.get("continuation-token", ["0"])[0])
                page, more = keys[start : start + 2], start + 2 < len(keys)
                xml = "<ListBucketResult>" + "".join(f"<Contents><Key>{escape(k)}</Key></Contents>" for k in page)
                xml += f"<IsTruncated>{'true' if more else 'false'}</IsTruncated>"
                xml += f"<NextContinuationToken>{start + 2}</NextContinuationToken>" if more else ""
                self._send(200, (xml + "</ListBucketResult>").encode())

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.endpoint = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, name="fake-s3")

    def puts(self) -> list[str]:
        return [k for m, k in self.log if m == "PUT"]


@pytest.fixture
def s3(db, monkeypatch):
    monkeypatch.setattr(age, "LOG_N", 10)  # pyrage reads any work factor; keep the suite fast
    fake = FakeS3()
    fake.thread.start()
    yield fake
    fake.server.shutdown()
    fake.server.server_close()
    fake.thread.join()


def configure(fake: FakeS3, passphrase: str | None = None, retention: int = 30, prefix: str = "shop") -> None:
    offsite.save_destination(
        None,
        endpoint=fake.endpoint,
        bucket="bucket",
        region="auto",
        prefix=prefix,
        access_key_id="AKID",
        secret_key=SECRET,
        retention=retention,
    )
    if passphrase:
        offsite.set_passphrase(None, passphrase)


def stamps(fake: FakeS3) -> list[str]:
    return sorted(k.split("/")[-1].split(".")[0] for k in fake.objects if ".manifest.json" in k)


def counts(conn) -> dict[str, int]:
    tables = [
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")
    ]
    return {t: conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}


@pytest.mark.parametrize("passphrase", [None, PASSPHRASE])
def test_a_set_restores_from_the_bucket_alone(s3, tmp_path, passphrase):
    a, b = add_file(b"alpha"), add_file(b"beta")
    settings.set_setting("core.example_secret", "provider-key", None, is_secret=True)
    configure(s3, passphrase)
    row = service.run("manual")
    assert row["status"] == "ok"
    stamp = row["snapshot"].removesuffix(".sqlite")

    gen = json.loads(
        secrets.decrypt(core_db.one("SELECT value FROM core_settings WHERE key = ?", (offsite.CONFIG,))["value"])
    ).get("generation")
    root, ext = (f"shop/age-{gen}/", ".age") if passphrase else ("shop/", "")
    blob_keys = [f"{root}files/{s[:2]}/{s}{ext}" for s in sorted([a, b])]
    # blobs, then the snapshot, then the manifest last; never the encryption key
    assert s3.puts() == [*blob_keys, f"{root}backups/{stamp}.sqlite{ext}", f"{root}backups/{stamp}.manifest.json{ext}"]
    assert not any("encryption-key" in k for k in s3.objects)
    status = offsite.status()
    # every byte this run put: blobs, snapshot and manifest
    assert status["last_error"] is None and status["last_success_bytes"] == sum(map(len, s3.objects.values()))
    assert status["encrypted"] is bool(passphrase) and status["stale"] is False

    pulled = tmp_path / "pulled"
    for key, body in s3.objects.items():
        rel = Path(key[len(root) :])
        if rel.suffix == ".age":
            assert passphrase and body.startswith(b"age-encryption.org/v1\n")
            body, rel = pyrage.passphrase.decrypt(body, passphrase), rel.with_suffix("")
        (pulled / rel).parent.mkdir(parents=True, exist_ok=True)
        (pulled / rel).write_bytes(body)
    key_file = tmp_path / "key"
    key_file.write_bytes((core_db.data_dir() / ".encryption-key").read_bytes())
    target = tmp_path / "restored"
    restore.restore(pulled / "backups" / f"{stamp}.manifest.json", target, key_file=key_file)

    copy = core_db.sqlite3.connect(target / core_db.DB_FILENAME)
    snap = core_db.sqlite3.connect(core_db.data_dir() / "backups" / row["snapshot"])
    assert counts(copy) == counts(snap) and counts(copy)["core_files"] == 2
    copy.close()
    snap.close()
    for sha, content in [(a, b"alpha"), (b, b"beta")]:
        assert (target / "files" / sha[:2] / sha).read_bytes() == content


@pytest.mark.parametrize("passphrase", [None, PASSPHRASE])
def test_blobs_go_up_once_and_prune_keeps_retention(s3, freeze, passphrase):
    shared, gone = add_file(b"shared"), add_file(b"only in the first set", entity_id=2)
    configure(s3, passphrase, retention=2)
    freeze("2026-11-01T03:00:00Z")
    service.run("job")
    with core_db.transaction() as conn:
        conn.execute("DELETE FROM core_files WHERE sha256 = ?", (gone,))
    for day in ("02", "03"):
        freeze(f"2026-11-{day}T03:00:00Z")
        service.run("job")
    blob_puts = [k for k in s3.puts() if "/files/" in k]
    assert len(blob_puts) == 2 and len(set(blob_puts)) == 2  # each blob uploaded once
    assert stamps(s3) == ["20261102T030000Z", "20261103T030000Z"]
    assert not any("20261101" in k for k in s3.objects)
    blobs = [k for k in s3.objects if "/files/" in k]
    assert len(blobs) == 1 and shared in blobs[0]  # the blob only the pruned set listed is gone
    assert offsite.status()["last_error"] is None


def test_a_new_passphrase_starts_a_new_root_and_old_sets_keep_theirs(s3, freeze):
    blob = add_file(b"shared attachment")
    configure(s3, "first passphrase")
    freeze("2026-11-01T03:00:00Z")
    service.run("job")
    offsite.set_passphrase(None, "second passphrase")
    freeze("2026-11-02T03:00:00Z")
    service.run("job")
    roots = sorted({k.split("/")[1] for k in s3.objects})
    assert len(roots) == 2 and all(r.startswith("age-") for r in roots)
    for root in roots:  # each root holds a whole set: its blob, snapshot and manifest
        keys = [k for k in s3.objects if k.split("/")[1] == root]
        assert len(keys) == 3 and any(blob in k for k in keys)
    old = next(k for k in s3.objects if "20261101" in k and "manifest" in k)
    assert json.loads(pyrage.passphrase.decrypt(s3.objects[old], "first passphrase"))["blobs"] == [blob]

    offsite.save_destination(
        None,
        endpoint=s3.endpoint,
        bucket="bucket",
        region="auto",
        prefix="shop",
        access_key_id="AKID",
        secret_key=None,
        retention=1,
    )  # a blank secret keeps the stored one
    offsite.clear_passphrase()
    freeze("2026-11-03T03:00:00Z")
    service.run("job")
    # retention 1: both encrypted roots aged out whole, blobs too; the new set is plain at the prefix
    assert sorted(s3.objects) == sorted(
        [
            f"shop/files/{blob[:2]}/{blob}",
            "shop/backups/20261103T030000Z.sqlite",
            "shop/backups/20261103T030000Z.manifest.json",
        ]
    )


def test_a_blob_missing_everywhere_blocks_the_set_and_the_prune(s3, freeze):
    configure(s3, retention=1)
    freeze("2026-11-01T03:00:00Z")
    service.run("job")
    first = dict(s3.objects)
    good = offsite.status()["last_success_at"]
    sha = add_file(b"lost before the upload")
    (core_db.data_dir() / "files" / sha[:2] / sha).unlink()
    freeze("2026-11-02T03:00:00Z")
    assert service.run("job")["status"] == "ok"  # the local set is fine; only the copy refuses
    assert s3.objects == first  # nothing published, nothing pruned
    status = offsite.status()
    assert status["last_success_at"] == good and "missing or damaged on this server" in status["last_error"]


def test_a_damaged_blob_blocks_the_set(s3, freeze):
    configure(s3)
    sha = add_file(b"the real attachment")
    (core_db.data_dir() / "files" / sha[:2] / sha).write_bytes(b"trunc")
    assert service.run("job")["status"] == "ok"
    assert s3.puts() == [] and "missing or damaged on this server" in offsite.status()["last_error"]


def test_prune_reads_manifests_by_suffix_even_under_a_manifest_like_prefix(s3, freeze):
    add_file(b"only in the first set")
    configure(s3, retention=1, prefix="old.manifest.json")
    freeze("2026-11-01T03:00:00Z")
    service.run("job")
    with core_db.transaction() as conn:
        conn.execute("DELETE FROM core_files")
    freeze("2026-11-02T03:00:00Z")
    service.run("job")
    assert sorted(s3.objects) == [
        "old.manifest.json/backups/20261102T030000Z.manifest.json",
        "old.manifest.json/backups/20261102T030000Z.sqlite",
    ]
    assert offsite.status()["last_error"] is None


def test_a_manifest_that_cannot_be_read_back_prunes_nothing(s3, freeze):
    configure(s3, retention=1)
    freeze("2026-11-01T03:00:00Z")
    service.run("job")
    s3.deny_reads = True
    freeze("2026-11-02T03:00:00Z")
    service.run("job")
    assert {"shop/backups/20261101T030000Z.sqlite", "shop/backups/20261101T030000Z.manifest.json"} <= set(s3.objects)
    status = offsite.status()
    assert status["last_success_at"] == "2026-11-01T03:00:00Z" and "403" in status["last_error"]
    with pytest.raises(AppError, match="403"):
        offsite.test_connection()  # a key that cannot read fails the test too


def test_an_unreadable_retained_manifest_keeps_blobs_and_is_an_error(s3, freeze, monkeypatch):
    sha = add_file(b"kept while an old manifest cannot be read")
    configure(s3, retention=2)
    freeze("2026-11-01T03:00:00Z")
    service.run("job")
    with core_db.transaction() as conn:
        conn.execute("DELETE FROM core_files")
    real = offsite._blobs_listed

    def old_unreadable(dest, key, passphrase):
        if "20261101" in key:
            raise ValueError("unreadable")
        return real(dest, key, passphrase)

    monkeypatch.setattr(offsite, "_blobs_listed", old_unreadable)
    for day in ("02", "03"):  # day 3 prunes day 1 and then reads day 2's manifest; day 2 read day 1's
        freeze(f"2026-11-{day}T03:00:00Z")
        service.run("job")
        if day == "02":
            assert any(sha in k for k in s3.objects)  # fail closed: the blob stays
            assert "could not be read back" in offsite.status()["last_error"]
    assert not any(sha in k for k in s3.objects) and offsite.status()["last_error"] is None


def test_prune_stops_when_cancelled(s3, freeze):
    configure(s3)
    for day in ("01", "02"):
        freeze(f"2026-11-{day}T03:00:00Z")
        service.run("job")
    before = dict(s3.objects)
    _, cfg = offsite._read()
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(AppError, match="stopped"):
        offsite._prune({**cfg, "retention": 1}, cancel)
    assert s3.objects == before


def test_listing_checks_before_each_page(s3):
    configure(s3)
    s3.objects = {f"shop/k{i}": b"" for i in range(5)}  # three pages of two
    calls: list[int] = []

    def check() -> None:
        calls.append(1)
        if len(calls) == 2:
            raise AppError("stopped")

    with pytest.raises(AppError, match="stopped"):
        offsite._destination(offsite._read()[1]).list_keys("shop/", check)
    assert len(calls) == 2  # page two was never requested


def test_an_encrypted_copy_needs_room_for_itself(s3, monkeypatch):
    configure(s3, PASSPHRASE)
    monkeypatch.setattr(offsite, "MIN_FREE_BYTES", 1 << 62)
    assert service.run("job")["status"] == "ok"  # service's own reserve is its own constant
    assert s3.puts() == [] and "Not enough disk space to encrypt" in offsite.status()["last_error"]


def test_a_bad_hostname_is_a_form_error():
    with pytest.raises(Invalid, match="host name"):
        offsite.validate_endpoint("https://" + "a" * 64 + ".example.com")


def test_a_snapshot_that_fails_quick_check_is_an_error_and_never_uploaded(s3, monkeypatch):
    configure(s3)
    monkeypatch.setattr(service, "QUICK_CHECK", "SELECT 'page 2 is never used'")
    row = service.run("manual")
    assert row["status"] == "error" and "quick_check" in row["error"]
    assert s3.puts() == [] and service.complete_stamps() == []


def test_settings_edits_wait_for_a_running_backup(s3, monkeypatch, freeze):
    configure(s3, retention=1)
    real = offsite._upload
    refused = []

    def edited_meanwhile(cfg, manifest, cancel):
        for edit in (
            lambda: offsite.set_passphrase(None, "set while uploading"),
            offsite.clear_passphrase,
            lambda: configure(s3, retention=30),
            offsite.clear_destination,
        ):
            with pytest.raises(Conflict, match="A backup is running"):
                edit()
            refused.append(edit)
        return real(cfg, manifest, cancel)

    monkeypatch.setattr(offsite, "_upload", edited_meanwhile)
    service.run("job")
    assert len(refused) == 4 and offsite.status()["last_error"] is None
    configure(s3, retention=30)  # once the run is over, edits go through


def test_the_routes(s3, client, login_as, freeze):
    admin, member = login_as("admin"), login_as("member")
    body = {
        "endpoint": s3.endpoint,
        "bucket": "bucket",
        "prefix": "/shop/",
        "access_key_id": "AKID",
        "secret_key": SECRET,
    }
    for method, path, kw in [
        ("put", "/api/core/backups/destination", {"json": body}),
        ("delete", "/api/core/backups/destination", {}),
        ("post", "/api/core/backups/destination/test", {}),
        ("put", "/api/core/backups/passphrase", {"json": {"passphrase": PASSPHRASE}}),
        ("delete", "/api/core/backups/passphrase", {}),
    ]:
        assert getattr(member, method)(path, **kw).status_code == 403, path
        assert getattr(client, method)(path, **kw).status_code == 401, path

    freeze("2026-11-01T09:00:00Z")
    r = admin.put("/api/core/backups/destination", json=body)
    assert r.status_code == 200
    assert {k: r.json()[k] for k in ("configured", "prefix", "region", "retention", "stale")} == {
        "configured": True,
        "prefix": "shop/",
        "region": "us-east-1",
        "retention": 30,
        "stale": False,
    }
    assert admin.put("/api/core/backups/passphrase", json={"passphrase": "short"}).status_code == 422
    with offsite.RUNNING:  # a backup is running: the edit is refused with a sentence to show
        r = admin.put("/api/core/backups/passphrase", json={"passphrase": PASSPHRASE})
    assert (r.status_code, r.json()["detail"]) == (409, offsite.BUSY)
    assert admin.put("/api/core/backups/passphrase", json={"passphrase": PASSPHRASE}).json()["encrypted"] is True
    for r in (admin.get("/api/core/backups"), admin.post("/api/core/backups/destination/test")):
        assert r.status_code == 200 and SECRET not in r.text and PASSPHRASE not in r.text
    assert s3.objects == {} and len(s3.puts()) == 1  # the test object went up and came down

    run = admin.post("/api/core/backups/run").json()
    stamp = run["snapshot"].removesuffix(".sqlite")
    download = admin.get(f"/api/core/backups/{stamp}/download")
    assert download.headers["content-disposition"] == f'attachment; filename="{stamp}.sqlite.age"'
    assert (
        pyrage.passphrase.decrypt(download.content, PASSPHRASE)
        == (core_db.data_dir() / "backups" / run["snapshot"]).read_bytes()
    )
    assert not list((core_db.data_dir() / "backups").glob("*.tmp"))
    # a fresh ciphertext each time: a resumed range would splice two files, so ranges are ignored
    ranged = admin.get(f"/api/core/backups/{stamp}/download", headers={"Range": "bytes=10-"})
    assert ranged.status_code == 200 and ranged.headers["accept-ranges"] == "none"
    assert pyrage.passphrase.decrypt(ranged.content, PASSPHRASE)
    # a 422 never echoes what was submitted
    for path, bad in [
        ("/api/core/backups/destination", {**body, "bucket": None}),
        ("/api/core/backups/passphrase", {"passphrase": "short12"}),
    ]:
        r = admin.put(path, json=bad)
        assert r.status_code == 422 and SECRET not in r.text and "short12" not in r.text and "input" not in r.text

    freeze("2026-11-03T09:00:01Z")  # 48 h after the upload, plus a second
    assert admin.get("/api/core/backups").json()["offsite"]["stale"] is True

    s3.refuse = 403
    r = admin.post("/api/core/backups/destination/test")
    assert r.status_code == 502 and "AccessDenied" in r.json()["detail"] and SECRET not in r.text
    assert admin.post("/api/core/backups/run").json()["status"] == "ok"  # the local set does not depend on the bucket
    assert "AccessDenied" in admin.get("/api/core/backups").json()["offsite"]["last_error"]
    s3.refuse = None

    # A config the install key cannot read is never taken for "no passphrase".
    with core_db.transaction() as conn:
        conn.execute("UPDATE core_settings SET value = 'enc:v1:garbage' WHERE key = ?", (offsite.CONFIG,))
    puts = len(s3.puts())
    off = admin.get("/api/core/backups").json()["offsite"]
    assert off["unreadable"] is True and off["configured"] is True and "can't be read" in off["last_error"]
    assert admin.get(f"/api/core/backups/{stamp}/download").status_code == 409
    assert admin.put("/api/core/backups/passphrase", json={"passphrase": PASSPHRASE}).status_code == 409
    admin.post("/api/core/backups/run")
    assert len(s3.puts()) == puts
    off = admin.delete("/api/core/backups/destination").json()
    assert (off["configured"], off["unreadable"], off["encrypted"]) == (False, False, False)
    plain = (core_db.data_dir() / "backups" / run["snapshot"]).read_bytes()
    assert admin.get(f"/api/core/backups/{stamp}/download").content == plain
    ranged = admin.get(f"/api/core/backups/{stamp}/download", headers={"Range": "bytes=10-"})
    assert ranged.status_code == 206 and ranged.content == plain[10:]  # the stable plain file still resumes
