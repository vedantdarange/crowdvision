"""app/services/source_service.py — Business logic for Sources (contract §6.2)."""
from __future__ import annotations

from typing import Any

from app.core.clock import Clock, SystemClock
from app.core.errors import Forbidden, NotFound, ValidationAppError
from app.core.time import utcnow
from app.engine.zone_engine import StubZoneEngine
from app.extensions import db
from app.models.models import Source, User, Zone
from app.repositories.source_repo import SourceRepository
from app.repositories.zone_repo import ZoneRepository
from app.schemas.serializers import serialize_source
from app.schemas.sources import SourceCreateRequest, SourcePatchRequest
from app.services.audit_service import AuditService


class SourceService:
    def __init__(
        self,
        source_repo: SourceRepository,
        zone_repo: ZoneRepository,
        audit_service: AuditService,
        engine: StubZoneEngine | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._repo = source_repo
        self._zone_repo = zone_repo
        self._audit = audit_service
        self._engine = engine
        self._clock: Clock = clock or SystemClock()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _get_active_zone_or_404(self, zone_id: int) -> Zone:
        zone = self._zone_repo.get(zone_id)
        if zone is None or not zone.is_active:
            raise NotFound(f"Zone {zone_id} not found.")
        return zone

    def _get_source_or_404(self, source_id: int) -> Source:
        source = self._repo.get(source_id)
        if source is None:
            raise NotFound(f"Source {source_id} not found.")
        return source

    def _validate_coverage(self, coverage: float, zone_area: float) -> None:
        """Validate 1 <= coverage <= 2 * zone.area_m2."""
        max_cov = 2.0 * zone_area
        if coverage < 1.0 or coverage > max_cov:
            msg = f"coverage_area_m2 must be between 1 and {max_cov:.1f} m² (2x zone area)."
            raise ValidationAppError(msg, details={"coverage_area_m2": [msg]})

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------
    def list_sources(self, zone_id: int | None = None) -> list[dict[str, Any]]:
        if zone_id is not None:
            self._get_active_zone_or_404(zone_id)
        sources = self._repo.list_all(zone_id=zone_id, include_inactive=False)
        if self._engine is None:
            return [serialize_source(s) for s in sources]
        now = self._clock.utcnow()
        stale_after_s = 10.0
        result = []
        for s in sources:
            st, last_at = self._engine.get_source_status(s.id, now, stale_after_s=stale_after_s)
            result.append(serialize_source(s, status=st, last_frame_at=last_at))
        return result

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------
    def create_source(self, req: SourceCreateRequest, actor: User) -> dict[str, Any]:
        zone = self._get_active_zone_or_404(req.zone_id)

        # Police MAY NOT send coverage_area_m2 — only admin can
        if req.coverage_area_m2 is not None and actor.role != "admin":
            raise Forbidden("Only admin may set coverage_area_m2.")

        coverage = req.coverage_area_m2 if req.coverage_area_m2 is not None else zone.area_m2
        self._validate_coverage(coverage, zone.area_m2)

        now = utcnow()
        source = Source(  # pyrefly: ignore[unexpected-keyword]
            zone_id=zone.id,
            name=req.name,
            kind=req.kind,
            coverage_area_m2=coverage,
            is_active=True,
            created_by=actor.id,
            created_at=now,
        )
        self._repo.add(source)
        self._audit.log(
            actor,
            "SOURCE_CREATED",
            "source",
            source.id,
            {"name": source.name, "zone_id": zone.id, "kind": source.kind},
        )
        db.session.commit()
        db.session.refresh(source)
        return serialize_source(source)

    def update_source(
        self, source_id: int, req: SourcePatchRequest, actor: User
    ) -> dict[str, Any]:
        source = self._get_source_or_404(source_id)
        zone = self._zone_repo.get(source.zone_id)
        if zone is None:
            raise NotFound(f"Zone {source.zone_id} not found.")

        if req.coverage_area_m2 is not None and actor.role != "admin":
            raise Forbidden("Only admin may set coverage_area_m2.")

        if req.name is not None:
            source.name = req.name
        if req.is_active is not None:
            source.is_active = req.is_active
        if req.coverage_area_m2 is not None:
            self._validate_coverage(req.coverage_area_m2, zone.area_m2)
            source.coverage_area_m2 = req.coverage_area_m2

        self._audit.log(actor, "SOURCE_UPDATED", "source", source.id, {"name": source.name})
        db.session.commit()
        db.session.refresh(source)
        return serialize_source(source)

    def delete_source(self, source_id: int, actor: User) -> None:
        source = self._get_source_or_404(source_id)
        if not source.is_active:
            raise NotFound(f"Source {source_id} not found.")
        source.is_active = False
        self._audit.log(actor, "SOURCE_DELETED", "source", source_id, {"name": source.name})
        db.session.commit()
