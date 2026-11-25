"""The off-site copy's primitives: age passphrase files that a real age implementation (pyrage,
the rage library) opens, the in-app reader, and the S3 request signature."""

import hashlib
import importlib
import os
from datetime import UTC, datetime

import pytest

from backend.core.backup import age, s3
from backend.core.errors import Invalid

# pyrage (rage, an independent age implementation) is compiled and ships no type stubs.
pyrage = importlib.import_module("pyrage")
PASSPHRASE = "a long test passphrase"


@pytest.mark.parametrize("size", [0, 1, 65536, 65537, 200000])
def test_pyrage_decrypts_what_the_writer_wrote(tmp_path, monkeypatch, size):
    if size != 65537:  # one size at age's real work factor; the rest fast
        monkeypatch.setattr(age, "LOG_N", 10)
    data = os.urandom(size)
    src, dst = tmp_path / "plain", tmp_path / "plain.age"
    src.write_bytes(data)
    age.encrypt_file(src, dst, PASSPHRASE)
    assert pyrage.passphrase.decrypt(dst.read_bytes(), PASSPHRASE) == data
    assert age.decrypt(dst.read_bytes(), PASSPHRASE) == data


def test_the_reader_refuses_a_wrong_passphrase_damage_and_too_much_work(tmp_path, monkeypatch):
    monkeypatch.setattr(age, "LOG_N", 10)
    src, dst = tmp_path / "plain", tmp_path / "plain.age"
    src.write_bytes(b"attachment bytes" * 5000)
    age.encrypt_file(src, dst, PASSPHRASE)
    data = dst.read_bytes()
    for bad, passphrase in [
        (data, "wrong passphrase"),
        (data[:-1], PASSPHRASE),
        (data[:-16], PASSPHRASE),  # a whole tag gone
        (data.replace(b" 10\n", b" 30\n", 1), PASSPHRASE),
        (b"not age at all", PASSPHRASE),
    ]:
        with pytest.raises(age.DecryptError):
            age.decrypt(bad, passphrase)
    with pytest.raises(pyrage.DecryptError):
        pyrage.passphrase.decrypt(data[:-1], PASSPHRASE)


def test_aws_published_list_objects_signature():
    # https://docs.aws.amazon.com/AmazonS3/latest/API/sig-v4-header-based-auth.html (lifted from CakeCRM)
    headers = s3.signed_headers(
        "GET",
        "examplebucket.s3.amazonaws.com",
        "/",
        "max-keys=2&prefix=J",
        hashlib.sha256(b"").hexdigest(),
        "us-east-1",
        "AKIAIOSFODNN7EXAMPLE",
        "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        datetime(2013, 5, 24, tzinfo=UTC),
    )
    assert headers["Authorization"].endswith("34b48302e7b5fa45bde8084f4b7868a86f0a534bc59db6670ed5711ef69dc6f7")


def test_endpoints_are_canonical_origins():
    assert (
        s3.validate_endpoint(" https://ACCT.r2.cloudflarestorage.com:443/ ") == "https://acct.r2.cloudflarestorage.com"
    )
    assert s3.validate_endpoint("http://127.0.0.1:9000/base") == "http://127.0.0.1:9000/base"
    for bad in ["ftp://host", "https://user:pw@host", "https://host/?q=1", "https://host/../x", "host"]:
        with pytest.raises(Invalid):
            s3.validate_endpoint(bad)
