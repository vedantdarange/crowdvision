"""app/engine/smoothing.py — Pure Python rolling median smoother (contract §4.1).

No Flask, SQLAlchemy, sockets, or threading imports.
"""
from __future__ import annotations

import statistics
from collections import deque


class RollingMedian:
    """Rolling median over the last *window* raw person counts."""

    def __init__(self, window: int = 5) -> None:
        if window < 1:
            raise ValueError("smoothing window must be >= 1")
        self._window = int(window)
        self._buf: deque[float] = deque(maxlen=self._window)

    @property
    def window(self) -> int:
        return self._window

    @property
    def value(self) -> float | None:
        """Current median value, or None if no samples have been pushed."""
        if not self._buf:
            return None
        return float(statistics.median(self._buf))

    def push(self, raw_count: float) -> float:
        """Append *raw_count* and return the updated rolling median."""
        self._buf.append(float(raw_count))
        return float(statistics.median(self._buf))

    def resize(self, new_window: int) -> None:
        """Resize buffer while preserving the most recent samples (for reload)."""
        if new_window < 1:
            raise ValueError("smoothing window must be >= 1")
        if new_window == self._window:
            return
        self._window = int(new_window)
        self._buf = deque(self._buf, maxlen=self._window)

    def clear(self) -> None:
        """Discard buffered samples (e.g. when source restarts with reset=True)."""
        self._buf.clear()

    def __len__(self) -> int:
        return len(self._buf)
