"""app/schemas/serializers.py — Pure serializer functions for Zone, Source, Alert, Advisory.

These functions take ORM objects and optional live dicts and return plain dicts
matching contract §5. They are reused by both REST routes and Socket.IO realtime
events so REST and WS shapes never drift.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from app.core.time import to_iso_z

if TYPE_CHECKING:
    from app.models.models import Advisory, AlertEvent, AlertModel, Source, User, Zone

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


def _person_ref(user: "User | None") -> dict[str, Any] | None:
    if user is None:
        return None
    return {"id": user.id, "name": user.name}


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
    """Return a SourceInfo dict (contract §5)."""
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


def serialize_alert(
    alert: "AlertModel",
    zone: "Zone",
    users_by_id: dict[int, "User"] | None = None,
) -> dict[str, Any]:
    """Return an Alert dict (contract §5)."""
    umap = users_by_id or {}
    return {
        "id": alert.id,
        "zone_id": alert.zone_id,
        "zone_name": zone.name,
        "location": {
            "lat": zone.centroid_lat,
            "lng": zone.centroid_lng,
        },
        "level": alert.level,
        "peak_level": alert.peak_level,
        "status": alert.status,
        "condition_active": alert.condition_active,
        "peak_density": alert.peak_density,
        "peak_count": alert.peak_count,
        "created_at": to_iso_z(alert.created_at),
        "acknowledged_at": to_iso_z(alert.acknowledged_at),
        "acknowledged_by": (
            _person_ref(umap.get(alert.acknowledged_by))
            if alert.acknowledged_by is not None
            else None
        ),
        "responding_at": to_iso_z(alert.responding_at),
        "responding_by": (
            _person_ref(umap.get(alert.responding_by))
            if alert.responding_by is not None
            else None
        ),
        "resolved_at": to_iso_z(alert.resolved_at),
        "resolved_by": (
            _person_ref(umap.get(alert.resolved_by))
            if alert.resolved_by is not None
            else None
        ),
        "resolution_note": alert.resolution_note,
        "condition_cleared_at": to_iso_z(alert.condition_cleared_at),
        "last_escalated_at": to_iso_z(alert.last_escalated_at),
    }


def serialize_alert_event(
    event: "AlertEvent",
    actor: "User | None" = None,
) -> dict[str, Any]:
    """Return an AlertEvent dict (contract §5)."""
    try:
        data = json.loads(event.data_json) if event.data_json else {}
    except (json.JSONDecodeError, TypeError):
        data = {}
    return {
        "id": event.id,
        "alert_id": event.alert_id,
        "type": event.type,
        "actor": _person_ref(actor),
        "data": data,
        "created_at": to_iso_z(event.created_at),
    }


def serialize_alert_detail(
    alert: "AlertModel",
    zone: "Zone",
    events: list["AlertEvent"],
    users_by_id: dict[int, "User"] | None = None,
) -> dict[str, Any]:
    """Return an AlertDetail dict (contract §5)."""
    umap = users_by_id or {}
    base = serialize_alert(alert, zone, umap)
    base["events"] = [
        serialize_alert_event(ev, umap.get(ev.actor_id) if ev.actor_id is not None else None)
        for ev in events
    ]
    return base


def serialize_advisory(
    advisory: "Advisory",
    *,
    creator: "User",
    zone: "Zone | None" = None,
) -> dict[str, Any]:
    """Return an Advisory dict (contract §5)."""
    return {
        "id": advisory.id,
        "title": advisory.title,
        "body": advisory.body,
        "severity": advisory.severity,
        "zone_id": advisory.zone_id,
        "zone_name": zone.name if zone is not None else None,
        "created_by": {"id": creator.id, "name": creator.name},
        "created_at": to_iso_z(advisory.created_at),
        "expires_at": to_iso_z(advisory.expires_at),
        "is_active": advisory.is_active,
    }
