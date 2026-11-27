"""app/services/source_service.py — Business logic for Sources (contract §6.2)."""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from app.core.clock import Clock, SystemClock
from app.core.errors import Forbidden, NotFound, ValidationAppError
from app.core.time import to_iso_z, utcnow
from app.engine.zone_engine import ZoneEngine
from app.extensions import db
from app.models.models import Source, User, Zone
from app.repositories.source_repo import SourceRepository
from app.repositories.zone_repo import ZoneRepository
from app.schemas.serializers import serialize_source
from app.schemas.sources import SourceCreateRequest, SourcePatchRequest
from app.services.audit_service import AuditService
from app.services.engine_sync import reload_engine_from_db

if TYPE_CHECKING:
    from app.services.settings_service import SettingsService


class SourceService:
    def __init__(
        self,
        source_repo: SourceRepository,
        zone_repo: ZoneRepository,
        audit_service: AuditService,
        settings_service: "SettingsService | None" = None,
        zone_engine: ZoneEngine | None = None,
        engine_lock: threading.Lock | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._repo = source_repo
        self._zone_repo = zone_repo
        self._audit = audit_service
        self._settings = settings_service
        self._engine = zone_engine
        self._engine_lock = engine_lock
        self._clock: Clock = clock or SystemClock()

    def _reload_engine(self) -> None:
        if self._engine is None or self._settings is None:
            return
        if self._engine_lock is not None:
            with self._engine_lock:
                reload_engine_from_db(
                    zone_engine=self._engine,
                    zone_repo=self._zone_repo,
                    source_repo=self._repo,
                    settings_service=self._settings,
                )
        else:
            reload_engine_from_db(
                zone_engine=self._engine,
                zone_repo=self._zone_repo,
                source_repo=self._repo,
                settings_service=self._settings,
            )

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
        max_cov = 2.0 * zone_area
        if coverage < 1.0 or coverage > max_cov:
            msg = f"coverage_area_m2 must be between 1 and {max_cov:.1f} m² (2x zone area)."
            raise ValidationAppError(msg, details={"coverage_area_m2": [msg]})

    def _serialize_one(self, src: Source) -> dict[str, Any]:
        if self._engine is None:
            return serialize_source(src)
        now = self._clock.utcnow()
        if self._engine_lock is not None:
            with self._engine_lock:
                st = self._engine.get_source_state(src.id, now)
        else:
            st = self._engine.get_source_state(src.id, now)
        if st is None:
            return serialize_source(src)
        return serialize_source(
            src,
            status=st["status"],
            last_frame_at=to_iso_z(st["last_frame_at"]),
        )

    def list_sources(self, zone_id: int | None = None) -> list[dict[str, Any]]:
        if zone_id is not None:
            self._get_active_zone_or_404(zone_id)
        sources = self._repo.list_all(zone_id=zone_id, include_inactive=False)
        return [self._serialize_one(s) for s in sources]

    def create_source(self, req: SourceCreateRequest, actor: User) -> dict[str, Any]:
        zone = self._get_active_zone_or_404(req.zone_id)

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
        self._reload_engine()
        return self._serialize_one(source)

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
        self._reload_engine()
        return self._serialize_one(source)

    def delete_source(self, source_id: int, actor: User) -> None:
        source = self._get_source_or_404(source_id)
        if not source.is_active:
            raise NotFound(f"Source {source_id} not found.")
        source.is_active = False
        self._audit.log(actor, "SOURCE_DELETED", "source", source_id, {"name": source.name})
        db.session.commit()
        self._reload_engine()
