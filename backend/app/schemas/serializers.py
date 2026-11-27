"""app/schemas/serializers.py — Pure serializer functions for Zone and Source.

These functions take ORM objects and an optional live_state dict and return
plain dicts matching contract §5. They are reused by both REST routes and
Socket.IO realtime events so REST and WS shapes never drift.

PublicZoneState (contract §5):
    zone_id, name, geometry, centroid, level, trend, density, updated_at

ZoneState (contract §5):
    id, name, description, geometry, centroid, area_m2, mode,
    warning_density, critical_density, warning_count, critical_count,
    is_active, created_at, updated_at,
    level, trend, count, density, sources, open_alert_id, live_updated_at

SourceInfo (contract §5):
    id, zone_id, name, kind, coverage_area_m2,
    is_active, status, last_frame_at, created_at
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from app.core.time import to_iso_z

if TYPE_CHECKING:
    from app.models.models import Source, Zone

# ---------------------------------------------------------------------------
# LiveState placeholder (filled by B4 engine)
# ---------------------------------------------------------------------------
LIVE_STATE_PLACEHOLDER: dict[str, Any] = {
    "level": "NO_DATA",
    "trend": "STEADY",
    "density": None,
    "count": None,
    "live_updated_at": None,
}


def _parse_geometry(geometry_json: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(geometry_json, str):
        return json.loads(geometry_json)
    return geometry_json


def serialize_public_zone(
    zone: "Zone",
    live_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a PublicZoneState dict (exact keys from contract §5).

    NEVER includes counts, thresholds, sources, or area_m2.
    """
    ls = live_state or LIVE_STATE_PLACEHOLDER
    density = ls["density"]
    if density is not None:
        density = round(float(density), 1)
    return {
        "zone_id": zone.id,
        "name": zone.name,
        "geometry": _parse_geometry(zone.geometry_json),
        "centroid": {
            "lat": zone.centroid_lat,
            "lng": zone.centroid_lng,
        },
        "level": ls["level"],
        "trend": ls["trend"],
        "density": density,
        "updated_at": ls["live_updated_at"],
    }


def serialize_zone(
    zone: "Zone",
    live_state: dict[str, Any] | None = None,
    sources: list[dict[str, Any]] | None = None,
    open_alert_id: int | None = None,
) -> dict[str, Any]:
    """Return a full ZoneState dict (admin/police view, contract §5)."""
    ls = live_state or LIVE_STATE_PLACEHOLDER
    return {
        "id": zone.id,
        "name": zone.name,
        "description": zone.description,
        "geometry": _parse_geometry(zone.geometry_json),
        "centroid": {
            "lat": zone.centroid_lat,
            "lng": zone.centroid_lng,
        },
        "area_m2": zone.area_m2,
        "mode": zone.mode,
        "warning_density": zone.warning_density,
        "critical_density": zone.critical_density,
        "warning_count": zone.warning_count,
        "critical_count": zone.critical_count,
        "is_active": zone.is_active,
        "created_at": to_iso_z(zone.created_at),
        "updated_at": to_iso_z(zone.updated_at),
        "level": ls["level"],
        "trend": ls["trend"],
        "count": ls["count"],
        "density": ls["density"],
        "sources": sources if sources is not None else [],
        "open_alert_id": open_alert_id,
        "live_updated_at": ls["live_updated_at"],
    }


def serialize_source(
    source: "Source",
    status: str = "OFFLINE",
    last_frame_at: str | None = None,
) -> dict[str, Any]:
    """Return a SourceInfo dict (contract §5).

    Status defaults to OFFLINE / last_frame_at None until B5 engine fills live values.
    """
    return {
        "id": source.id,
        "zone_id": source.zone_id,
        "name": source.name,
        "kind": source.kind,
        "coverage_area_m2": source.coverage_area_m2,
        "is_active": source.is_active,
        "status": status,
        "last_frame_at": last_frame_at,
        "created_at": to_iso_z(source.created_at),
    }
