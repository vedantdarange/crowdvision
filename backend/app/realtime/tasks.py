"""app/realtime/tasks.py — 1 Hz background task loop (plan §8.3 / §9 B4).

Responsibilities on each 1 s tick (inside `app.app_context()`):
  1. enforce_session_freshness(now)
  2. engine.tick(now) -> AlertService.persist_actions -> post-commit dispatch
  3. source ONLINE/OFFLINE transition check -> emit `source:status` on change
  4. Persist `zone_samples` (<= 1 per 2 s per zone with data)
  5. Expire advisories whose `expires_at <= now` -> commit + emit `advisory:retracted`
  6. Hourly retention delete (`zone_samples` older than 7 days)
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from app.core.time import to_iso_z
from app.extensions import db, socketio
from app.models.models import ZoneSample
from app.realtime.connect import enforce_session_freshness

if TYPE_CHECKING:
    from flask import Flask

logger = logging.getLogger(__name__)


def _naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


class SourceStatusTracker:
    """Thread-safe tracker emitting `source:status` only on ONLINE <-> OFFLINE change."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._status: dict[int, str] = {}

    def check_and_record(self, source_id: int, new_status: str) -> bool:
        """Record *new_status* and return True if it changed from the known status."""
        with self._lock:
            prev = self._status.get(source_id, "OFFLINE")
            if new_status != prev:
                self._status[source_id] = new_status
                return True
            if source_id not in self._status:
                self._status[source_id] = new_status
            return False

    def reset(self) -> None:
        with self._lock:
            self._status.clear()


class BackgroundSchedulerState:
    """Mutable throttling/retention timestamps for the 1 Hz background loop."""

    def __init__(self) -> None:
        self.last_sample_at: dict[int, datetime] = {}
        self.last_retention_at: datetime | None = None
        self.stop_event = threading.Event()
        self.started = False
        self.thread: threading.Thread | None = None

    def reset(self) -> None:
        self.last_sample_at.clear()
        self.last_retention_at = None


def run_tick_once(flask_app: "Flask", now: datetime | None = None) -> dict[str, Any]:
    """Execute one 1 Hz tick inside `flask_app.app_context()`.

    Returns a summary dict for diagnostics/tests.
    """
    with flask_app.app_context():
        container = flask_app.extensions["container"]
        tick_now = now or container.clock.utcnow()
        tick_naive = _naive_utc(tick_now)
        summary: dict[str, Any] = {
            "actions": 0,
            "samples_written": 0,
            "advisories_expired": 0,
            "samples_pruned": 0,
            "source_changes": 0,
        }

        # 1. Socket session freshness (B2)
        enforce_session_freshness(tick_now)

        # 2. Engine tick + atomic DB persistence + state snapshot
        active_sources = container.source_repo.list_all(include_inactive=False)
        active_zones = container.zone_repo.list_active()

        with container.engine_lock:
            actions = container.zone_engine.tick(tick_now)
            summary["actions"] = len(actions)
            effects = container.alert_service.persist_actions(
                actions, zone_engine=container.zone_engine
            )
            source_snapshots = {
                src.id: container.zone_engine.get_source_state(src.id, tick_now)
                for src in active_sources
            }
            zone_snapshots = {
                zone.id: container.zone_engine.get_zone_state(zone.id, tick_now)
                for zone in active_zones
            }

        # Dispatch realtime + push AFTER lock & DB commit
        container.alert_service.dispatch_side_effects(effects)

        # 3. Source ONLINE/OFFLINE transitions
        for src in active_sources:
            st_info = source_snapshots.get(src.id)
            cur_status = st_info["status"] if st_info is not None else "OFFLINE"
            last_frame_iso = (
                to_iso_z(st_info["last_frame_at"])
                if st_info is not None and st_info["last_frame_at"] is not None
                else None
            )
            if container.source_status_tracker.check_and_record(src.id, cur_status):
                container.emitter.emit_source_status(
                    src.id, src.zone_id, cur_status, last_frame_iso
                )
                summary["source_changes"] += 1

        # 4. Persist zone_samples (<= 1 per 2 s per zone with data)
        task_state: BackgroundSchedulerState = container.task_state
        samples_added = 0
        for zone in active_zones:
            z_state = zone_snapshots.get(zone.id)
            if z_state is None or z_state["level"] == "NO_DATA":
                continue
            if z_state["live_updated_at"] is None:
                continue
            last_ts = task_state.last_sample_at.get(zone.id)
            if last_ts is not None and (tick_now - last_ts).total_seconds() < 2.0:
                continue
            container.zone_sample_repo.add(
                ZoneSample(  # pyrefly: ignore[unexpected-keyword]
                    zone_id=zone.id,
                    ts=tick_naive,
                    count=z_state["count"],
                    density=z_state["density"],
                    level=z_state["level"],
                )
            )
            task_state.last_sample_at[zone.id] = tick_now
            samples_added += 1

        if samples_added > 0:
            db.session.commit()
        summary["samples_written"] = samples_added

        # 5. Expire advisories whose expires_at <= now
        expired_ids = container.advisory_service.expire_due_advisories(tick_now)
        summary["advisories_expired"] = len(expired_ids)

        # 6. Hourly retention delete (zone_samples > 7 days)
        if (
            task_state.last_retention_at is None
            or (tick_now - task_state.last_retention_at).total_seconds() >= 3600.0
        ):
            cutoff_naive = tick_naive - timedelta(days=7)
            pruned = container.zone_sample_repo.delete_older_than(cutoff_naive)
            db.session.commit()
            task_state.last_retention_at = tick_now
            summary["samples_pruned"] = pruned

        return summary


def _loop_worker(flask_app: "Flask", interval_s: float = 1.0) -> None:
    """Background 1 Hz worker running safely inside try/except."""
    container = flask_app.extensions["container"]
    stop_event = container.task_state.stop_event
    logger.info("1 Hz background loop started")
    while not stop_event.is_set():
        try:
            run_tick_once(flask_app)
        except Exception:
            logger.exception("Error in 1 Hz background loop tick")
            try:
                with flask_app.app_context():
                    db.session.rollback()
            except Exception:
                pass
        socketio.sleep(interval_s)
    logger.info("1 Hz background loop stopped")


def start_background_loop(flask_app: "Flask", interval_s: float = 1.0) -> None:
    """Start the single 1 Hz Socket.IO background task if not already running."""
    container = flask_app.extensions["container"]
    if container.task_state.started:
        return
    container.task_state.stop_event.clear()
    container.task_state.started = True
    container.task_state.thread = socketio.start_background_task(
        _loop_worker, flask_app, interval_s
    )


def stop_background_loop(flask_app: "Flask") -> None:
    """Signal the background loop to stop and wait briefly for exit."""
    container = flask_app.extensions["container"]
    container.task_state.stop_event.set()
    t = container.task_state.thread
    if t is not None and t.is_alive():
        t.join(timeout=2.0)
    container.task_state.thread = None
    container.task_state.started = False
