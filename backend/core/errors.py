"""Domain errors services raise; one handler turns them into FastAPI's `{detail}` shape."""

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
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

    @app.exception_handler(RequestValidationError)
    async def _invalid(request: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI's default echoes each field's `input`: a 422 would return a submitted secret or password.
        errors = [{k: v for k, v in e.items() if k != "input"} for e in exc.errors()]
        return JSONResponse({"detail": jsonable_encoder(errors)}, status_code=422)
