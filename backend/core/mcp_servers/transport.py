"""Outbound MCP HTTP under the address policy (docs/agents/mcp.md §2), enforced at connection time.

A hostname check before connecting is not enough: DNS can answer a public address to the check
and a private one to the connection (rebinding). So the policy lives in the network backend that
opens every TCP connection: it resolves the host itself, refuses the connection unless EVERY
returned address passes, and connects to a validated IP. httpcore then starts TLS with the URL's
hostname, so SNI and certificate verification still name the host, not the IP.

- https only. Loopback, private, link-local, IPv4-mapped IPv6 (and anything else that is not a
  global address) are refused.
- MCP_ALLOW_PRIVATE=1 (local development) permits those addresses, and `http://` to them only.
- No redirects (max_redirects=0, so the SDK's same-origin following stops at the first hop), no
  proxies or netrc from the environment, 30 s timeout, responses capped at 1 MB and never
  compressed (a compressed body would get past the cap once decoded).
- Refuses to send inside a database transaction (platform rule: no network inside transaction()).

Web mode (`http_client(web=True)`, Whisk's `core_web_fetch`, docs/agents/agent.md §4): http and
https both, but never a private address (MCP_ALLOW_PRIVATE does not apply); still no automatic
redirects (the reader follows them itself, so each hop is a new request through this transport,
checked and pinned again, and no redirect body is read); 6 MB raw (the reader stops at 5 MB); compressed bodies allowed (httpx2 inflates them in bounded
pieces and the caller caps what it reads); a 401 or 403 is returned, not refused.
"""

from __future__ import annotations

import ipaddress
import os
import socket

import anyio
import httpcore2
import httpx2

# The real class: httpcore2.AnyIOBackend is a stand-in when anyio is missing, which a checker cannot rule out.
from httpcore2._backends.anyio import AnyIOBackend

from backend.core import db

TIMEOUT = 30.0
MAX_RESPONSE = 1024 * 1024
MAX_WEB_RESPONSE = 6 * 1024 * 1024  # a backstop above the web reader's own 5 MB cap, so the reader truncates first
# IPv6 ranges that carry an IPv4 address, which `is_global` can call global (64:ff9b::a9fe:a9fe is
# the metadata address behind NAT64). Refused whole rather than decoded: nothing fetched lives there.
_EMBEDDED = tuple(
    ipaddress.IPv6Network(n)
    for n in ("64:ff9b::/96", "64:ff9b:1::/48", "2002::/16", "::/96")  # NAT64, NAT64 local, 6to4, IPv4-compatible
)


class Refused(Exception):
    """The policy refused a destination or a response."""


def allow_private() -> bool:
    return os.environ.get("MCP_ALLOW_PRIVATE") == "1"


def internal(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Anything that is not a plain public unicast address."""
    if not ip.is_global or ip.is_multicast:
        return True
    return isinstance(ip, ipaddress.IPv6Address) and (ip.ipv4_mapped is not None or any(ip in n for n in _EMBEDDED))


def check(address: str, *, plain: bool, allow: bool) -> None:
    ip = ipaddress.ip_address(address)
    if internal(ip) and not allow:
        raise Refused(f"{ip} is a loopback, private or link-local address; the outbound guard refuses it")
    if plain and not internal(ip):
        raise Refused(f"http:// is allowed only to private addresses, and {ip} is public; use https")


async def resolve(host: str, port: int) -> list[str]:
    """Every address the host resolves to (tests replace this with a stub)."""
    infos = await anyio.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


class GuardedBackend(httpcore2.AsyncNetworkBackend):
    def __init__(self, *, plain: bool, allow: bool, inner: httpcore2.AsyncNetworkBackend | None = None):
        self._plain, self._allow = plain, allow
        self._inner = inner or AnyIOBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        addresses = await resolve(host, port)
        for address in addresses:  # all of them, before any connection
            check(address, plain=self._plain, allow=self._allow)
        error: Exception = Refused(f"{host} did not resolve")  # raised as is when there is no address
        for address in addresses:
            try:
                return await self._inner.connect_tcp(
                    address, port, timeout=timeout, local_address=local_address, socket_options=socket_options
                )
            except httpcore2.ConnectError as e:
                error = e
        raise error

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise Refused("unix sockets are not allowed")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


def _pool(backend: GuardedBackend) -> httpx2.AsyncHTTPTransport:
    transport = httpx2.AsyncHTTPTransport(trust_env=False)
    # httpx takes no network backend in its constructor; the pool is where httpcore accepts one.
    transport._pool = httpcore2.AsyncConnectionPool(ssl_context=httpx2.create_ssl_context(), network_backend=backend)
    return transport


class _Capped(httpx2.AsyncByteStream):
    def __init__(self, stream: httpx2.AsyncByteStream, limit: int = MAX_RESPONSE):
        self._stream, self._limit = stream, limit

    async def __aiter__(self):
        seen = 0
        async for chunk in self._stream:
            seen += len(chunk)
            if seen > self._limit:
                raise Refused(f"The server's response is over {self._limit // 1024} KB")
            yield chunk

    async def aclose(self) -> None:
        await self._stream.aclose()


class GuardedTransport(httpx2.AsyncBaseTransport):
    def __init__(self, inner: httpcore2.AsyncNetworkBackend | None = None, *, web: bool = False):
        self._web = web
        if web:  # public addresses only, over either scheme
            self._pools = {s: _pool(GuardedBackend(plain=False, allow=False, inner=inner)) for s in ("https", "http")}
            return
        allow = allow_private()
        self._pools = {"https": _pool(GuardedBackend(plain=False, allow=allow, inner=inner))}
        if allow:
            self._pools["http"] = _pool(GuardedBackend(plain=True, allow=True, inner=inner))

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        if db.in_transaction():
            raise RuntimeError("network call inside transaction()")
        pool = self._pools.get(request.url.scheme)
        if pool is None:
            if self._web:
                raise Refused(f"{request.url.scheme}:// is not allowed; only http and https pages are read")
            raise Refused(f"{request.url.scheme}:// is not allowed; MCP servers must use https")
        response = await pool.handle_async_request(request)
        problem = None  # web mode: a page's 403 is an answer, and a compressed body is inflated in bounded pieces
        if not self._web and response.status_code in (401, 403):  # the SDK would report only "an error response"
            problem = f"The server refused the request (HTTP {response.status_code}); check the token"
        elif not self._web and response.headers.get("content-encoding", "identity") != "identity":
            problem = "The server sent a compressed response, which is refused"
        if problem:
            await response.aclose()
            raise Refused(problem)
        if not isinstance(response.stream, httpx2.AsyncByteStream):  # an async transport always returns one
            raise TypeError("expected an async response stream")
        response.stream = _Capped(response.stream, MAX_WEB_RESPONSE if self._web else MAX_RESPONSE)
        return response

    async def aclose(self) -> None:
        for pool in self._pools.values():
            await pool.aclose()


def http_client(
    token: str = "", inner: httpcore2.AsyncNetworkBackend | None = None, *, web: bool = False
) -> httpx2.AsyncClient:
    headers = {} if web else {"Accept-Encoding": "identity"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx2.AsyncClient(
        transport=GuardedTransport(inner, web=web),
        headers=headers,
        timeout=TIMEOUT,
        follow_redirects=False,  # httpx would read every redirect body in full; web reads follow by hand
        max_redirects=0,
        trust_env=False,
    )
