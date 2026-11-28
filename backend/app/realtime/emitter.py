"""app/realtime/emitter.py — Socket.IO event emitter with zone throttling (contract §7.2).

Rules (plan §8.3 / contract §7.2):
  - `zone:update`       -> room `public` (`PublicZoneState`)
  - `zone:detail`       -> room `role:police` (`ZoneState`)
  - `alert:new`         -> room `role:police` (`Alert`)
  - `alert:updated`     -> room `role:police` (`Alert`)
  - `alert:escalated`   -> room `role:police` (`{alert: Alert, reason}`)
  - `source:status`     -> room `role:police` (`{source_id, zone_id, status, last_frame_at}`)
  - `advisory:new`      -> room `public` (`Advisory`)
  - `advisory:retracted`-> room `public` (`{id}`)
  - Zone events throttled to <= 1 emit/s/zone unless `level` or `trend` changed.
"""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from flask import current_app, has_app_context

from app.core.clock import Clock, SystemClock
from app.extensions import socketio
from app.schemas.serializers import serialize_public_zone, serialize_zone

if TYPE_CHECKING:
    from app.models.models import Zone


class RealtimeEmitter:
    """Thread-safe Socket.IO emitter with per-(event, zone) 1 Hz throttling."""

    def __init__(self, clock: Clock | None = None, min_interval_s: float = 1.0) -> None:
        self._clock: Clock = clock or SystemClock()
        self._min_interval_s = float(min_interval_s)
        self._lock = threading.Lock()
        self._last_sent: dict[tuple[str, int], tuple[float, str, str]] = {}

    def _should_emit(self, event_name: str, zone_id: int, level: str, trend: str) -> bool:
        now_s = self._clock.time()
        key = (event_name, zone_id)
        with self._lock:
            prev = self._last_sent.get(key)
            if prev is None:
                self._last_sent[key] = (now_s, level, trend)
                return True
            last_t, last_level, last_trend = prev
            changed = (level != last_level) or (trend != last_trend)
            if changed or (now_s - last_t) >= self._min_interval_s:
                self._last_sent[key] = (now_s, level, trend)
                return True
            return False

    def emit_zone_update(self, zone: "Zone", live_state: dict[str, Any]) -> bool:
        level = str(live_state.get("level", "NO_DATA"))
        trend = str(live_state.get("trend", "STEADY"))
        if not self._should_emit("zone:update", zone.id, level, trend):
            return False
        payload = serialize_public_zone(zone, live_state)
        socketio.emit("zone:update", payload, to="public", namespace="/")
        return True

    def emit_zone_detail(
        self,
        zone: "Zone",
        live_state: dict[str, Any],
        sources: list[dict[str, Any]],
        open_alert_id: int | None = None,
    ) -> bool:
        level = str(live_state.get("level", "NO_DATA"))
        trend = str(live_state.get("trend", "STEADY"))
        if not self._should_emit("zone:detail", zone.id, level, trend):
            return False
        payload = serialize_zone(
            zone,
            live_state,
            sources=sources,
            open_alert_id=open_alert_id,
        )
        socketio.emit("zone:detail", payload, to="role:police", namespace="/")
        return True

    def emit_alert_new(self, alert_payload: dict[str, Any]) -> None:
        socketio.emit("alert:new", alert_payload, to="role:police", namespace="/")

    def emit_alert_updated(self, alert_payload: dict[str, Any]) -> None:
        socketio.emit("alert:updated", alert_payload, to="role:police", namespace="/")

    def emit_alert_escalated(self, alert_payload: dict[str, Any], reason: str) -> None:
        socketio.emit(
            "alert:escalated",
            {"alert": alert_payload, "reason": reason},
            to="role:police",
            namespace="/",
        )

    def emit_source_status(
        self,
        source_id: int,
        zone_id: int,
        status: str,
        last_frame_at: str | None,
    ) -> None:
        socketio.emit(
            "source:status",
            {
                "source_id": source_id,
                "zone_id": zone_id,
                "status": status,
                "last_frame_at": last_frame_at,
            },
            to="role:police",
            namespace="/",
        )

    def emit_advisory_new(self, advisory_payload: dict[str, Any]) -> None:
        socketio.emit("advisory:new", advisory_payload, to="public", namespace="/")

    def emit_advisory_retracted(self, advisory_id: int) -> None:
        socketio.emit(
            "advisory:retracted",
            {"id": advisory_id},
            to="public",
            namespace="/",
        )

    def emit_report_new(self, report_payload: dict[str, Any]) -> None:
        """Emit report:new strictly to police/admin room (contract §7.2)."""
        socketio.emit("report:new", report_payload, to="role:police", namespace="/")

    def emit_report_updated(
        self, report_payload: dict[str, Any], owner_id: int
    ) -> None:
        """Emit report:updated once per recipient across role:police and user:{owner} (contract §7.2)."""
        socketio.emit(
            "report:updated",
            report_payload,
            to=["role:police", f"user:{owner_id}"],
            namespace="/",
        )

    def emit_frame_result(self, sid: str, payload: dict[str, Any]) -> None:
        """Emit frame:result strictly to the submitting socket sid (contract §8)."""
        socketio.emit("frame:result", payload, to=sid, namespace="/")

    def reset(self) -> None:
        with self._lock:
            self._last_sent.clear()

    def prune_zones(self, active_zone_ids: set[int]) -> int:
        """Drop cached throttle timestamps for deactivated or deleted zones."""
        with self._lock:
            stale_keys = [k for k in self._last_sent if k[1] not in active_zone_ids]
            for k in stale_keys:
                self._last_sent.pop(k, None)
            return len(stale_keys)

    def prune_stale(self, max_age_s: float = 3600.0) -> int:
        """Drop cached throttle entries older than *max_age_s* seconds."""
        now_s = self._clock.time()
        with self._lock:
            stale_keys = [
                k
                for k, (last_t, _, _) in self._last_sent.items()
                if (now_s - last_t) >= max_age_s
            ]
            for k in stale_keys:
                self._last_sent.pop(k, None)
            return len(stale_keys)

    def stats(self) -> dict[str, int]:
        """Return bounded-state diagnostics for soak tests and health inspection."""
        with self._lock:
            return {"throttle_entries": len(self._last_sent)}


_fallback_emitter = RealtimeEmitter()


def _active_emitter() -> RealtimeEmitter:
    if has_app_context():
        container = current_app.extensions.get("container")
        if container is not None and hasattr(container, "emitter"):
            return container.emitter
    return _fallback_emitter


def emit_zone_update(zone: "Zone", live_state: dict[str, Any]) -> bool:
    return _active_emitter().emit_zone_update(zone, live_state)


def emit_zone_detail(
    zone: "Zone",
    live_state: dict[str, Any],
    sources: list[dict[str, Any]],
    open_alert_id: int | None = None,
) -> bool:
    return _active_emitter().emit_zone_detail(
        zone, live_state, sources=sources, open_alert_id=open_alert_id
    )
