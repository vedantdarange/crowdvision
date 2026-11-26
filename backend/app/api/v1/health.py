"""app/api/v1/health.py — GET /api/v1/health

Returns the shape required by contract §6.2:
  {status, db, detector, worker_alive, version}

detector is 'unavailable' and worker_alive is False until B5 builds the
real detection pipeline.
"""
from __future__ import annotations

import logging

from flask import Blueprint, Response

from app.config import settings
from app.core.responses import ok
from app.extensions import db

logger = logging.getLogger(__name__)

health_bp = Blueprint("health", __name__)


@health_bp.get("/health")
def health() -> tuple[Response, int]:
    """Return system health status."""
    db_status = "ok"
    try:
        db.session.execute(db.text("SELECT 1"))
    except Exception:
        logger.exception("Health check: DB query failed")
        db_status = "error"

    return ok(
        {
            "status": "ok" if db_status == "ok" else "degraded",
            "db": db_status,
            # B5 will replace these when the detection worker is wired up.
            "detector": "unavailable",
            "worker_alive": False,
            "version": settings.app_version,
        }
    )
