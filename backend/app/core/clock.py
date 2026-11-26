"""app/core/clock.py — Injected clock abstraction.

The engine and anything time-sensitive receive a Clock so tests can
advance time deterministically without sleeping.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """Minimal clock interface used throughout the engine."""

    def utcnow(self) -> datetime:
        """Return the current time as a timezone-aware UTC datetime."""
        ...

    def time(self) -> float:
        """Return the current time as a Unix timestamp (float seconds)."""
        ...


class SystemClock:
    """Production clock — delegates to the real wall clock."""

    def utcnow(self) -> datetime:
        return datetime.now(timezone.utc)

    def time(self) -> float:
        return time.time()


class FakeClock:
    """Deterministic clock for tests.

    Usage::

        clock = FakeClock(start=0.0)
        clock.advance(5)   # move forward 5 seconds
        assert clock.time() == 5.0
    """

    def __init__(self, start: float = 0.0) -> None:
        self._t = start

    def utcnow(self) -> datetime:
        return datetime.fromtimestamp(self._t, tz=timezone.utc)

    def time(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        """Advance the clock by *seconds*."""
        self._t += seconds

    def set(self, t: float) -> None:
        """Set the clock to an absolute Unix timestamp."""
        self._t = t
