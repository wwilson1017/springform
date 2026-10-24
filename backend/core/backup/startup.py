"""Boot check: does this install's encryption key match the newest backup's?

A data directory copied by hand to a server with another ENCRYPTION_KEY boots and serves, but
every stored secret reads as unset. On a mismatch the boot logs an ERROR with the remedy and
stores the manifest's filename at KEY_MISMATCH (an internal core_settings row) for the Backups
page; a match, or no backup at all, clears it. It never refuses to boot: an install whose key is
lost must still start so its admin can recover.
"""

import logging

from backend.core import db, secrets, settings
from backend.core.backup import service

logger = logging.getLogger(__name__)

KEY_MISMATCH = "backups.key_mismatch"


def _newest_fingerprint() -> tuple[str, str] | None:
    """(manifest filename, key fingerprint) of the newest readable manifest, if any."""
    for stamp in reversed(service.complete_stamps()):
        manifest = service.read_manifest(stamp)
        if isinstance(manifest, dict) and manifest.get("key_fingerprint"):
            return f"{stamp}{service.MANIFEST}", manifest["key_fingerprint"]
    return None


def on_startup() -> None:
    newest = _newest_fingerprint()
    mismatch = newest is not None and newest[1] != secrets.key_fingerprint()
    with db.transaction() as conn:
        if mismatch:
            settings.set_setting_in(conn, KEY_MISMATCH, newest[0], None)
        else:
            conn.execute("DELETE FROM core_settings WHERE key = ?", (KEY_MISMATCH,))
    if mismatch:
        logger.error(
            "The encryption key (fingerprint %s) is not the one the newest backup, %s, was taken with (%s): "
            "stored secrets will read as unset. Restore the matching key (ENCRYPTION_KEY or <data>/.encryption-key) "
            "or run a restore (scripts/restore.sh, docs/agents/deploy.md).",
            secrets.key_fingerprint(), newest[0], newest[1],
        )
