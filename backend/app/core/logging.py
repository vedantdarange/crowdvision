"""app/core/logging.py — Structured JSON logging + request-id middleware.

Every log record is emitted as JSON (python-json-logger). Each incoming
HTTP request is tagged with a UUID request_id so errors can be correlated
across log lines without leaking stack traces to API callers.
"""
from __future__ import annotations

import logging
import uuid

from flask import Flask, Response, g, has_request_context
from pythonjsonlogger.json import JsonFormatter


class _RequestIdFilter(logging.Filter):
    """Attach request_id from Flask's `g` to every log record during a request."""

    def filter(self, record: logging.LogRecord) -> bool:
        if has_request_context():
            record.request_id = getattr(g, "request_id", "")
        elif not hasattr(record, "request_id"):
            record.request_id = ""
        return True


def configure_logging(app: Flask) -> None:
    """Attach a JSON handler to the root logger and register request-id hooks."""
    log_level = logging.DEBUG if app.debug else logging.INFO

    handler = logging.StreamHandler()
    formatter = JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(request_id)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )
    handler.setFormatter(formatter)
    handler.addFilter(_RequestIdFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)

    # Silence noisy Werkzeug request logs at DEBUG; keep WARNING+.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    @app.before_request
    def _assign_request_id() -> None:
        g.request_id = str(uuid.uuid4())

    @app.after_request
    def _add_request_id_header(response: Response) -> Response:
        response.headers["X-Request-ID"] = getattr(g, "request_id", "")
        return response
