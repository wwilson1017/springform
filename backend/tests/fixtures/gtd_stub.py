"""A GTD suite stand-in for the Settings, GTD suite tests and local demos: the device connect
(`/api/connect`, `/api/connect/poll`), `/api/config` with the app addresses, and the two-tool MCP
stub (`mcp_stub`) served as the agent link `/link/<token>`.

`with serve() as (base, state, calls):` runs it on a free loopback port; tests steer it through
`state` (approve, rate-limit, expire). `python -m backend.tests.fixtures.gtd_stub <port>` runs it in
the foreground, approving each code on its second poll.
"""

from __future__ import annotations

import contextlib
import sys
from types import SimpleNamespace

import uvicorn
from starlette.requests import Request
from starlette.responses import JSONResponse

from backend.tests.fixtures import mcp_stub

LINK = "L" * 43
DEVICE = "d" * 43
CODE = "WXYZ-2345"
APPS = {
    key: {"title": f"{key.title()} GTD", "url": f"https://{key}.example.test"}
    for key in ("todo", "notes", "projects", "sites", "brain")
}


def fresh_state() -> SimpleNamespace:
    return SimpleNamespace(
        approved=False,  # the next poll answers approved (once)
        approve_after=None,  # or: approve on this poll number
        gone=False,  # the code is expired or collected: polls answer 404
        limited=False,  # /api/connect answers 429
        poll_limited=False,  # /api/connect/poll answers 429
        interval=0,
        polls=0,
        connects=0,
        apps={**APPS, "mail": {"title": "Mail", "url": "https://mail.example.test"}},  # mail: not a tile
        config_status=200,
    )


def build():
    """(asgi app, state, calls): `calls` records every MCP tool call the agent link receives."""
    mcp, calls = mcp_stub.build()
    state = fresh_state()

    async def app(scope, receive, send):
        if scope["type"] != "http":
            return await mcp(scope, receive, send)
        path, method = scope["path"], scope["method"]
        if path == f"/link/{LINK}":
            return await mcp({**scope, "path": "/mcp", "raw_path": b"/mcp"}, receive, send)
        reply = JSONResponse({"detail": "Not found"}, status_code=404)
        if path == "/api/config" and method == "GET":
            reply = JSONResponse({"apps": state.apps}, status_code=state.config_status)
        elif path == "/api/connect" and method == "POST":
            state.connects += 1
            if state.limited:
                reply = JSONResponse({"detail": "Too many"}, status_code=429, headers={"Retry-After": "3600"})
            else:
                state.approved = state.gone = False  # a new code
                state.polls = 0
                reply = JSONResponse(
                    {
                        "user_code": CODE,
                        "device_token": DEVICE,
                        "interval": state.interval,
                        "expires_in": 900,
                        "url": f"https://suite.example.test/connect?code={CODE}",
                    }
                )
        elif path == "/api/connect/poll" and method == "POST":
            state.polls += 1
            body = await Request(scope, receive).json()
            if state.approve_after is not None and state.polls >= state.approve_after:
                state.approved = True
            if state.poll_limited:
                reply = JSONResponse({"detail": "Too many"}, status_code=429, headers={"Retry-After": "120"})
            elif body.get("device_token") != DEVICE or state.gone:
                pass  # 404
            elif state.approved:
                state.gone = True  # the link is handed out exactly once
                host = dict(scope["headers"])[b"host"].decode()
                reply = JSONResponse({"status": "approved", "agent_url": f"http://{host}/link/{LINK}"})
            else:
                reply = JSONResponse({"status": "pending"})
        await reply(scope, receive, send)

    return app, state, calls


@contextlib.contextmanager
def serve():
    """Run on a free loopback port for the length of the `with`; yields (base url, state, calls)."""
    app, state, calls = build()
    with mcp_stub.run(app) as base:
        yield base, state, calls


if __name__ == "__main__":
    asgi, demo, _ = build()
    demo.approve_after = 2
    demo.interval = 3
    uvicorn.run(asgi, host="127.0.0.1", port=int(sys.argv[1]), log_level="info")
