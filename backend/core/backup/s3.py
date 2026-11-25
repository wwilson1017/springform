"""A small path-style S3 client for the off-site copy: SigV4 signed PUT, GET, DELETE and a paged LIST.

No SDK. Any S3-compatible store works (AWS S3, Cloudflare R2, Backblaze B2, MinIO). Lifted from
CakeCRM `backend/backups/s3.py`, without its multipart upload.
"""

import hashlib
import hmac
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit, urlunsplit

import httpx

from backend.core import clock
from backend.core.errors import AppError, Invalid

READ = 1 << 20


class S3Error(AppError):
    """The store could not be reached or refused a call; `detail` is safe to show an admin."""

    status, default = 502, "offsite_unavailable"


def validate_endpoint(endpoint: str) -> str:
    """The endpoint as a canonical http(s) origin plus optional base path; Invalid otherwise."""
    endpoint = endpoint.strip().rstrip("/")
    try:
        url = urlsplit(endpoint)
        port = url.port
    except ValueError:
        raise Invalid("The endpoint URL or port is not valid.") from None
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or any(part in {".", ".."} for part in unquote(url.path).split("/"))
        or any(ord(c) < 32 for c in endpoint)
    ):
        raise Invalid("The endpoint must be an http(s) URL with a host, and no credentials, query or dot segments.")
    host = url.hostname.encode("idna").decode().lower()
    if ":" in host:
        host = f"[{host}]"
    default = {"http": 80, "https": 443}[url.scheme]  # httpx drops a default port from Host, so the signature must too
    origin = host + (f":{port}" if port not in (None, default) else "")
    return urlunsplit((url.scheme, origin, quote(unquote(url.path), safe="/-_.~"), "", ""))


def signed_headers(
    method: str,
    host: str,
    path: str,
    query: str,
    digest: str,
    region: str,
    access_key_id: str,
    secret_key: str,
    now: datetime | None = None,
) -> dict[str, str]:
    stamp = (now or clock.now()).strftime("%Y%m%dT%H%M%SZ")
    date = stamp[:8]
    headers = {"host": host, "x-amz-content-sha256": digest, "x-amz-date": stamp}
    names = ";".join(headers)
    canonical = "\n".join([method, path, query, "".join(f"{k}:{v}\n" for k, v in headers.items()), names, digest])
    scope = f"{date}/{region}/s3/aws4_request"
    to_sign = f"AWS4-HMAC-SHA256\n{stamp}\n{scope}\n{hashlib.sha256(canonical.encode()).hexdigest()}"
    key = ("AWS4" + secret_key).encode()
    for value in (date, region, "s3", "aws4_request"):
        key = hmac.digest(key, value.encode(), "sha256")
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    headers["Authorization"] = (
        f"AWS4-HMAC-SHA256 Credential={access_key_id}/{scope}, SignedHeaders={names}, Signature={signature}"
    )
    return headers


def _xml(data: bytes) -> ET.Element:
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        raise S3Error("The storage service returned something that is not XML.") from None
    for node in root.iter():
        node.tag = node.tag.rsplit("}", 1)[-1]
    return root


class S3Destination:
    def __init__(self, endpoint: str, bucket: str, region: str, access_key_id: str, secret_key: str):
        self.endpoint = validate_endpoint(endpoint)
        self.bucket, self.region, self.access_key_id, self.secret_key = bucket, region, access_key_id, secret_key

    def _request(
        self,
        method: str,
        key: str = "",
        params: dict | None = None,
        body: bytes | Iterator[bytes] = b"",
        digest: str | None = None,
        length: int | None = None,
    ) -> httpx.Response:
        base = urlsplit(self.endpoint)
        path = base.path + "/" + quote(self.bucket, safe="-_.~") + "/" + quote(key, safe="/-_.~")
        query = "&".join(
            f"{k}={v}"
            for k, v in sorted(
                (quote(str(k), safe="-_.~"), quote(str(v), safe="-_.~")) for k, v in (params or {}).items()
            )
        )
        if isinstance(body, bytes):
            digest, length = hashlib.sha256(body).hexdigest(), len(body)
        assert digest is not None and length is not None
        headers = signed_headers(
            method, base.netloc, path, query, digest, self.region, self.access_key_id, self.secret_key
        )
        headers["Content-Length"] = str(length)
        url = urlunsplit((base.scheme, base.netloc, path, query, ""))
        try:
            with httpx.Client(timeout=httpx.Timeout(300, connect=20), follow_redirects=False) as client:
                response = client.request(method, url, headers=headers, content=body)
        except httpx.HTTPError:
            raise S3Error("Could not reach the storage service: check the endpoint and the network.") from None
        if not response.is_success:
            message = f"The storage service answered HTTP {response.status_code}"
            try:
                root = _xml(response.content)
                message += ": " + " — ".join(filter(None, [root.findtext("Code"), root.findtext("Message")]))
            except S3Error:
                pass
            for secret in (self.secret_key, self.access_key_id):
                if secret:
                    message = message.replace(secret, "[redacted]")
            raise S3Error(message[:1000])
        return response

    def put_bytes(self, key: str, data: bytes) -> None:
        self._request("PUT", key, body=data)

    def put_file(self, key: str, path: Path) -> int:
        """Upload a local file, streamed from disk with its length and SHA-256 signed. Returns its size."""
        # simplification: one PUT, so about 5 GB per object (the stores' limit). Upgrade: CakeCRM's
        # multipart put_file (backend/backups/s3.py).
        with path.open("rb") as f:
            digest = hashlib.file_digest(f, "sha256").hexdigest()
            size = f.tell()
            f.seek(0)
            self._request("PUT", key, body=iter(lambda: f.read(READ), b""), digest=digest, length=size)
        return size

    def get_bytes(self, key: str) -> bytes:
        return self._request("GET", key).content

    def delete(self, key: str) -> None:
        self._request("DELETE", key)

    def list_keys(self, prefix: str) -> list[str]:
        keys: list[str] = []
        params = {"list-type": "2", "prefix": prefix}
        seen: set[str] = set()
        while True:
            root = _xml(self._request("GET", params=params).content)
            keys.extend(n.text for n in root.findall("Contents/Key") if n.text is not None)
            if root.findtext("IsTruncated", "false").lower() != "true":
                return keys
            token = root.findtext("NextContinuationToken")
            if not token or token in seen:
                raise S3Error("The storage service returned an invalid continuation token.")
            seen.add(token)
            params["continuation-token"] = token
