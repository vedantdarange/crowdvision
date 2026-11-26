"""app/core/responses.py — Contract-compliant response helpers.

All routes use these helpers so the envelope is consistent.
Success: {data: …} or {data: …, pagination: …}
Delete:  204 no body
Error:   {error: {code, message, details?}}  (built by the global handler)
"""
from __future__ import annotations

from typing import Any

from flask import Response, jsonify


def ok(data: Any) -> tuple[Response, int]:
    """200 with {data: …}."""
    return jsonify({"data": data}), 200


def created(data: Any) -> tuple[Response, int]:
    """201 with {data: …}."""
    return jsonify({"data": data}), 201


def no_content() -> Response:
    """204 — no body."""
    return Response(status=204)


def paginated(
    data: list[Any], total: int, page: int, limit: int
) -> tuple[Response, int]:
    """200 with {data: […], pagination: {…}}."""
    total_pages = max(1, (total + limit - 1) // limit)
    return (
        jsonify(
            {
                "data": data,
                "pagination": {
                    "total": total,
                    "page": page,
                    "limit": limit,
                    "total_pages": total_pages,
                },
            }
        ),
        200,
    )


def error_response(
    code: str, message: str, details: Any = None, status: int = 500
) -> tuple[Response, int]:
    """Build the standard error envelope."""
    body: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        body["details"] = details
    return jsonify({"error": body}), status
