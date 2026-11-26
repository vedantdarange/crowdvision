"""app/core/validation.py — Request JSON parsing and Pydantic v2 validation."""
from __future__ import annotations

from typing import Any, TypeVar

from flask import request
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from app.core.errors import BadRequest, ValidationAppError

T = TypeVar("T", bound=BaseModel)


def _format_errors(exc: PydanticValidationError) -> dict[str, list[str]]:
    details: dict[str, list[str]] = {}
    for err in exc.errors():
        loc = ".".join(str(part) for part in err.get("loc", ())) or "_root"
        details.setdefault(loc, []).append(err.get("msg", "Invalid value"))
    return details


def parse_json_body() -> dict[str, Any]:
    """Parse the request body as a JSON object or raise BadRequest."""
    data = request.get_json(silent=False)
    if not isinstance(data, dict):
        raise BadRequest("Request body must be a JSON object.")
    return data


def validate(schema_cls: type[T], data: Any) -> T:
    """Validate *data* against *schema_cls* or raise ValidationAppError."""
    try:
        return schema_cls.model_validate(data)
    except PydanticValidationError as exc:
        raise ValidationAppError(
            message="Validation failed.",
            details=_format_errors(exc),
        ) from exc
