"""app/realtime/emitter.py — Throttled Socket.IO zone event emitter (contract §7.2).

Rules (plan §8.3 / contract §7.2):
  - `emit_zone_update` -> room `public`, payload = `PublicZoneState`
  - `emit_zone_detail` -> room `role:police`, payload = `ZoneState`
  - Throttled per zone to <= 1 emit/second UNLESS `level` or `trend` changed.
  - Payloads are ALWAYS built via B2's `app.schemas.serializers` functions.
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
        # (event_name, zone_id) -> (last_emit_time_s, last_level, last_trend)
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

    def emit_zone_update(
        self,
        zone: "Zone",
        live_state: dict[str, Any],
    ) -> bool:
        """Emit `zone:update` (PublicZoneState) to room `public` if unthrottled.

        Returns True if emitted, False if suppressed by throttle.
        """
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
        """Emit `zone:detail` (ZoneState) to room `role:police` if unthrottled.

        Returns True if emitted, False if suppressed by throttle.
        """
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

    def reset(self) -> None:
        """Clear throttle state (useful in tests)."""
        with self._lock:
            self._last_sent.clear()


_fallback_emitter = RealtimeEmitter()


def _active_emitter() -> RealtimeEmitter:
    if has_app_context():
        container = current_app.extensions.get("container")
        if container is not None and hasattr(container, "emitter"):
            return container.emitter
    return _fallback_emitter


def emit_zone_update(zone: "Zone", live_state: dict[str, Any]) -> bool:
    """Convenience wrapper delegating to the active app container's emitter."""
    return _active_emitter().emit_zone_update(zone, live_state)


def emit_zone_detail(
    zone: "Zone",
    live_state: dict[str, Any],
    sources: list[dict[str, Any]],
    open_alert_id: int | None = None,
) -> bool:
    """Convenience wrapper delegating to the active app container's emitter."""
    return _active_emitter().emit_zone_detail(
        zone, live_state, sources=sources, open_alert_id=open_alert_id
    )
