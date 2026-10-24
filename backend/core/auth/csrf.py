"""CSRF for cookie sessions.

A state-changing `/api` request that carries the session cookie must also carry
`Sec-Fetch-Site: same-origin` (or `none`, typed by the user) or an `Origin` equal to PUBLIC_URL;
missing both, it is refused. A request with only a bearer header is exempt (a cross-site page
cannot attach one); a request carrying both is treated as cookie-authenticated. Preflights pass.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.core import settings
from backend.core.auth.deps import COOKIE

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def allowed(request: Request) -> bool:
    if request.method in SAFE_METHODS or not request.url.path.startswith("/api/"):
        return True
    if COOKIE not in request.cookies:
        return True
    if request.headers.get("sec-fetch-site") in ("same-origin", "none"):
        return True
    origin = request.headers.get("origin")
    return origin is not None and origin.rstrip("/") == settings.public_url()


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def csrf(request: Request, call_next):
        if not allowed(request):
            return JSONResponse({"detail": "csrf"}, status_code=403)
        return await call_next(request)
