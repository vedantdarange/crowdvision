"""app/engine/zone_machine.py — Pure Python per-zone level & trend state machine.

Implements contract §4.2 and plan §8.1:
  - Hysteresis factor h (default 0.85)
  - Debounce hold before moving UP (`debounce_s`)
  - Clear hold before moving DOWN (`clear_s`)
  - Pending timer reset whenever candidate target changes
  - Immediate `NO_DATA` on stale outage; immediate level application on recovery
  - 60 s sliding-window trend (`RISING`, `FALLING`, `STEADY`)

No Flask, SQLAlchemy, sockets, or threading imports.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

_RANK: dict[str, int] = {
    "NO_DATA": -1,
    "SAFE": 0,
    "WARNING": 1,
    "CRITICAL": 2,
}

_TREND_WINDOW_S = 60.0


@dataclass(frozen=True)
class LevelTransition:
    """Emitted by `ZoneMachine.step()` when the zone's confirmed level changes."""

    old_level: str
    new_level: str


def _target_for_fresh(metric: float, warning: float, critical: float) -> str:
    if metric >= critical:
        return "CRITICAL"
    if metric >= warning:
        return "WARNING"
    return "SAFE"


class ZoneMachine:
    """Per-zone level & trend state machine with injected timestamps (float seconds)."""

    def __init__(self, initial_level: str = "NO_DATA") -> None:
        if initial_level not in _RANK:
            raise ValueError(f"Invalid initial_level {initial_level!r}")
        self.level: str = initial_level
        self.pending_target: str | None = None
        self.pending_since: float | None = None
        self.metric_history: deque[tuple[float, float]] = deque()
        self.last_metric: float | None = None

    def _prune_history(self, now_s: float) -> None:
        while self.metric_history and (now_s - self.metric_history[0][0]) > _TREND_WINDOW_S:
            self.metric_history.popleft()

    def clear_pending(self) -> None:
        self.pending_target = None
        self.pending_since = None

    def step(
        self,
        metric: float | None,
        now_s: float,
        *,
        warning: float,
        critical: float,
        hysteresis_ratio: float,
        debounce_s: float,
        clear_s: float,
        is_new_sample: bool = True,
    ) -> LevelTransition | None:
        """Advance the state machine for *metric* at timestamp *now_s*.

        Args:
            metric: Zone metric (density or smoothed count), or None if no fresh source.
            now_s: Current Unix timestamp in seconds.
            warning: Warning threshold (W).
            critical: Critical threshold (C).
            hysteresis_ratio: Hysteresis multiplier h in (0, 1).
            debounce_s: Hold duration before upgrading level.
            clear_s: Hold duration before downgrading level.
            is_new_sample: True on `ingest`, False on periodic `tick`.

        Returns:
            `LevelTransition` if `self.level` changed, otherwise None.
        """
        self._prune_history(now_s)

        if metric is None:
            self.last_metric = None
            self.clear_pending()
            if self.level != "NO_DATA":
                old = self.level
                self.level = "NO_DATA"
                return LevelTransition(old_level=old, new_level="NO_DATA")
            return None

        if is_new_sample or self.last_metric is None or metric != self.last_metric:
            self.metric_history.append((now_s, float(metric)))
            self._prune_history(now_s)
        self.last_metric = float(metric)

        # Leaving NO_DATA: apply first confirmed level immediately (no debounce)
        if self.level == "NO_DATA":
            new_level = _target_for_fresh(metric, warning, critical)
            self.level = new_level
            self.clear_pending()
            return LevelTransition(old_level="NO_DATA", new_level=new_level)

        # Hysteresis target calculation (contract §4.2)
        w_low = warning * hysteresis_ratio
        c_low = critical * hysteresis_ratio

        if self.level == "SAFE":
            if metric >= critical:
                target = "CRITICAL"
            elif metric >= warning:
                target = "WARNING"
            else:
                target = "SAFE"
        elif self.level == "WARNING":
            if metric >= critical:
                target = "CRITICAL"
            elif metric < w_low:
                target = "SAFE"
            else:
                target = "WARNING"
        else:  # CRITICAL
            if metric < w_low:
                target = "SAFE"
            elif metric < c_low:
                target = "WARNING"
            else:
                target = "CRITICAL"

        if target == self.level:
            self.clear_pending()
            return None

        if target != self.pending_target:
            self.pending_target = target
            self.pending_since = now_s

        hold = debounce_s if _RANK[target] > _RANK[self.level] else clear_s
        assert self.pending_since is not None
        if (now_s - self.pending_since) >= hold:
            old = self.level
            self.level = target
            self.clear_pending()
            return LevelTransition(old_level=old, new_level=target)

        return None

    def trend(self, now_s: float, mode: str) -> str:
        """Compute 60 s metric trend: 'RISING', 'FALLING', or 'STEADY'."""
        self._prune_history(now_s)
        if self.level == "NO_DATA" or len(self.metric_history) < 2:
            return "STEADY"
        oldest_val = self.metric_history[0][1]
        latest_val = self.metric_history[-1][1]
        diff = latest_val - oldest_val
        delta = 2.0 if mode == "COUNT" else 0.3
        if diff >= delta:
            return "RISING"
        if diff <= -delta:
            return "FALLING"
        return "STEADY"
