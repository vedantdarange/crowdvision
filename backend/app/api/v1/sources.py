"""app/api/v1/sources.py — Source CRUD endpoints (contract §6.2).

Route table (all under /api/v1):
  GET    /sources        — police+ (?zone_id=)
  POST   /sources        — police+ ({zone_id, name, kind, coverage_area_m2?})
  PATCH  /sources/{id}   — admin only
  DELETE /sources/{id}   — admin only
"""
from __future__ import annotations

from flask import Blueprint, request

from app.container import get_container
from app.core.auth import current_user, roles_required
from app.core.errors import ValidationAppError
from app.core.responses import created, no_content, ok
from app.core.validation import parse_json_body, validate
from app.schemas.sources import SourceCreateRequest, SourcePatchRequest

sources_bp = Blueprint("sources", __name__)


@sources_bp.get("/sources")
@roles_required("police")
def list_sources():
    current_user()
    raw_zone_id = request.args.get("zone_id")
    zone_id: int | None = None
    if raw_zone_id is not None and raw_zone_id != "":
        try:
            zone_id = int(raw_zone_id)
        except ValueError as exc:
            raise ValidationAppError(
                "zone_id must be an integer.",
                details={"zone_id": ["Must be a valid integer"]},
            ) from exc
    container = get_container()
    return ok(container.source_service.list_sources(zone_id=zone_id))


@sources_bp.post("/sources")
@roles_required("police")
def create_source():
    actor = current_user()
    req = validate(SourceCreateRequest, parse_json_body())
    container = get_container()
    return created(container.source_service.create_source(req, actor))


@sources_bp.patch("/sources/<int:source_id>")
@roles_required("admin")
def update_source(source_id: int):
    actor = current_user()
    req = validate(SourcePatchRequest, parse_json_body())
    container = get_container()
    return ok(container.source_service.update_source(source_id, req, actor))


@sources_bp.delete("/sources/<int:source_id>")
@roles_required("admin")
def delete_source(source_id: int):
    actor = current_user()
    container = get_container()
    container.source_service.delete_source(source_id, actor)
    return no_content()
