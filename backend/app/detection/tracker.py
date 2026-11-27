"""app/detection/tracker.py — Optional analytics tracker hook (plan §8.2).

Tracker output is strictly for optional analytics/eval (USE_TRACKER=true).
The occupancy count sent to ZoneEngine MUST ALWAYS be raw person box count
(`len(boxes)`), never tracker-confirmed count.
"""
from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

from app.detection.protocol import Box

logger = logging.getLogger(__name__)

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


class ByteTrackTrackerHook:
    """Optional per-source analytics tracker backed by `trackers.ByteTrackTracker` (2.7.x).

    Strictly for analytics/evaluation when USE_TRACKER=true; NEVER changes occupancy
    counts sent to ZoneEngine.
    """

    def __init__(
        self,
        *,
        frame_rate: float = 3.0,
        track_activation_threshold: float = 0.35,
        inactivity_reset_s: float = INACTIVITY_RESET_S,
        tracker_cls: Any = None,
    ) -> None:
        if tracker_cls is None:
            from trackers import ByteTrackTracker

            tracker_cls = ByteTrackTracker
        self._tracker_cls = tracker_cls
        self._frame_rate = max(1.0, float(frame_rate))
        self._track_activation_threshold = float(track_activation_threshold)
        self._inactivity_reset_s = float(inactivity_reset_s)
        self._trackers: dict[int, Any] = {}
        self._last_seen_s: dict[int, float] = {}
        self.reset_count_by_source: dict[int, int] = {}

    def _get_or_create(self, source_id: int) -> Any:
        tr = self._trackers.get(source_id)
        if tr is None:
            tr = self._tracker_cls(
                frame_rate=self._frame_rate,
                track_activation_threshold=self._track_activation_threshold,
            )
            self._trackers[source_id] = tr
        return tr

    def reset(self, source_id: int) -> None:
        """Reset and drop per-source ByteTrack state."""
        tr = self._trackers.pop(source_id, None)
        if tr is not None and hasattr(tr, "reset"):
            tr.reset()
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
        """Update per-source ByteTrackTracker and return tracked boxes (analytics only)."""
        import numpy as np
        import supervision as sv

        last_seen = self._last_seen_s.get(source_id)
        if reset or (
            last_seen is not None and (now_s - last_seen) >= self._inactivity_reset_s
        ):
            self.reset(source_id)

        tracker = self._get_or_create(source_id)
        if boxes:
            xyxy = np.array([[b[0], b[1], b[2], b[3]] for b in boxes], dtype=np.float32)
            confs = np.array([b[4] for b in boxes], dtype=np.float32)
            sv_det = sv.Detections(xyxy=xyxy, confidence=confs)
        else:
            sv_det = sv.Detections.empty()

        tracked = tracker.update(sv_det, timestamp=float(now_s))
        self._last_seen_s[source_id] = float(now_s)

        if tracked is None or len(tracked) == 0:
            return []
        t_xyxy = tracked.xyxy
        t_confs = tracked.confidence
        t_ids = tracked.tracker_id
        out: list[Box] = []
        for idx in range(len(tracked)):
            # Only confirmed tracks have tracker_id >= 0
            if t_ids is not None and int(t_ids[idx]) < 0:
                continue
            bx1, by1, bx2, by2 = t_xyxy[idx]
            score = float(t_confs[idx]) if t_confs is not None else 1.0
            out.append((float(bx1), float(by1), float(bx2), float(by2), score))
        return out


def build_tracker(
    use_tracker: bool,
    *,
    frame_rate: float = 3.0,
    track_activation_threshold: float = 0.35,
) -> TrackerHook | None:
    """Build optional analytics tracker when USE_TRACKER=true; falls back cleanly if uninstalled."""
    if not use_tracker:
        return None
    try:
        return ByteTrackTrackerHook(
            frame_rate=frame_rate,
            track_activation_threshold=track_activation_threshold,
        )
    except ImportError:
        logger.warning(
            "USE_TRACKER=true but 'trackers' package is not installed; "
            "using PassThroughTracker stub for analytics."
        )
        return PassThroughTracker()
