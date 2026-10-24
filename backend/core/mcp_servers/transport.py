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
"""

from __future__ import annotations

import ipaddress
import os
import socket

import anyio
import httpcore2
import httpx2

from backend.core import db

TIMEOUT = 30.0
MAX_RESPONSE = 1024 * 1024


class Refused(Exception):
    """The policy refused a destination or a response."""


def allow_private() -> bool:
    return os.environ.get("MCP_ALLOW_PRIVATE") == "1"


def internal(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Anything that is not a plain public unicast address."""
    return not ip.is_global or ip.is_multicast or (ip.version == 6 and ip.ipv4_mapped is not None)


def check(address: str, *, plain: bool, allow: bool) -> None:
    ip = ipaddress.ip_address(address)
    if internal(ip) and not allow:
        raise Refused(f"{ip} is a loopback, private or link-local address; outbound MCP refuses it")
    if plain and not internal(ip):
        raise Refused(f"http:// is allowed only to private addresses, and {ip} is public; use https")


async def resolve(host: str, port: int) -> list[str]:
    """Every address the host resolves to (tests replace this with a stub)."""
    infos = await anyio.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


class GuardedBackend(httpcore2.AsyncNetworkBackend):
    def __init__(self, *, plain: bool, allow: bool, inner: httpcore2.AsyncNetworkBackend | None = None):
        self._plain, self._allow = plain, allow
        self._inner = inner or httpcore2.AnyIOBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        addresses = await resolve(host, port)
        if not addresses:
            raise Refused(f"{host} did not resolve")
        for address in addresses:  # all of them, before any connection
            check(address, plain=self._plain, allow=self._allow)
        error: Exception | None = None
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
    def __init__(self, stream: httpx2.AsyncByteStream):
        self._stream = stream

    async def __aiter__(self):
        seen = 0
        async for chunk in self._stream:
            seen += len(chunk)
            if seen > MAX_RESPONSE:
                raise Refused(f"The server's response is over {MAX_RESPONSE // 1024} KB")
            yield chunk

    async def aclose(self) -> None:
        await self._stream.aclose()


class GuardedTransport(httpx2.AsyncBaseTransport):
    def __init__(self, inner: httpcore2.AsyncNetworkBackend | None = None):
        allow = allow_private()
        self._pools = {"https": _pool(GuardedBackend(plain=False, allow=allow, inner=inner))}
        if allow:
            self._pools["http"] = _pool(GuardedBackend(plain=True, allow=True, inner=inner))

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        if db.in_transaction():
            raise RuntimeError("network call inside transaction()")
        pool = self._pools.get(request.url.scheme)
        if pool is None:
            raise Refused(f"{request.url.scheme}:// is not allowed; MCP servers must use https")
        response = await pool.handle_async_request(request)
        problem = None
        if response.status_code in (401, 403):  # the SDK would report only "an error response"
            problem = f"The server refused the token (HTTP {response.status_code})"
        elif response.headers.get("content-encoding", "identity") != "identity":
            problem = "The server sent a compressed response, which is refused"
        if problem:
            await response.aclose()
            raise Refused(problem)
        response.stream = _Capped(response.stream)
        return response

    async def aclose(self) -> None:
        for pool in self._pools.values():
            await pool.aclose()


def http_client(token: str = "", inner: httpcore2.AsyncNetworkBackend | None = None) -> httpx2.AsyncClient:
    headers = {"Accept-Encoding": "identity", **({"Authorization": f"Bearer {token}"} if token else {})}
    return httpx2.AsyncClient(
        transport=GuardedTransport(inner), headers=headers, timeout=TIMEOUT,
        follow_redirects=False, max_redirects=0, trust_env=False,
    )
