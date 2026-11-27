"""app/api/v1/alerts.py — Alert REST endpoints (contract §6.2).

Route table (all under /api/v1):
  GET  /alerts                     — police+
  GET  /alerts/{id}                — police+
  POST /alerts/{id}/acknowledge    — police+
  POST /alerts/{id}/respond        — police+
  POST /alerts/{id}/resolve        — police+
"""
from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, request

from app.container import get_container
from app.core.auth import current_user, roles_required
from app.core.errors import ValidationAppError
from app.core.responses import ok, paginated
from app.core.validation import validate
from app.schemas.alerts import AlertActionNoteRequest

alerts_bp = Blueprint("alerts", __name__)


def _parse_iso_param(raw: str | None, field: str) -> datetime | None:
    if not raw:
        return None
    try:
        cleaned = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except ValueError as exc:
        raise ValidationAppError(
            f"Invalid ISO datetime for {field}.",
            details={field: ["Must be a valid ISO-8601 datetime"]},
        ) from exc


def _parse_optional_note() -> str | None:
    if not request.data:
        return None
    raw = request.get_json(silent=False)
    if not isinstance(raw, dict):
        raise ValidationAppError("Request body must be a JSON object.")
    req = validate(AlertActionNoteRequest, raw)
    return req.note


@alerts_bp.get("/alerts")
@roles_required("police")
def list_alerts():
    current_user()
    raw_status = request.args.get("status")
    statuses = [s.strip() for s in raw_status.split(",") if s.strip()] if raw_status else None
    level = request.args.get("level") or None

    raw_zone = request.args.get("zone_id")
    zone_id: int | None = None
    if raw_zone is not None and raw_zone != "":
        try:
            zone_id = int(raw_zone)
        except ValueError as exc:
            raise ValidationAppError("zone_id must be an integer.") from exc

    dt_from = _parse_iso_param(request.args.get("from"), "from")
    dt_to = _parse_iso_param(request.args.get("to"), "to")

    raw_active = request.args.get("active")
    active: bool | None = None
    if raw_active is not None and raw_active != "":
        active = raw_active.lower() in ("1", "true", "yes")

    try:
        page = max(1, int(request.args.get("page", 1)))
        limit = max(1, min(100, int(request.args.get("limit", 20))))
    except ValueError as exc:
        raise ValidationAppError("page and limit must be integers.") from exc

    sort = request.args.get("sort", "-created_at")

    container = get_container()
    items, total = container.alert_service.list_alerts(
        statuses=statuses,
        level=level,
        zone_id=zone_id,
        dt_from=dt_from,
        dt_to=dt_to,
        active=active,
        page=page,
        limit=limit,
        sort=sort,
    )
    return paginated(items, total=total, page=page, limit=limit)


@alerts_bp.get("/alerts/<int:alert_id>")
@roles_required("police")
def get_alert(alert_id: int):
    current_user()
    container = get_container()
    return ok(container.alert_service.get_alert_detail(alert_id))


@alerts_bp.post("/alerts/<int:alert_id>/acknowledge")
@roles_required("police")
def acknowledge_alert(alert_id: int):
    actor = current_user()
    note = _parse_optional_note()
    container = get_container()
    return ok(container.alert_service.acknowledge(alert_id, actor, note=note))


@alerts_bp.post("/alerts/<int:alert_id>/respond")
@roles_required("police")
def respond_alert(alert_id: int):
    actor = current_user()
    note = _parse_optional_note()
    container = get_container()
    return ok(container.alert_service.respond(alert_id, actor, note=note))


@alerts_bp.post("/alerts/<int:alert_id>/resolve")
@roles_required("police")
def resolve_alert(alert_id: int):
    actor = current_user()
    note = _parse_optional_note()
    container = get_container()
    return ok(container.alert_service.resolve(alert_id, actor, note=note))
