"""The off-site copy: each good recovery set, uploaded to the admin's own S3-compatible bucket.

The bucket mirrors the volume, so a downloaded copy restores with `restore.py` unchanged:

    <prefix>files/<aa>/<sha>              attachments, content-addressed (uploaded once)
    <prefix>backups/<stamp>.sqlite        the snapshot
    <prefix>backups/<stamp>.manifest.json the manifest, uploaded last: the set is complete once it is there

With a backup passphrase every object is age-encrypted, ends in `.age`, and lives under its own
root `<prefix>age-<generation>/` (same layout inside). Setting a passphrase starts a new
generation, so a changed passphrase never overwrites an attachment an older retained set needs.
The encryption key (`.encryption-key`, ENCRYPTION_KEY) is never uploaded.

Config is one secret core_settings row (destination + optional passphrase): an unreadable row
(the encryption key changed) is never mistaken for "no passphrase". Outcomes go to a plain row
the Backups page and the admin banner read. No network call runs inside a transaction.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets as token
import threading
from pathlib import Path
from typing import Any

from backend.core import clock, db, secrets, settings
from backend.core.backup import age
from backend.core.backup.s3 import S3Destination, validate_endpoint
from backend.core.errors import AppError, Conflict, Invalid

logger = logging.getLogger(__name__)

CONFIG = "backups.offsite_config"  # secret: endpoint, bucket, region, prefix, access_key_id, secret_key, retention, passphrase, generation
STATUS = "backups.offsite"  # since, last_success_at, last_success_bytes, last_error
STALE_HOURS = 48
DESTINATION_FIELDS = ("endpoint", "bucket", "region", "prefix", "access_key_id", "retention")
_STAMP = r"\d{8}T\d{6}Z(?:-\d+)?"
_ROOT = r"(?:(age-[0-9a-f]{8})/)?"
SET_KEY = re.compile(rf"^{_ROOT}backups/({_STAMP})\.(sqlite|manifest\.json)(?:\.age)?$")
BLOB_KEY = re.compile(rf"^{_ROOT}files/[0-9a-f]{{2}}/([0-9a-f]{{64}})(?:\.age)?$")
SHA = re.compile(r"^[0-9a-f]{64}$")


class ConfigUnreadable(Conflict):
    default = "offsite_config_unreadable"


UNREADABLE = (
    "The off-site settings can't be read: the encryption key changed since they were saved. "
    "Remove the destination and set it, and the passphrase, again."
)


def _order(stamp: str) -> tuple[str, int]:
    base, _, n = stamp.partition("-")
    return base, int(n) if n.isdigit() else 1


def _read_in(conn: db.Conn) -> tuple[str | None, dict]:
    """(raw stored value, config). Raises ConfigUnreadable when the row exists but cannot be decrypted."""
    row = conn.execute("SELECT value FROM core_settings WHERE key = ?", (CONFIG,)).fetchone()
    if row is None:
        return None, {}
    plain = secrets.decrypt(row[0])
    if not plain:
        raise ConfigUnreadable(UNREADABLE)
    return row[0], json.loads(plain)


def _read() -> tuple[str | None, dict]:
    return _read_in(db.get_conn())


def _write_in(conn: db.Conn, cfg: dict, user_id: int | None) -> None:
    if cfg:
        settings.set_setting_in(conn, CONFIG, cfg, user_id, is_secret=True)
    else:
        conn.execute("DELETE FROM core_settings WHERE key = ?", (CONFIG,))


def _configured(cfg: dict) -> bool:
    return all(cfg.get(k) for k in ("endpoint", "bucket", "region", "access_key_id", "secret_key"))


def _root(cfg: dict) -> str:
    return cfg["prefix"] + (f"age-{cfg['generation']}/" if cfg.get("passphrase") else "")


def _destination(cfg: dict) -> S3Destination:
    return S3Destination(cfg["endpoint"], cfg["bucket"], cfg["region"], cfg["access_key_id"], cfg["secret_key"])


# --- settings (the Backups page) ---------------------------------------------------------------


def save_destination(
    user_id: int | None,
    *,
    endpoint: str,
    bucket: str,
    region: str,
    prefix: str,
    access_key_id: str,
    secret_key: str | None,
    retention: int,
) -> dict:
    """Lifted from CakeCRM `backups/service.py` save_destination. A blank secret keeps the stored one."""
    endpoint = validate_endpoint(endpoint)
    bucket, region, access_key_id = bucket.strip(), region.strip(), access_key_id.strip()
    prefix = prefix.strip().strip("/")
    prefix = prefix + "/" if prefix else ""
    if (
        not bucket
        or bucket in {".", ".."}
        or "/" in bucket
        or not region
        or not access_key_id
        or any(part in {".", ".."} for part in prefix.split("/"))
        or any(ord(c) < 32 for c in bucket + region + access_key_id + prefix)
    ):
        raise Invalid("Enter a bucket, region and access key id; the prefix cannot hold dot segments.")
    if not 1 <= retention <= 365:
        raise Invalid("Keep between 1 and 365 sets.")
    with db.transaction() as conn:
        _, cfg = _read_in(conn)
        secret = (secret_key or "").strip() or cfg.get("secret_key")
        if not secret:
            raise Invalid("Enter the bucket's secret access key.")
        new = {"endpoint": endpoint, "bucket": bucket, "region": region, "prefix": prefix}
        moved = any(cfg.get(k) != v for k, v in new.items())
        cfg.update(new, access_key_id=access_key_id, secret_key=secret, retention=retention)
        _write_in(conn, cfg, user_id)
        if moved or settings.get_setting(STATUS) is None:
            settings.set_setting_in(conn, STATUS, {"since": clock.now_iso()}, user_id)
    return status()


def clear_destination() -> dict:
    """Forget the destination (the passphrase stays). An unreadable config is removed whole."""
    with db.transaction() as conn:
        try:
            _, cfg = _read_in(conn)
            cfg = {k: v for k, v in cfg.items() if k in ("passphrase", "generation")}
        except ConfigUnreadable:
            cfg = {}
        _write_in(conn, cfg, None)
        conn.execute("DELETE FROM core_settings WHERE key = ?", (STATUS,))
    return status()


def set_passphrase(user_id: int | None, passphrase: str) -> dict:
    """A new passphrase starts a new generation: later sets go under a new `age-<generation>/` root."""
    with db.transaction() as conn:
        _, cfg = _read_in(conn)
        cfg.update(passphrase=passphrase, generation=token.token_hex(4))
        _write_in(conn, cfg, user_id)
    return status()


def clear_passphrase() -> dict:
    with db.transaction() as conn:
        _, cfg = _read_in(conn)
        cfg.pop("passphrase", None)
        cfg.pop("generation", None)
        _write_in(conn, cfg, None)
    return status()


def status() -> dict:
    """The `offsite` block of GET /api/core/backups. Never holds the secret or the passphrase."""
    try:
        _, cfg = _read()
        unreadable = False
    except ConfigUnreadable:
        cfg, unreadable = {}, True
    st: dict[str, Any] = settings.get_setting(STATUS) or {}
    configured = unreadable or _configured(cfg)
    since = st.get("last_success_at") or st.get("since")
    stale = bool(configured and since and (clock.now() - clock.parse(since)).total_seconds() > STALE_HOURS * 3600)
    return {
        "configured": configured,
        "unreadable": unreadable,
        **{k: cfg.get(k) for k in DESTINATION_FIELDS},
        "encrypted": bool(cfg.get("passphrase")),
        "last_success_at": st.get("last_success_at"),
        "last_success_bytes": st.get("last_success_bytes"),
        "last_error": UNREADABLE if unreadable else st.get("last_error"),
        "stale": stale,
    }


def test_connection() -> None:
    """Write, list, read back and delete a small object: proves the endpoint, the credentials and
    every permission the copy uses (prune reads manifests back)."""
    _, cfg = _read()
    if not _configured(cfg):
        raise Invalid("Save a backup destination first.")
    dest = _destination(cfg)
    key = f"{cfg['prefix']}springform-connection-test-{token.token_hex(12)}.txt"
    probe = b"Springform backup connection test\n"
    try:
        dest.put_bytes(key, probe)
        if key not in dest.list_keys(key):
            raise AppError("The storage service accepted the test file but does not list it.")
        if dest.get_bytes(key) != probe:
            raise AppError("The storage service returned something other than the test file it stored.")
    except Exception:
        try:
            dest.delete(key)
        except AppError:
            pass  # keep the original failure
        raise
    dest.delete(key)  # a missing delete permission fails the test too


def encrypted_copy(snapshot: Path) -> Path | None:
    """With a passphrase, an age-encrypted temporary copy of `snapshot` for download (the caller
    deletes it); None without one. Raises ConfigUnreadable rather than serving a plain file."""
    _, cfg = _read()
    if not cfg.get("passphrase"):
        return None
    tmp = snapshot.with_name(f"{snapshot.stem}.{token.token_hex(6)}.age.tmp")  # service.prune clears strays
    try:
        age.encrypt_file(snapshot, tmp, cfg["passphrase"])
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return tmp


# --- the upload (called by service.run after a good set) ---------------------------------------


def upload(manifest: Path, cancel: threading.Event | None = None) -> None:
    """Copy the set whose manifest is `manifest` off-site, then prune. Never raises; the outcome is recorded."""
    try:
        raw, cfg = _read()
    except ConfigUnreadable:
        logger.error("Off-site copy skipped: %s", UNREADABLE)
        return
    except Exception:
        logger.exception("Off-site copy skipped: its settings could not be read")
        return
    if not _configured(cfg):
        return
    try:
        size = _upload(cfg, manifest, cancel)
    except Exception as e:
        logger.exception("Off-site copy of %s failed; the next backup tries again", manifest.name)
        _record(raw, last_error=_message(e))
        return
    logger.info("Off-site copy of %s uploaded", manifest.name)
    _record(raw, last_success_at=clock.now_iso(), last_success_bytes=size, last_error=None)
    try:
        _prune(cfg, raw, cancel)
    except Exception as e:
        logger.exception("Pruning the off-site copy failed; the new set is uploaded")
        _record(raw, last_error="Uploaded, but removing old backups failed: " + _message(e))


def _message(e: Exception) -> str:
    return (e.detail if isinstance(e, AppError) else f"The upload failed: {e!r}")[:1000]


def _record(raw: str | None, **fields: Any) -> None:
    """Merge `fields` into the status row, unless the config changed while the run was out."""
    try:
        with db.transaction() as conn:
            now = conn.execute("SELECT value FROM core_settings WHERE key = ?", (CONFIG,)).fetchone()
            if now is None or now[0] != raw:
                return
            row = conn.execute("SELECT value FROM core_settings WHERE key = ?", (STATUS,)).fetchone()
            st = json.loads(row[0]) if row else {"since": clock.now_iso()}
            settings.set_setting_in(conn, STATUS, {**st, **fields}, None)
    except Exception:
        logger.exception("Could not record the off-site copy's outcome")


def _check(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise AppError("The off-site copy was stopped before it finished; the next backup resumes it.")


def _config_unchanged(raw: str | None) -> None:
    """A plain read, no transaction: prune stops once the admin removed or changed the destination."""
    now = db.get_conn().execute("SELECT value FROM core_settings WHERE key = ?", (CONFIG,)).fetchone()
    if now is None or now[0] != raw:
        raise AppError("The off-site settings changed while the copy ran; old backups were left alone.")


def _put(dest: S3Destination, key: str, path: Path, passphrase: str | None, tmp_dir: Path) -> int:
    if not passphrase:
        return dest.put_file(key, path)
    # simplification: one scrypt per object (about a second at age's work factor), so a first
    # encrypted copy of many attachments is slow; later runs upload only new ones.
    tmp = tmp_dir / f"offsite-{token.token_hex(6)}.age.tmp"
    try:
        age.encrypt_file(path, tmp, passphrase)
        return dest.put_file(key, tmp)
    finally:
        tmp.unlink(missing_ok=True)


def _upload(cfg: dict, manifest: Path, cancel: threading.Event | None) -> int:
    """Blobs, then the snapshot, then the manifest. Returns the snapshot's uploaded size."""
    body = json.loads(manifest.read_text(encoding="utf-8"))
    backups, passphrase = manifest.parent, cfg.get("passphrase")
    files, root, ext = backups.parent / "files", _root(cfg), ".age" if passphrase else ""
    dest = _destination(cfg)
    have = set(dest.list_keys(f"{root}files/"))
    missing = []
    for sha in body["blobs"]:
        _check(cancel)
        key = f"{root}files/{sha[:2]}/{sha}{ext}"
        if key in have:
            continue
        local = files / sha[:2] / sha
        if not local.is_file() or _sha256(local) != sha:  # a damaged file would publish a set restore refuses
            missing.append(sha)
            continue
        _put(dest, key, local, passphrase, backups)
    if missing:  # publishing this manifest would put a set in the bucket that restore refuses
        raise AppError(
            f"{len(missing)} attached files the backup lists are missing or damaged on this server (first: {missing[0]}); "
            "the set was not uploaded."
        )
    _check(cancel)
    snapshot = backups / body["snapshot"]["filename"]
    size = _put(dest, f"{root}backups/{snapshot.name}{ext}", snapshot, passphrase, backups)
    _check(cancel)
    _put(dest, f"{root}backups/{manifest.name}{ext}", manifest, passphrase, backups)
    return size


