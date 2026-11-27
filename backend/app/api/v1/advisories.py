"""app/api/v1/advisories.py — Advisory REST endpoints (contract §6.2).

Route table (all under /api/v1):
  GET    /advisories       — public (?zone_id=)
  POST   /advisories       — police+
  DELETE /advisories/{id}  — police+
"""
from __future__ import annotations

from flask import Blueprint, request

from app.container import get_container
from app.core.auth import current_user, roles_required
from app.core.errors import ValidationAppError
from app.core.responses import created, no_content, ok
from app.core.validation import parse_json_body, validate
from app.schemas.advisories import AdvisoryCreateRequest

advisories_bp = Blueprint("advisories", __name__)


@advisories_bp.get("/advisories")
def list_advisories():
    raw_zone = request.args.get("zone_id")
    zone_id: int | None = None
    if raw_zone is not None and raw_zone != "":
        try:
            zone_id = int(raw_zone)
        except ValueError as exc:
            raise ValidationAppError(
                "zone_id must be an integer.",
                details={"zone_id": ["Must be an integer"]},
            ) from exc
    container = get_container()
    return ok(container.advisory_service.list_public(zone_id=zone_id))


@advisories_bp.post("/advisories")
@roles_required("police")
def create_advisory():
    actor = current_user()
    req = validate(AdvisoryCreateRequest, parse_json_body())
    container = get_container()
    return created(container.advisory_service.create(req, actor))


@advisories_bp.delete("/advisories/<int:advisory_id>")
@roles_required("police")
def delete_advisory(advisory_id: int):
    actor = current_user()
    container = get_container()
    container.advisory_service.retract(advisory_id, actor)
    return no_content()
