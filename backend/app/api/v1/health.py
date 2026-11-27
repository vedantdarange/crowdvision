"""app/api/v1/health.py — GET /api/v1/health

Returns the shape required by contract §6.2:
  {status, db, detector, worker_alive, version}
"""
from __future__ import annotations

import logging

from flask import Blueprint, Response, current_app, jsonify

from app.config import settings
from app.extensions import db

logger = logging.getLogger(__name__)

health_bp = Blueprint("health", __name__)


@health_bp.get("/health")
def health() -> tuple[Response, int]:
    """Return system health status including DB check and worker Ping/Pong."""
    db_status = "ok"
    try:
        db.session.execute(db.text("SELECT 1"))
    except Exception:
        logger.exception("Health check: DB query failed")
        db_status = "error"

    container = current_app.extensions.get("container")
    if container is not None and hasattr(container, "detection_manager"):
        detector_status, worker_alive = container.detection_manager.check_health()
    else:
        detector_status, worker_alive = "unavailable", False

    # Contract §6.2 returns the Health object at top level (no {data: ...} envelope).
    return (
        jsonify(
            {
                "status": "ok" if db_status == "ok" else "degraded",
                "db": db_status,
                "detector": detector_status,
                "worker_alive": worker_alive,
                "version": settings.app_version,
            }
        ),
        200,
    )
