"""app/detection/tracker.py — Optional analytics tracker hook (plan §8.2).

Tracker output is strictly for optional analytics/eval (USE_TRACKER=true).
The occupancy count sent to ZoneEngine MUST ALWAYS be raw person box count
(`len(boxes)`), never tracker-confirmed count.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.detection.protocol import Box

INACTIVITY_RESET_S = 30.0


@runtime_checkable
class TrackerHook(Protocol):
    """Optional per-source tracker interface for analytics."""

    def update(
        self,
        source_id: int,
        boxes: list[Box],
        now_s: float,
        *,
        reset: bool = False,
    ) -> list[Box]:
        """Update tracker state for *source_id* and return tracked/filtered boxes."""
        ...

    def reset(self, source_id: int) -> None:
        """Clear any per-source tracking state for *source_id*."""
        ...


class PassThroughTracker:
    """Stub analytics tracker used when USE_TRACKER=true in Phase B5a.

    Enforces explicit `reset=True` and 30 s inactivity reset per source while
    passing detections through unchanged.
    """

    def __init__(self, inactivity_reset_s: float = INACTIVITY_RESET_S) -> None:
        self._inactivity_reset_s = float(inactivity_reset_s)
        self._last_seen_s: dict[int, float] = {}
        self.reset_count_by_source: dict[int, int] = {}

    def reset(self, source_id: int) -> None:
        """Clear tracking state for *source_id*."""
        self._last_seen_s.pop(source_id, None)
        self.reset_count_by_source[source_id] = (
            self.reset_count_by_source.get(source_id, 0) + 1
        )

    def update(
        self,
        source_id: int,
        boxes: list[Box],
        now_s: float,
        *,
        reset: bool = False,
    ) -> list[Box]:
        """Record activity, resetting on explicit reset or 30 s gap, and pass boxes through."""
        last_seen = self._last_seen_s.get(source_id)
        if reset or (
            last_seen is not None and (now_s - last_seen) >= self._inactivity_reset_s
        ):
            self.reset(source_id)
        self._last_seen_s[source_id] = float(now_s)
        return list(boxes)
