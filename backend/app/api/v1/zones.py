"""app/api/v1/zones.py — Zone CRUD & History endpoints (contract §6.2).

Route table (all under /api/v1):
  GET    /zones/live          — public
  GET    /zones/{id}/public   — public
  GET    /zones/{id}/history  — police+ (?from&to&bucket_s=10)
  GET    /zones               — police+ (?include_inactive=true admin only)
  GET    /zones/{id}          — police+
  POST   /zones               — admin only
  PATCH  /zones/{id}          — admin only
  DELETE /zones/{id}          — admin only
"""
from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, request

from app.container import get_container
from app.core.auth import current_user, roles_required
from app.core.errors import ValidationAppError
from app.core.responses import created, no_content, ok
from app.core.validation import parse_json_body, validate
from app.schemas.zones import ZoneCreateRequest, ZonePatchRequest

zones_bp = Blueprint("zones", __name__)


def _parse_iso(raw: str | None, field: str) -> datetime | None:
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


@zones_bp.get("/zones/live")
def get_zones_live():
    container = get_container()
    return ok(container.zone_service.get_live())


@zones_bp.get("/zones/<int:zone_id>/public")
def get_zone_public(zone_id: int):
    container = get_container()
    return ok(container.zone_service.get_public(zone_id))


@zones_bp.get("/zones")
@roles_required("police")
def list_zones():
    actor = current_user()
    include_inactive = request.args.get("include_inactive", "").lower() in ("1", "true", "yes")
    container = get_container()
    return ok(container.zone_service.list_zones(include_inactive=include_inactive, actor=actor))


@zones_bp.get("/zones/<int:zone_id>")
@roles_required("police")
def get_zone(zone_id: int):
    current_user()
    container = get_container()
    return ok(container.zone_service.get_zone(zone_id))


@zones_bp.get("/zones/<int:zone_id>/history")
@roles_required("police")
def get_zone_history(zone_id: int):
    current_user()
    dt_from = _parse_iso(request.args.get("from"), "from")
    dt_to = _parse_iso(request.args.get("to"), "to")
    raw_bucket = request.args.get("bucket_s", "10")
    try:
        bucket_s = int(raw_bucket)
    except ValueError as exc:
        raise ValidationAppError(
            "bucket_s must be an integer.",
            details={"bucket_s": ["Allowed values: 10, 60, 300"]},
        ) from exc
    container = get_container()
    return ok(
        container.zone_service.get_history(
            zone_id, dt_from=dt_from, dt_to=dt_to, bucket_s=bucket_s
        )
    )


@zones_bp.post("/zones")
@roles_required("admin")
def create_zone():
    actor = current_user()
    req = validate(ZoneCreateRequest, parse_json_body())
    container = get_container()
    return created(container.zone_service.create_zone(req, actor))


@zones_bp.patch("/zones/<int:zone_id>")
@roles_required("admin")
def update_zone(zone_id: int):
    actor = current_user()
    req = validate(ZonePatchRequest, parse_json_body())
    container = get_container()
    return ok(container.zone_service.update_zone(zone_id, req, actor))


@zones_bp.delete("/zones/<int:zone_id>")
@roles_required("admin")
def delete_zone(zone_id: int):
    actor = current_user()
    container = get_container()
    container.zone_service.delete_zone(zone_id, actor)
    return no_content()
