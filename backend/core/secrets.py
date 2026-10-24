"""Long-lived install secrets and encryption at rest.

Two secrets must come back identical on every boot or the install breaks: the Fernet key (a new
one orphans every stored credential) and the session signing key (a new one signs everyone out).
Both resolve the same way: environment variable, then a 0600 file in the data directory, then
generated once and stored there. An invalid value is an error, never a silent rotation.

Encrypted values carry the `enc:v1:` prefix; plaintext passes through decrypt unchanged.
"""

from __future__ import annotations

import functools
import hashlib
import logging
import os
from collections.abc import Callable
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from backend.core import db

logger = logging.getLogger(__name__)

PREFIX = "enc:v1:"


def persisted(env_var: str, filename: str, generate: Callable[[], str], validate: Callable[[str], bool]) -> str:
    raw = os.environ.get(env_var, "")
    if raw:
        if not validate(raw):
            raise RuntimeError(f"{env_var} is set but is not a valid value")
        return raw
    return _from_file(db.data_dir() / filename, generate, validate)


def _from_file(path: Path, generate: Callable[[], str], validate: Callable[[str], bool]) -> str:
    if not path.exists():
        value = generate()
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass  # another process published it first; adopt theirs below
        else:
            with os.fdopen(fd, "w") as f:
                f.write(value + "\n")
                f.flush()
                os.fsync(f.fileno())
            logger.info("Generated %s", path)
            return value
    value = path.read_text(encoding="utf-8").strip()
    if not validate(value):
        raise RuntimeError(f"{path} holds an invalid value; refusing to replace an established secret")
    return value


def _is_fernet_key(value: str) -> bool:
    try:
        Fernet(value.encode())
        return True
    except Exception:
        return False


@functools.cache
def _key(data_dir: str, env_value: str) -> bytes:
    return persisted("ENCRYPTION_KEY", ".encryption-key", lambda: Fernet.generate_key().decode(), _is_fernet_key).encode()


def key() -> bytes:
    return _key(str(db.data_dir()), os.environ.get("ENCRYPTION_KEY", ""))


def key_fingerprint() -> str:
    """Identifies the key without revealing it (backup manifests compare it on restore)."""
    return hashlib.sha256(key()).hexdigest()[:16]


def encrypt(plaintext: str) -> str:
    if not plaintext or plaintext.startswith(PREFIX):
        return plaintext
    return PREFIX + Fernet(key()).encrypt(plaintext.encode()).decode()


def decrypt(stored: str) -> str:
    """Plaintext of an `enc:v1:` value; "" when it cannot be decrypted (tampered or wrong key)."""
    if not stored or not stored.startswith(PREFIX):
        return stored
    try:
        return Fernet(key()).decrypt(stored[len(PREFIX):].encode()).decode()
    except InvalidToken:
        logger.warning("Could not decrypt a stored value (tampered, or the wrong ENCRYPTION_KEY)")
        return ""
