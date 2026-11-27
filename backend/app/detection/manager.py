"""app/detection/manager.py — DetectionManager wiring ZoneEngine + AlertService (plan §8.2 / §9 B4)."""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

from app.core.clock import Clock, SystemClock
from app.core.errors import NotFound
from app.core.time import to_iso_z
from app.detection.detector import Detector, FakeDetector
from app.engine.zone_engine import ZoneEngine
from app.realtime.emitter import RealtimeEmitter
from app.realtime.tasks import SourceStatusTracker
from app.repositories.source_repo import SourceRepository
from app.repositories.zone_repo import ZoneRepository
from app.services.alert_service import AlertService
from app.services.engine_sync import format_zone_live_state, reload_engine_from_db
from app.services.settings_service import SettingsService


class DetectionManager:
    """Coordinates detection counts -> ZoneEngine -> AlertService.apply -> realtime."""

    def __init__(
        self,
        *,
        detector: Detector | None = None,
        zone_engine: ZoneEngine,
        engine_lock: threading.Lock,
        alert_service: AlertService,
        emitter: RealtimeEmitter,
        zone_repo: ZoneRepository,
        source_repo: SourceRepository,
        settings_service: SettingsService,
        source_status_tracker: SourceStatusTracker,
        clock: Clock | None = None,
    ) -> None:
        self.detector: Detector = detector or FakeDetector()
        self.engine = zone_engine
        self._engine_lock = engine_lock
        self._alert_service = alert_service
        self.emitter = emitter
        self._zone_repo = zone_repo
        self._source_repo = source_repo
        self._settings = settings_service
        self._source_status_tracker = source_status_tracker
        self._clock: Clock = clock or SystemClock()

    def ingest_count(
        self,
        source_id: int,
        count: int,
        now: datetime | None = None,
        *,
        reset: bool = False,
    ) -> dict[str, Any]:
        """Ingest one count reading for *source_id* through ZoneEngine + AlertService.

        Shared single entry point for both `fake-feed` (B3) and real worker frames (B5).
        """
        ts = now or self._clock.utcnow()
        source = self._source_repo.get(source_id)
        if source is None or not source.is_active:
            raise NotFound(f"Active source {source_id} not found.")

        zone = self._zone_repo.get(source.zone_id)
        if zone is None or not zone.is_active:
            raise NotFound(f"Active zone {source.zone_id} not found.")

        with self._engine_lock:
            # Ensure ZoneEngine knows about this source/zone (preserving existing buffers)
            if (
                source.id not in self.engine._sources
                or zone.id not in self.engine._zones
            ):
                reload_engine_from_db(
                    zone_engine=self.engine,
                    zone_repo=self._zone_repo,
                    source_repo=self._source_repo,
                    settings_service=self._settings,
                )

            actions = self.engine.ingest(source_id, count, ts, reset=reset)
            effects = self._alert_service.persist_actions(
                actions, zone_engine=self.engine
            )
            eng_state = self.engine.get_zone_state(zone.id, ts)
            src_state = self.engine.get_source_state(source.id, ts)

        # Post-commit realtime dispatch OUTSIDE lock
        self._alert_service.dispatch_side_effects(effects)

        if src_state is not None and self._source_status_tracker.check_and_record(
            source.id, src_state["status"]
        ):
            self.emitter.emit_source_status(
                source.id,
                source.zone_id,
                src_state["status"],
                to_iso_z(src_state["last_frame_at"]),
            )

        return format_zone_live_state(eng_state)
