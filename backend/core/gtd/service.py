"""Settings, GTD suite: connect a GTD suite account to the install (docs/agents/mcp.md §2, "GTD suite connect").

A device flow the admin's browser drives. Start reads the suite's `/api/config` (the launcher tiles;
a wrong address fails here, before a code is spent) and asks for a device code. Each poll asks the
suite once, no faster than the interval it gave. On approval the agent link it returns exactly once
becomes a trusted outbound MCP server (prefix `gtd`) plus its tiles, in one transaction, and its
tools are discovered. Every request goes through the guarded MCP transport, never inside a transaction.
Disconnect deletes the server: the tiles go with it (foreign key) and the tools leave the registry.
"""

from __future__ import annotations

import threading
import time
from urllib.parse import urlsplit

from pydantic import ValidationError

from backend.core import db
from backend.core.errors import AppError, Conflict, Invalid
from backend.core.mcp_servers import client, service as mcp_service, transport
from backend.core.mcp_servers.router import ServerIn, check_url
from backend.core.platform import keys, service as platform_service

PREFIX, NAME = "gtd", "GTD suite"
TILES = {  # the suite's app key: (tile title, icon), in launcher order
    "todo": ("Todo", "check-square"),
    "notes": ("Notes", "file"),
    "projects": ("Projects", "target"),
    "sites": ("Sites", "grid"),
    "brain": ("Brain", "book"),
}


class GtdError(AppError):
    status, default = 502, "gtd_unavailable"


# simplification: the connect waiting for approval lives in process memory (one process is a platform
# rule), so a restart mid-connect means clicking Connect again; upgrade: a row, if that ever matters.
_lock = threading.Lock()
_pending: dict | None = None


def _web_url(v) -> bool:
    """Something a browser may open from an href: http(s) with a host, never `javascript:`."""
    if not isinstance(v, str) or len(v) > 2000:
        return False
    parts = urlsplit(v)
    return parts.scheme in ("http", "https") and bool(parts.hostname)


def _json(r) -> dict | None:
    try:
        body = r.json() if r.status_code == 200 else None
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def _tiles(r) -> list[dict]:
    """One tile per app the suite lists, of the five; unknown keys and unusable URLs are skipped."""
    apps = (_json(r) or {}).get("apps")
    if not isinstance(apps, dict):
        raise GtdError("That address did not answer like a GTD suite.")
    return [
        {"title": title, "url": apps[key]["url"], "icon": icon}
        for key, (title, icon) in TILES.items()
        if isinstance(apps.get(key), dict) and _web_url(apps[key].get("url"))
    ]


async def _start(base: str):
    async with transport.http_client() as http:
        tiles = _tiles(await http.get(f"{base}/api/config"))
        return tiles, await http.post(f"{base}/api/connect", json={"client": "springform"})


async def _poll(base: str, device_token: str):
    async with transport.http_client() as http:
        return await http.post(f"{base}/api/connect/poll", json={"device_token": device_token})


def _call(exchange, *args):
    try:
        return client.run(exchange, *args)
    except GtdError:
        raise
    except Exception as e:
        raise GtdError(f"Couldn't reach the GTD suite: {client.describe(e)}") from None


def _retry_after(r, default: int) -> int:
    try:
        return max(int(r.headers.get("retry-after", default)), 1)
    except ValueError:
        return default


def _server() -> dict | None:
    return db.one("SELECT * FROM core_agent_mcp_servers WHERE prefix = ? AND trusted = 1", (PREFIX,))


def _live() -> dict | None:
    """The connect waiting for approval; an approved one is kept until it is stored."""
    p = _pending
    return p if p is not None and (p["agent_url"] or time.monotonic() < p["expires_at"]) else None


def view() -> dict:
    row, p = _server(), _live()
    pending = None
    if p is not None:
        left = max(int(p["expires_at"] - time.monotonic()), 0)
        pending = {"user_code": p["user_code"], "url": p["url"], "interval": p["interval"], "expires_in": left}
    return {
        "base_url": keys.get("gtd.base_url"),
        "server": mcp_service.view(row) if row else None,
        "pending": pending,
    }