def _sha256(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def _blobs_listed(dest: S3Destination, key: str, passphrase: str | None) -> set[str]:
    """The blob list of a remote manifest. Raises on anything unreadable or malformed (fail closed)."""
    data = dest.get_bytes(key)
    if key.endswith(".age"):
        if not passphrase:
            raise ValueError("encrypted manifest and no passphrase")
        data = age.decrypt(data, passphrase)
    body = json.loads(data)
    blobs = body["blobs"]
    if (
        body.get("version") != 1
        or not isinstance(blobs, list)
        or not all(isinstance(b, str) and SHA.match(b) for b in blobs)
    ):
        raise ValueError("malformed manifest")
    return set(blobs)


def _prune(cfg: dict, raw: str | None, cancel: threading.Event | None = None) -> None:
    """Keep the newest `retention` complete sets across every root; delete older set objects
    (manifest first), then blobs no retained manifest in their root lists. A root whose manifests
    this install cannot read (an older passphrase) keeps its blobs until its sets age out; one it
    should read but cannot keeps its blobs and raises once the rest is pruned. Stops (raises)
    when cancelled or when the config changed since the run read it."""

    def step() -> None:
        _check(cancel)
        _config_unchanged(raw)

    dest, prefix = _destination(cfg), cfg["prefix"]
    sets: dict[tuple[str, str], list[tuple[str, bool]]] = {}  # (root, stamp) -> [(key, is_manifest)]
    blobs: dict[str, list[tuple[str, str]]] = {}
    for key in dest.list_keys(prefix):
        rel = key[len(prefix) :]
        if m := SET_KEY.match(rel):
            sets.setdefault((m[1] or "", m[2]), []).append((key, m[3] == "manifest.json"))
        elif m := BLOB_KEY.match(rel):
            blobs.setdefault(m[1] or "", []).append((key, m[2]))
    complete = sorted((s for s, keys in sets.items() if any(man for _, man in keys)), key=lambda s: _order(s[1]))
    retained = set(complete[-cfg["retention"] :])
    for s, keys in sets.items():
        if s not in retained:
            for key, _ in sorted(keys, key=lambda k: not k[1]):  # manifest first
                step()
                dest.delete(key)
    current = f"age-{cfg['generation']}" if cfg.get("passphrase") else ""
    unread: list[str] = []
    for root, items in blobs.items():
        manifests = [k for s, keys in sets.items() if s in retained and s[0] == root for k, man in keys if man]
        if manifests and root not in ("", current):
            continue  # an older passphrase's root: its manifests cannot be read here
        keep: set[str] = set()
        for k in manifests:
            _check(cancel)
            try:
                keep |= _blobs_listed(dest, k, cfg.get("passphrase"))
            except Exception as e:  # fail closed: keep every blob in this root
                logger.warning("Off-site prune left the attachments under %r alone: %r", root or "/", e)
                unread.append(root or "/")
                break
        if (root or "/") in unread:
            continue
        for key, sha in items:
            if sha not in keep:
                step()
                dest.delete(key)
    if unread:
        raise AppError(
            f"A retained backup's list of attached files could not be read back from the bucket ({', '.join(unread)}), "
            "so its old attachments were kept. Check that the access key can read objects."
        )
