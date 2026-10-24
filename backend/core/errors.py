"""Domain errors services raise; one handler turns them into FastAPI's `{detail}` shape."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    status = 500
    default = "error"

    def __init__(self, detail: str | None = None):
        self.detail = detail or self.default
        super().__init__(self.detail)


class NotFound(AppError):
    status, default = 404, "not_found"


class Forbidden(AppError):
    status, default = 403, "forbidden"


class Conflict(AppError):
    status, default = 409, "conflict"


class Invalid(AppError):
    status, default = 422, "invalid"


def install(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status)
