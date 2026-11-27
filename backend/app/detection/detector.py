"""app/detection/detector.py — Detector Protocol and FakeDetector (plan §8.2).

No torch / ultralytics imports in this phase; UltralyticsDetector is added in B5.
"""
from __future__ import annotations

import random
from typing import Any, Protocol, runtime_checkable

from app.detection.protocol import Box


@runtime_checkable
class Detector(Protocol):
    """Minimal detector interface implemented by FakeDetector and UltralyticsDetector."""

    def detect(
        self, frame: Any, source_id: int, conf: float, imgsz: int
    ) -> list[Box]:
        """Return normalised [x1, y1, x2, y2, conf] person boxes."""
        ...


class FakeDetector:
    """Deterministic fake detector for tests, CI, and fake-feed demos.

    Given the same *seed*, *source_id*, and configured count, `detect()`
    produces a deterministic list of valid normalised bounding boxes with
    confidence >= *conf*.
    """

    def __init__(
        self,
        seed: int = 42,
        default_count: int = 0,
        counts: dict[int, int] | None = None,
    ) -> None:
        self._seed = seed
        self._default_count = max(0, int(default_count))
        self._counts: dict[int, int] = dict(counts) if counts else {}
        self._rng_by_source: dict[int, random.Random] = {}

    def set_count(self, source_id: int, count: int) -> None:
        """Set the target person count to emit on subsequent calls for *source_id*."""
        self._counts[source_id] = max(0, int(count))

    def get_count(self, source_id: int) -> int:
        return self._counts.get(source_id, self._default_count)

    def _rng(self, source_id: int) -> random.Random:
        if source_id not in self._rng_by_source:
            self._rng_by_source[source_id] = random.Random(
                (self._seed * 1_000_003) ^ source_id
            )
        return self._rng_by_source[source_id]

    def detect(
        self, frame: Any, source_id: int, conf: float, imgsz: int
    ) -> list[Box]:
        """Return `count` deterministic normalised boxes for *source_id*."""
        target = self.get_count(source_id)
        rng = self._rng(source_id)
        min_conf = max(0.0, min(0.99, float(conf)))

        boxes: list[Box] = []
        for _ in range(target):
            w = round(rng.uniform(0.04, 0.15), 4)
            h = round(rng.uniform(0.08, 0.28), 4)
            x1 = round(rng.uniform(0.0, max(0.0, 1.0 - w)), 4)
            y1 = round(rng.uniform(0.0, max(0.0, 1.0 - h)), 4)
            x2 = round(min(1.0, x1 + w), 4)
            y2 = round(min(1.0, y1 + h), 4)
            box_conf = round(rng.uniform(min_conf, 0.99), 4)
            boxes.append((x1, y1, x2, y2, box_conf))
        return boxes
