"""The error format: `{"code": "...", "message": "..."}`, the same shape as the backend's errors.

A response never carries a stack trace, a token or a provider's raw error text.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("agent.service")


class ApiError(Exception):
    """An error with its HTTP status, its code and a message that is safe to show the caller."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        *,
        headers: Mapping[str, str] | None = None,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.headers = dict(headers or {})
        self.details = dict(details) if details else None


def unauthorized(message: str = "Authentication required") -> ApiError:
    return ApiError(401, "UNAUTHORIZED", message, headers={"WWW-Authenticate": "Bearer"})


def _body(code: str, message: str, details: Mapping[str, object] | None = None) -> dict[str, object]:
    body: dict[str, object] = {"code": code, "message": message}
    if details:
        body["details"] = dict(details)
    return body


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(_request: Request, error: ApiError) -> JSONResponse:
        return JSONResponse(
            _body(error.code, error.message, error.details), status_code=error.status, headers=error.headers
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_request: Request, error: RequestValidationError) -> JSONResponse:
        # Field locations only: the rejected values are the caller's content and stay out of the response.
        fields = sorted(
            {".".join(str(part) for part in item["loc"] if part != "body") or "body" for item in error.errors()}
        )
        return JSONResponse(_body("VALIDATION_ERROR", "The request is not valid", {"fields": fields}), status_code=400)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(_request: Request, error: StarletteHTTPException) -> JSONResponse:
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(error.status_code, "HTTP_ERROR")
        return JSONResponse(_body(code, "The request cannot be served"), status_code=error.status_code)

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_request: Request, error: Exception) -> JSONResponse:
        logger.error("Unhandled %s", type(error).__name__, exc_info=error)
        return JSONResponse(_body("INTERNAL_ERROR", "The service failed to handle the request"), status_code=500)
