"""Response defaults: nosniff, same-origin framing against clickjacking, and referrer policy.

HSTS applies only to HTTPS. A script/style CSP awaits a design for the inline theme script.
Wrap the whole built stack so unhandled 500s and CSRF refusals also receive these headers;
a response's own values always win.
"""

from fastapi import FastAPI
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Content-Security-Policy": "frame-ancestors 'self'",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}
HSTS = "max-age=31536000"


def _wrap(asgi: ASGIApp) -> ASGIApp:
    async def wrapped(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await asgi(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in HEADERS.items():
                    if name not in headers:
                        headers[name] = value
                if scope["scheme"] == "https" and "Strict-Transport-Security" not in headers:
                    headers["Strict-Transport-Security"] = HSTS
            await send(message)

        await asgi(scope, receive, send_with_headers)

    return wrapped


def install(app: FastAPI) -> None:
    build = app.build_middleware_stack
    app.build_middleware_stack = lambda: _wrap(build())
