"""app/engine/zone_engine.py — Pure-Python ZoneEngine stub (# TEMPORARY until B4).

TEMPORARY until B4:
  This module provides a minimal in-memory LiveState updater so Phase B3
  can emit `zone:update` and `zone:detail` events from `fake-feed` without
  blocking on B4's full smoothing/hysteresis/debounce/alert state machine.

  No Flask or SQLAlchemy imports allowed in `app/engine/*`.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from app.core.time import to_iso_z


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# TEMPORARY until B4
class StubZoneEngine:
    """Thread-safe minimal LiveState updater (# TEMPORARY until B4).

    Computes raw `density = count / coverage_area_m2` and assigns a naive level
    directly from zone thresholds without smoothing, hysteresis, or debounce.
    Also tracks `last_frame_at` per source.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._source_last_frame: dict[int, datetime] = {}
        self._zone_states: dict[int, dict[str, Any]] = {}
        self._last_metric: dict[int, float] = {}

    def ingest(
        self,
        source_id: int,
        count: int,
        now: datetime,
        *,
        zone_cfg: dict[str, Any],
        source_cfg: dict[str, Any],
    ) -> dict[str, Any]:
        """Ingest one count reading for *source_id* and return updated zone LiveState."""
        now = _ensure_utc(now)
        zone_id = int(zone_cfg["id"])
        coverage = float(source_cfg["coverage_area_m2"])
        density = round(float(count) / max(coverage, 1e-6), 4)

        mode = str(zone_cfg.get("mode", "DENSITY"))
        w_cnt = zone_cfg.get("warning_count")
        c_cnt = zone_cfg.get("critical_count")

        if mode == "COUNT" and w_cnt is not None and c_cnt is not None:
            metric = float(count)
            warn_thresh = float(w_cnt)
            crit_thresh = float(c_cnt)
            trend_delta = 2.0
        else:
            metric = density
            warn_thresh = float(zone_cfg["warning_density"])
            crit_thresh = float(zone_cfg["critical_density"])
            trend_delta = 0.3

        if metric >= crit_thresh:
            level = "CRITICAL"
        elif metric >= warn_thresh:
            level = "WARNING"
        else:
            level = "SAFE"

        with self._lock:
            self._source_last_frame[source_id] = now

            prev_metric = self._last_metric.get(zone_id)
            if prev_metric is None:
                trend = "STEADY"
            elif metric - prev_metric >= trend_delta:
                trend = "RISING"
            elif prev_metric - metric >= trend_delta:
                trend = "FALLING"
            else:
                trend = "STEADY"
            self._last_metric[zone_id] = metric

            live_state: dict[str, Any] = {
                "level": level,
                "trend": trend,
                "density": round(density, 2),
                "count": float(count),
                "live_updated_at": to_iso_z(now),
            }
            self._zone_states[zone_id] = live_state
            return dict(live_state)

    def get_zone_live_state(self, zone_id: int) -> dict[str, Any] | None:
        """Return a copy of the latest LiveState for *zone_id*, or None if NO_DATA."""
        with self._lock:
            state = self._zone_states.get(zone_id)
            return dict(state) if state is not None else None

    def get_all_zone_live_states(self) -> dict[int, dict[str, Any]]:
        """Return {zone_id: live_state} for all zones that have received data."""
        with self._lock:
            return {zid: dict(st) for zid, st in self._zone_states.items()}

    def get_source_status(
        self,
        source_id: int,
        now: datetime,
        stale_after_s: float = 10.0,
    ) -> tuple[str, str | None]:
        """Return ('ONLINE'|'OFFLINE', last_frame_at_iso_or_None)."""
        now_utc = _ensure_utc(now)
        with self._lock:
            last_dt = self._source_last_frame.get(source_id)
        if last_dt is None:
            return "OFFLINE", None
        age_s = (now_utc - _ensure_utc(last_dt)).total_seconds()
        status = "ONLINE" if age_s <= stale_after_s else "OFFLINE"
        return status, to_iso_z(last_dt)

    def reset(self) -> None:
        """Clear all stored states (for test isolation)."""
        with self._lock:
            self._source_last_frame.clear()
            self._zone_states.clear()
            self._last_metric.clear()
