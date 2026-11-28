"""app/api/v1/analytics.py — Analytics summary and CSV export endpoints (contract §6.2 / plan §8.6).

Route table (all under /api/v1):
  GET /analytics/summary?from&to            — police+ (default last 24 h, IST peak hours)
  GET /analytics/export/alerts.csv?from&to  — admin (UTF-8 with BOM CSV download)
"""
from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, Response, request

from app.container import get_container
from app.core.auth import current_user, roles_required
from app.core.errors import ValidationAppError
from app.core.responses import ok

analytics_bp = Blueprint("analytics", __name__)


def _parse_iso_param(raw: str | None, field: str) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except ValueError as exc:
        raise ValidationAppError(
            f"Invalid ISO datetime for {field}.",
            details={field: ["Must be a valid ISO-8601 datetime"]},
        ) from exc


@analytics_bp.get("/analytics/summary")
@roles_required("police")
def analytics_summary():
    current_user()
    dt_from = _parse_iso_param(request.args.get("from"), "from")
    dt_to = _parse_iso_param(request.args.get("to"), "to")
    container = get_container()
    return ok(container.analytics_service.get_summary(dt_from=dt_from, dt_to=dt_to))


@analytics_bp.get("/analytics/export/alerts.csv")
@roles_required("admin")
def export_alerts_csv():
    current_user()
    dt_from = _parse_iso_param(request.args.get("from"), "from")
    dt_to = _parse_iso_param(request.args.get("to"), "to")
    container = get_container()
    csv_bytes = container.analytics_service.export_alerts_csv(
        dt_from=dt_from, dt_to=dt_to
    )
    return Response(
        csv_bytes,
        status=200,
        mimetype="text/csv",
        headers={
            "Content-Type": "text/csv; charset=utf-8",
            "Content-Disposition": 'attachment; filename="alerts.csv"',
        },
    )
