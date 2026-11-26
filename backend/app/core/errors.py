"""app/core/errors.py — AppError hierarchy.

Error codes match contract §6.1 exactly (case-sensitive).
The global handler is registered in app/__init__.py.
"""
from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for all application errors.

    Attributes:
        status: HTTP status code.
        code:   Contract error code string (§6.1).
        message: Human-readable message (never leak internals).
        details: Optional structured details (e.g. {field: [messages]}).
    """

    status: int = 500
    code: str = "INTERNAL"

    def __init__(
        self,
        message: str = "Something went wrong",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class BadRequest(AppError):
    status, code = 400, "BAD_REQUEST"


class ValidationAppError(AppError):
    status, code = 422, "VALIDATION_ERROR"


class Unauthenticated(AppError):
    status, code = 401, "UNAUTHENTICATED"


class Forbidden(AppError):
    status, code = 403, "FORBIDDEN"


class NotFound(AppError):
    status, code = 404, "NOT_FOUND"


class MethodNotAllowed(AppError):
    status, code = 405, "METHOD_NOT_ALLOWED"


class Conflict(AppError):
    status, code = 409, "CONFLICT"


class InvalidTransition(AppError):
    status, code = 409, "INVALID_TRANSITION"


class RateLimited(AppError):
    status, code = 429, "RATE_LIMITED"


class PayloadTooLarge(AppError):
    status, code = 413, "PAYLOAD_TOO_LARGE"


class DetectorUnavailable(AppError):
    status, code = 503, "DETECTOR_UNAVAILABLE"
