"""app/detection/manager.py — DetectionManager skeleton (plan §8.2 / §9 B3).

Provides `ingest_count(source_id, count, now)` as the single entry point
shared by `fake-feed` (B3) and the real detector worker pump (B5).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.core.clock import Clock, SystemClock
from app.core.errors import NotFound
from app.detection.detector import Detector, FakeDetector
from app.engine.zone_engine import StubZoneEngine
from app.realtime.emitter import RealtimeEmitter
from app.repositories.source_repo import SourceRepository
from app.repositories.zone_repo import ZoneRepository
from app.schemas.serializers import serialize_source
from app.services.settings_service import SettingsService


class DetectionManager:
    """Coordinates detection results, engine ingestion, and realtime emission."""

    def __init__(
        self,
        *,
        detector: Detector | None = None,
        engine: StubZoneEngine,
        emitter: RealtimeEmitter,
        zone_repo: ZoneRepository,
        source_repo: SourceRepository,
        settings_service: SettingsService,
        clock: Clock | None = None,
    ) -> None:
        self.detector: Detector = detector or FakeDetector()
        self.engine = engine
        self.emitter = emitter
        self._zone_repo = zone_repo
        self._source_repo = source_repo
        self._settings = settings_service
        self._clock: Clock = clock or SystemClock()

    def ingest_count(
        self,
        source_id: int,
        count: int,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Ingest a person count for *source_id*, update engine state, and emit updates.

        Shared entry point for both `fake-feed` (B3) and real worker results (B5).
        Must be called within a Flask `app_context()`.
        """
        ts = now or self._clock.utcnow()
        source = self._source_repo.get(source_id)
        if source is None or not source.is_active:
            raise NotFound(f"Active source {source_id} not found.")

        zone = self._zone_repo.get(source.zone_id)
        if zone is None or not zone.is_active:
            raise NotFound(f"Active zone {source.zone_id} not found.")

        zone_cfg = {
            "id": zone.id,
            "mode": zone.mode,
            "warning_density": zone.warning_density,
            "critical_density": zone.critical_density,
            "warning_count": zone.warning_count,
            "critical_count": zone.critical_count,
        }
        source_cfg = {
            "id": source.id,
            "zone_id": source.zone_id,
            "coverage_area_m2": source.coverage_area_m2,
        }

        # Forward to engine stub (# TEMPORARY until B4)
        live_state = self.engine.ingest(
            source_id,
            count,
            ts,
            zone_cfg=zone_cfg,
            source_cfg=source_cfg,
        )

        # Build serialized sources + open alert for ZoneState
        stale_after_s = float(self._settings.get_settings().get("stale_after_s", 10.0))
        zone_sources = self._source_repo.list_by_zone(zone.id, include_inactive=False)
        serialized_sources = []
        for src in zone_sources:
            st, last_at = self.engine.get_source_status(src.id, ts, stale_after_s=stale_after_s)
            serialized_sources.append(serialize_source(src, status=st, last_frame_at=last_at))

        open_alert_id = self._zone_repo.get_open_alert_id(zone.id)

        # Emit realtime updates (throttled per zone)
        self.emitter.emit_zone_update(zone, live_state)
        self.emitter.emit_zone_detail(
            zone,
            live_state,
            sources=serialized_sources,
            open_alert_id=open_alert_id,
        )
        return live_state
