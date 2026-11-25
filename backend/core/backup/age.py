"""age v1 passphrase (scrypt) encryption: https://c2sp.org/age (age-encryption.org/v1).

`encrypt_file` streams, so a snapshot of any size holds two 64 KiB chunks in memory. The output
decrypts with `age -d` (or rage, pyrage) and the passphrase alone. `decrypt` reads small files in
memory: the off-site prune reads its encrypted manifests back with it.
"""

import base64
import hashlib
import hmac
import os
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

LOG_N = 18  # age's default scrypt work factor; tests lower it
MAX_LOG_N = 18  # decrypt reads only files encrypt_file wrote; a header asking for more work is refused
INTRO = b"age-encryption.org/v1\n"
CHUNK = 64 * 1024
LABEL = b"age-encryption.org/v1/scrypt"


class DecryptError(Exception):
    """Not an age file this passphrase opens: wrong passphrase, damaged, or another recipient type."""


def _b64(data: bytes) -> bytes:
    return base64.b64encode(data).rstrip(b"=")


def _unb64(data: bytes) -> bytes:
    if b"=" in data:
        raise ValueError("padded base64")
    return base64.b64decode(data + b"=" * (-len(data) % 4), validate=True)


def _hkdf(key: bytes, salt: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=info).derive(key)


def _scrypt(passphrase: str, salt: bytes, log_n: int) -> bytes:
    return hashlib.scrypt(passphrase.encode(), salt=LABEL + salt, n=2**log_n, r=8, p=1, maxmem=2**29, dklen=32)


def encrypt_file(src: Path, dst: Path, passphrase: str) -> None:
    """Lifted from CakeCRM `backend/backups/age.py`."""
    file_key, salt = os.urandom(16), os.urandom(16)
    body = ChaCha20Poly1305(_scrypt(passphrase, salt, LOG_N)).encrypt(bytes(12), file_key, None)
    header = INTRO + b"-> scrypt " + _b64(salt) + b" " + str(LOG_N).encode() + b"\n" + _b64(body) + b"\n---"
    mac = hmac.digest(_hkdf(file_key, b"", b"header"), header, "sha256")
    nonce = os.urandom(16)
    cipher = ChaCha20Poly1305(_hkdf(file_key, nonce, b"payload"))
    with src.open("rb") as source, dst.open("wb") as target:
        target.write(header + b" " + _b64(mac) + b"\n" + nonce)
        chunk = source.read(CHUNK)
        counter = 0
        while True:
            following = source.read(CHUNK)
            target.write(cipher.encrypt(counter.to_bytes(11, "big") + bytes([not following]), chunk, None))
            if not following:
                break
            chunk, counter = following, counter + 1


def decrypt(data: bytes, passphrase: str) -> bytes:
    """The plaintext of an age passphrase file held in memory. Raises DecryptError."""
    try:
        head, sep, rest = data.partition(b"\n--- ")
        lines = head.split(b"\n")
        stanza = lines[1].split(b" ") if len(lines) == 3 else []
        if not sep or lines[0] + b"\n" != INTRO or len(stanza) != 4 or stanza[:2] != [b"->", b"scrypt"]:
            raise ValueError("not a single-stanza age scrypt file")
        log_n = int(stanza[3])
        if not 1 <= log_n <= MAX_LOG_N or not stanza[3].isdigit():
            raise ValueError("work factor out of range")
        wrapped = ChaCha20Poly1305(_scrypt(passphrase, _unb64(stanza[2]), log_n))
        file_key = wrapped.decrypt(bytes(12), _unb64(lines[2]), None)
        mac, _, payload = rest.partition(b"\n")
        expected = hmac.digest(_hkdf(file_key, b"", b"header"), head + b"\n---", "sha256")
        if not hmac.compare_digest(_unb64(mac), expected):
            raise ValueError("header MAC mismatch")
        nonce, payload = payload[:16], payload[16:]
        cipher = ChaCha20Poly1305(_hkdf(file_key, nonce, b"payload"))
        size = CHUNK + 16
        pieces = [payload[i : i + size] for i in range(0, len(payload), size)] or [b""]
        out = [
            cipher.decrypt(n.to_bytes(11, "big") + bytes([n == len(pieces) - 1]), piece, None)
            for n, piece in enumerate(pieces)
        ]
        return b"".join(out)
    except (ValueError, IndexError, InvalidTag) as e:
        raise DecryptError(str(e) or type(e).__name__) from None
