"""Consistent JSON errors: ``{"error": {"code", "message", "details"}}``."""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("hookflow.api")

_DEFAULT_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    422: "validation_error",
    429: "rate_limited",
}


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        message: str,
        code: str | None = None,
        details: Any = None,
        headers: dict[str, str] | None = None,
    ):
        self.status = status
        self.code = code or _DEFAULT_CODES.get(status, "error")
        self.message = message
        self.details = details
        self.headers = headers


def not_found(what: str) -> ApiError:
    return ApiError(404, f"{what} not found.")


def _body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(_body(exc.code, exc.message, exc.details), exc.status, headers=exc.headers)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _DEFAULT_CODES.get(exc.status_code, "error")
        return JSONResponse(_body(code, str(exc.detail)), exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            # Drop the submitted input from details so passwords etc. never echo back.
            {"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")}
            for e in exc.errors()
        ]
        return JSONResponse(_body("validation_error", "Request validation failed.", details), 422)

    @app.exception_handler(OperationalError)
    async def _database_down(request: Request, exc: OperationalError) -> JSONResponse:
        # Connection lost or database unreachable: temporary, so tell clients to retry rather than give up.
        log.error("Database unavailable on %s %s", request.method, request.url.path, exc_info=exc)
        return JSONResponse(
            _body("service_unavailable", "The service is temporarily unavailable. Please retry shortly."),
            503,
            headers={"Retry-After": "5"},
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(_body("internal_error", "Something went wrong on our side."), 500)
