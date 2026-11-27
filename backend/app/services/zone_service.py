"""app/services/zone_service.py — Business logic for Zones."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.core.errors import Conflict, Forbidden, NotFound, ValidationAppError
from app.core.geometry import polygon_area_m2, polygon_centroid
from app.core.time import utcnow
from app.engine.zone_engine import StubZoneEngine
from app.extensions import db
from app.models.models import User, Zone
from app.repositories.source_repo import SourceRepository
from app.repositories.zone_repo import ZoneRepository
from app.schemas.serializers import (
    LIVE_STATE_PLACEHOLDER,
    serialize_public_zone,
    serialize_source,
    serialize_zone,
)
from app.schemas.zones import ZoneCreateRequest, ZonePatchRequest
from app.services.audit_service import AuditService
from app.services.settings_service import SettingsService


class ZoneService:
    def __init__(
        self,
        zone_repo: ZoneRepository,
        source_repo: SourceRepository,
        audit_service: AuditService,
        settings_service: SettingsService,
        engine: StubZoneEngine | None = None,
    ) -> None:
        self._repo = zone_repo
        self._source_repo = source_repo
        self._audit = audit_service
        self._settings = settings_service
        self._engine = engine

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _get_or_404(self, zone_id: int) -> Zone:
        zone = self._repo.get(zone_id)
        if zone is None:
            raise NotFound(f"Zone {zone_id} not found.")
        return zone

    def _check_name_unique(self, name: str, exclude_id: int | None = None) -> None:
        existing = self._repo.get_by_name_active(name)
        if existing is not None and existing.id != exclude_id:
            raise Conflict(f"A zone named '{name}' already exists.")

    def _compute_and_validate_area(
        self,
        geometry: dict[str, Any],
        client_hint: float | None,
    ) -> tuple[float, float, float]:
        """Compute server area and centroid; validate client hint.

        Returns (area_m2, centroid_lat, centroid_lng).
        Raises ValidationAppError if hint differs by > 10% or area is out of bounds.
        """
        try:
            server_area = polygon_area_m2(geometry)
            centroid_lat, centroid_lng = polygon_centroid(geometry)
        except ValueError as exc:
            raise ValidationAppError(str(exc), details={"geometry": [str(exc)]}) from exc

        if server_area < 1.0 or server_area > 10_000_000.0:
            msg = (
                f"Zone area must be between 1 and 10,000,000 m² "
                f"(computed: {server_area:.1f} m²)."
            )
            raise ValidationAppError(msg, details={"geometry": [msg]})

        if client_hint is not None:
            diff_ratio = abs(server_area - client_hint) / server_area
            if diff_ratio > 0.10:
                msg = (
                    f"Provided area_m2 ({client_hint:.1f}) differs from server-computed "
                    f"value ({server_area:.1f}) by more than 10%."
                )
                raise ValidationAppError(msg, details={"area_m2": [msg]})

        return server_area, centroid_lat, centroid_lng

    def _live_state_for(self, zone_id: int) -> dict[str, Any]:
        if self._engine is not None:
            st = self._engine.get_zone_live_state(zone_id)
            if st is not None:
                return st
        return LIVE_STATE_PLACEHOLDER

    def _serialize_full(self, zone: Zone) -> dict[str, Any]:
        now = utcnow()
        stale_after_s = float(self._settings.get_settings().get("stale_after_s", 10.0))
        sources = []
        for s in self._source_repo.list_by_zone(zone.id):
            if self._engine is not None:
                status, last_at = self._engine.get_source_status(
                    s.id, now, stale_after_s=stale_after_s
                )
                sources.append(serialize_source(s, status=status, last_frame_at=last_at))
            else:
                sources.append(serialize_source(s))
        open_alert_id = self._repo.get_open_alert_id(zone.id)
        return serialize_zone(
            zone,
            self._live_state_for(zone.id),
            sources=sources,
            open_alert_id=open_alert_id,
        )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------
    def get_live(self) -> list[dict[str, Any]]:
        """Return all active zones as PublicZoneState."""
        zones = self._repo.list_active()
        return [serialize_public_zone(z, self._live_state_for(z.id)) for z in zones]

    def get_public(
        self,
        zone_id: int,
        live_states: dict[int, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Return {state: PublicZoneState, alternatives: PublicZoneState[]} per contract §6.2."""
        zone = self._get_or_404(zone_id)
        if not zone.is_active:
            raise NotFound(f"Zone {zone_id} not found.")
        state_map = (
            live_states
            if live_states is not None
            else (self._engine.get_all_zone_live_states() if self._engine is not None else {})
        )
        own_state = state_map.get(zone.id, LIVE_STATE_PLACEHOLDER)
        alternatives = self._find_alternatives(zone, state_map)
        return {
            "state": serialize_public_zone(zone, own_state),
            "alternatives": alternatives,
        }

    def _find_alternatives(
        self,
        zone: Zone,
        state_map: dict[int, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Return up to 3 nearest active zones whose live level is SAFE."""
        candidates: list[tuple[float, Zone, dict[str, Any]]] = []
        for other in self._repo.list_active():
            if other.id == zone.id:
                continue
            ls = state_map.get(other.id, LIVE_STATE_PLACEHOLDER)
            if ls.get("level") != "SAFE":
                continue
            dlat = other.centroid_lat - zone.centroid_lat
            dlng = other.centroid_lng - zone.centroid_lng
            dist_sq = dlat * dlat + dlng * dlng
            candidates.append((dist_sq, other, ls))
        candidates.sort(key=lambda item: item[0])
        return [serialize_public_zone(other, ls) for _, other, ls in candidates[:3]]

    def list_zones(self, include_inactive: bool, actor: User) -> list[dict[str, Any]]:
        if include_inactive and actor.role != "admin":
            raise Forbidden("Only admin may include inactive zones.")
        zones = self._repo.list_all(include_inactive=include_inactive)
        open_alerts = self._repo.get_open_alert_ids_map()
        all_sources = self._source_repo.list_all(include_inactive=False)
        now = utcnow()
        stale_after_s = float(self._settings.get_settings().get("stale_after_s", 10.0))
        sources_by_zone: dict[int, list[dict[str, Any]]] = {}
        for src in all_sources:
            if self._engine is not None:
                st, last_at = self._engine.get_source_status(
                    src.id, now, stale_after_s=stale_after_s
                )
                ser = serialize_source(src, status=st, last_frame_at=last_at)
            else:
                ser = serialize_source(src)
            sources_by_zone.setdefault(src.zone_id, []).append(ser)
        return [
            serialize_zone(
                z,
                self._live_state_for(z.id),
                sources=sources_by_zone.get(z.id, []),
                open_alert_id=open_alerts.get(z.id),
            )
            for z in zones
        ]

    def get_zone(self, zone_id: int) -> dict[str, Any]:
        zone = self._get_or_404(zone_id)
        return self._serialize_full(zone)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------
    def create_zone(self, req: ZoneCreateRequest, actor: User) -> dict[str, Any]:
        self._check_name_unique(req.name)
        warn_default, crit_default = self._settings.get_defaults()

        warn_density = req.warning_density if req.warning_density is not None else warn_default
        crit_density = req.critical_density if req.critical_density is not None else crit_default
        if warn_density >= crit_density:
            raise ValidationAppError(
                "warning_density must be less than critical_density",
                details={"warning_density": ["warning_density must be less than critical_density"]},
            )

        area, lat, lng = self._compute_and_validate_area(req.geometry, req.area_m2)
        now = utcnow()
        zone = Zone(  # pyrefly: ignore[unexpected-keyword]
            name=req.name,
            description=req.description,
            geometry_json=json.dumps(req.geometry),
            centroid_lat=lat,
            centroid_lng=lng,
            area_m2=area,
            mode=req.mode,
            warning_density=warn_density,
            critical_density=crit_density,
            warning_count=req.warning_count,
            critical_count=req.critical_count,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        try:
            self._repo.add(zone)
            self._audit.log(actor, "ZONE_CREATED", "zone", zone.id, {"name": zone.name, "area_m2": zone.area_m2})
            db.session.commit()
        except IntegrityError as exc:
            db.session.rollback()
            raise Conflict(f"A zone named '{req.name}' already exists.") from exc
        db.session.refresh(zone)
        return self._serialize_full(zone)

    def update_zone(self, zone_id: int, req: ZonePatchRequest, actor: User) -> dict[str, Any]:
        zone = self._get_or_404(zone_id)

        target_name = req.name if req.name is not None else zone.name
        target_active = req.is_active if req.is_active is not None else zone.is_active
        if target_active and (req.name is not None or req.is_active is True):
            self._check_name_unique(target_name, exclude_id=zone_id)

        if req.name is not None:
            zone.name = req.name
        if req.description is not None:
            zone.description = req.description
        if req.is_active is not None:
            if not req.is_active and self._repo.has_open_alert(zone_id):
                raise Conflict("Cannot deactivate a zone with an open alert.")
            zone.is_active = req.is_active

        if req.geometry is not None:
            area, lat, lng = self._compute_and_validate_area(req.geometry, req.area_m2)
            zone.geometry_json = json.dumps(req.geometry)
            zone.centroid_lat = lat
            zone.centroid_lng = lng
            zone.area_m2 = area
        elif req.area_m2 is not None:
            current_geom = json.loads(zone.geometry_json)
            area, lat, lng = self._compute_and_validate_area(current_geom, req.area_m2)
            zone.centroid_lat = lat
            zone.centroid_lng = lng
            zone.area_m2 = area

        if req.mode is not None:
            zone.mode = req.mode
        if req.warning_density is not None:
            zone.warning_density = req.warning_density
        if req.critical_density is not None:
            zone.critical_density = req.critical_density
        if req.warning_count is not None:
            zone.warning_count = req.warning_count
        if req.critical_count is not None:
            zone.critical_count = req.critical_count

        # Cross-field validation after applying patch
        if zone.warning_density >= zone.critical_density:
            raise ValidationAppError(
                "warning_density must be less than critical_density",
                details={"warning_density": ["warning_density must be less than critical_density"]},
            )
        if zone.mode == "COUNT":
            if zone.warning_count is None or zone.critical_count is None:
                raise ValidationAppError(
                    "COUNT mode requires both warning_count and critical_count",
                    details={"mode": ["COUNT mode requires both warning_count and critical_count"]},
                )
            if zone.warning_count >= zone.critical_count:
                raise ValidationAppError(
                    "warning_count must be less than critical_count",
                    details={"warning_count": ["warning_count must be less than critical_count"]},
                )

        zone.updated_at = utcnow()
        try:
            self._audit.log(actor, "ZONE_UPDATED", "zone", zone.id, {"name": zone.name})
            db.session.commit()
        except IntegrityError as exc:
            db.session.rollback()
            raise Conflict(f"A zone named '{zone.name}' already exists.") from exc
        db.session.refresh(zone)
        return self._serialize_full(zone)

    def delete_zone(self, zone_id: int, actor: User) -> None:
        zone = self._get_or_404(zone_id)
        if not zone.is_active:
            raise NotFound(f"Zone {zone_id} not found.")
        if self._repo.has_open_alert(zone_id):
            raise Conflict("Cannot delete a zone with an open alert.")
        zone.is_active = False
        zone.updated_at = utcnow()
        self._audit.log(actor, "ZONE_DELETED", "zone", zone_id, {"name": zone.name})
        db.session.commit()
