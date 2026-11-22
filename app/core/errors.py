"""Structured API error envelope and global FastAPI exception handlers."""

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException


class ErrorResponse(BaseModel):
    """Consistent structured JSON error envelope for all 4xx and 5xx responses."""

    code: str
    message: str
    details: Any | None = None


class AppError(Exception):
    """Base application error carrying HTTP status code and structured metadata."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


class BadRequestError(AppError):
    """HTTP 400 Bad Request."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "bad_request",
        details: Any | None = None,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            code=code,
            message=message,
            details=details,
        )


class UnauthorizedError(AppError):
    """HTTP 401 Unauthorized."""

    def __init__(
        self,
        message: str = "Authentication required.",
        *,
        code: str = "unauthorized",
        details: Any | None = None,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code=code,
            message=message,
            details=details,
        )


class ForbiddenError(AppError):
    """HTTP 403 Forbidden."""

    def __init__(
        self,
        message: str = "You do not have permission to perform this action.",
        *,
        code: str = "forbidden",
        details: Any | None = None,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            code=code,
            message=message,
            details=details,
        )


class NotFoundError(AppError):
    """HTTP 404 Not Found."""

    def __init__(
        self,
        message: str = "Requested resource was not found.",
        *,
        code: str = "not_found",
        details: Any | None = None,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            code=code,
            message=message,
            details=details,
        )


class ConflictError(AppError):
    """HTTP 409 Conflict."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "conflict",
        details: Any | None = None,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            code=code,
            message=message,
            details=details,
        )


class PayloadTooLargeError(AppError):
    """HTTP 413 Content Too Large."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "payload_too_large",
        details: Any | None = None,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            code=code,
            message=message,
            details=details,
        )


class UnsupportedMediaTypeError(AppError):
    """HTTP 415 Unsupported Media Type."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "unsupported_media_type",
        details: Any | None = None,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            code=code,
            message=message,
            details=details,
        )


_HTTP_STATUS_CODE_MAP: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "too_many_requests",
    500: "internal_server_error",
}


def register_exception_handlers(app: FastAPI) -> None:
    """Attach global handlers ensuring all 4xx/5xx errors share the JSON envelope."""

    @app.exception_handler(AppError)
    async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        payload = ErrorResponse(
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        return JSONResponse(
            status_code=exc.status_code,
            content=jsonable_encoder(payload),
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        payload = ErrorResponse(
            code="validation_error",
            message="Request validation failed.",
            details=jsonable_encoder(exc.errors()),
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=jsonable_encoder(payload),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        error_code = _HTTP_STATUS_CODE_MAP.get(exc.status_code, f"http_{exc.status_code}")
        message = exc.detail if isinstance(exc.detail, str) else "HTTP error occurred."
        details = None if isinstance(exc.detail, str) else exc.detail
        payload = ErrorResponse(code=error_code, message=message, details=details)
        return JSONResponse(
            status_code=exc.status_code,
            content=jsonable_encoder(payload),
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_request: Request, _exc: Exception) -> JSONResponse:
        payload = ErrorResponse(
            code="internal_server_error",
            message="An unexpected internal server error occurred.",
            details=None,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=jsonable_encoder(payload),
        )