def start() -> dict:
    global _pending
    with _lock:
        if _live() is not None:  # a double click or a second tab spends no second code
            return view()
        taken = db.one("SELECT trusted FROM core_agent_mcp_servers WHERE prefix = ?", (PREFIX,))
        if taken is not None:
            raise Conflict("gtd_already_connected" if taken["trusted"] else "gtd_prefix_taken")
        base = keys.get("gtd.base_url")
        try:  # the hand-added server rules: https (http only with MCP_ALLOW_PRIVATE=1), and a prefix no app uses
            ServerIn(name=NAME, url=base, prefix=PREFIX)
        except ValidationError as e:
            raise Invalid(e.errors()[0]["msg"].removeprefix("Value error, ")) from None
        tiles, r = _call(_start, base)
        if r.status_code == 429:
            minutes = -(-_retry_after(r, 3600) // 60)
            raise GtdError(f"The GTD suite allows only a few connects an hour. Try again in about {minutes} minutes.")
        body = _json(r)
        if body is None:
            raise GtdError(f"The GTD suite could not start a connect (HTTP {r.status_code}).")
        code, token, url = body.get("user_code"), body.get("device_token"), body.get("url")
        interval, expires = body.get("interval"), body.get("expires_in")
        if not (
            isinstance(code, str)
            and code
            and isinstance(token, str)
            and token
            and _web_url(url)
            and isinstance(interval, int)
            and isinstance(expires, int)
            and expires > 0
        ):
            raise GtdError("The GTD suite sent an answer this install does not understand.")
        now = time.monotonic()
        _pending = {
            "base": base,
            "device_token": token,
            "tiles": tiles,
            "user_code": code,
            "url": url,
            "interval": max(interval, 1),
            "expires_at": now + expires,
            "next_poll": now,
            "agent_url": None,
        }
        return view()


def _poll_once() -> int | None:
    """The new server's id once stored, else None (still waiting). Runs under the lock."""
    global _pending
    p = _live()
    if p is None:
        _pending = None
        if _server() is not None:  # another tab finished the connect
            return None
        raise Conflict("gtd_connect_expired")
    if p["agent_url"] is None:
        now = time.monotonic()
        if now < p["next_poll"]:
            return None
        p["next_poll"] = now + p["interval"]
        r = _call(_poll, p["base"], p["device_token"])
        if r.status_code == 404:  # expired, unknown or already collected
            _pending = None
            raise Conflict("gtd_connect_expired")
        if r.status_code == 429:
            p["next_poll"] = now + _retry_after(r, p["interval"])
            return None
        body = _json(r)
        if body is None:
            raise GtdError(f"The GTD suite could not answer the connect (HTTP {r.status_code}).")
        if body.get("status") != "approved":
            return None
        try:
            p["agent_url"] = check_url(str(body.get("agent_url", "")))
        except ValueError:
            _pending = None
            raise GtdError("The GTD suite returned an address this install will not call.") from None
    # The link is sent only once: it stays in memory until this commits (e.g. while a hand-added
    # server holds the prefix, each poll retries here and answers 409 prefix_taken).
    with db.transaction() as conn:
        server_id = mcp_service.create_in(conn, name=NAME, url=p["agent_url"], prefix=PREFIX, trusted=True)
        for position, tile in enumerate(p["tiles"]):
            platform_service.add_launcher_link_in(conn, **tile, position=position, server_id=server_id)
    _pending = None
    return server_id


def poll() -> dict:
    if not _lock.acquire(blocking=False):  # another request is asking the suite right now
        return view()
    try:
        server_id = _poll_once()
    finally:
        _lock.release()
    if server_id is not None:
        client.refresh(server_id)  # never raises: a failed discovery shows as the server's last_error
    return view()


def disconnect() -> dict:
    global _pending
    with _lock:
        _pending = None
        row = _server()
        if row is not None:
            mcp_service.delete(row["id"])  # its tiles go with it (ON DELETE CASCADE)
    if row is not None:
        client.refresh(row["id"])  # drops its tools from the registry
    return view()
