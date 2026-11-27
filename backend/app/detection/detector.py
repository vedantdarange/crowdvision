"""app/detection/detector.py — Detector Protocol, FakeDetector, and UltralyticsDetector (plan §8.2).

No top-level torch / ultralytics / OpenCV imports so tests and fake mode remain
fast and torch-free in the main process.
"""
from __future__ import annotations

import random
import time
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
        delay_ms: float = 0.0,
    ) -> None:
        self._seed = seed
        self._default_count = max(0, int(default_count))
        self._counts: dict[int, int] = dict(counts) if counts else {}
        self._delay_ms = max(0.0, float(delay_ms))
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
        if self._delay_ms > 0:
            time.sleep(self._delay_ms / 1000.0)
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


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


class FrameDecodeError(ValueError):
    """Raised strictly when decoding incoming frame bytes into an image fails."""


class UltralyticsDetector:
    """Real YOLOv8 person detector backed by Ultralytics + OpenCV + supervision."""

    def __init__(
        self,
        *,
        model_path: str | None = None,
        warmup_imgsz: int = 640,
        default_conf: float = 0.35,
        loaded_model: Any = None,
    ) -> None:
        if loaded_model is None:
            from app.detection.model_loader import load_ultralytics_model

            loaded_model = load_ultralytics_model(
                model_path=model_path,
                warmup_imgsz=warmup_imgsz,
                conf=default_conf,
            )
        self._loaded = loaded_model
        self._model = loaded_model.model
        self._person_classes: list[int] | None = loaded_model.person_classes
        self.names = loaded_model.names
        self.warmup_ms: float = float(loaded_model.warmup_ms)
        self.model_path = loaded_model.model_path

    def detect(
        self, frame: Any, source_id: int, conf: float, imgsz: int
    ) -> list[Box]:
        """Decode JPEG in RAM, run YOLO predict, convert via supervision, normalize 0..1."""
        import cv2
        import numpy as np
        import supervision as sv

        if isinstance(frame, (bytes, bytearray, memoryview)):
            raw = bytes(frame)
            if not raw:
                raise FrameDecodeError("Empty JPEG frame.")
            arr = np.frombuffer(raw, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        elif isinstance(frame, np.ndarray):
            img = frame
        else:
            raise FrameDecodeError("Frame must be JPEG bytes or numpy ndarray.")

        if img is None or img.ndim < 2 or img.shape[0] <= 0 or img.shape[1] <= 0:
            raise FrameDecodeError("Failed to decode frame image.")

        frame_h, frame_w = int(img.shape[0]), int(img.shape[1])
        conf_f = float(conf)
        imgsz_i = int(imgsz) if int(imgsz) > 0 else 640

        predict_kwargs: dict[str, Any] = {
            "imgsz": imgsz_i,
            "conf": conf_f,
            "verbose": False,
        }
        if self._person_classes is not None:
            predict_kwargs["classes"] = self._person_classes

        results = self._model.predict(img, **predict_kwargs)
        if not results:
            return []

        detections = sv.Detections.from_ultralytics(results[0])
        if len(detections) == 0:
            return []

        xyxy = detections.xyxy
        confs = detections.confidence
        boxes: list[Box] = []
        for idx in range(len(detections)):
            bx1, by1, bx2, by2 = xyxy[idx]
            score = float(confs[idx]) if confs is not None else 1.0
            if score < conf_f:
                continue
            nx1 = round(_clamp01(float(bx1) / frame_w), 4)
            ny1 = round(_clamp01(float(by1) / frame_h), 4)
            nx2 = round(_clamp01(float(bx2) / frame_w), 4)
            ny2 = round(_clamp01(float(by2) / frame_h), 4)
            if nx2 <= nx1 or ny2 <= ny1:
                continue
            boxes.append((nx1, ny1, nx2, ny2, round(score, 4)))
        return boxes


def build_detector(
    backend: str = "fake",
    *,
    seed: int = 42,
    default_count: int = 0,
    counts: dict[int, int] | None = None,
    delay_ms: float = 0.0,
    model_path: str | None = None,
    warmup_imgsz: int = 640,
) -> Detector:
    """Instantiate the configured detector backend (`fake` or `ultralytics`)."""
    norm = (backend or "fake").strip().lower()
    if norm == "fake":
        return FakeDetector(
            seed=seed,
            default_count=default_count,
            counts=counts,
            delay_ms=delay_ms,
        )
    if norm == "ultralytics":
        return UltralyticsDetector(
            model_path=model_path,
            warmup_imgsz=warmup_imgsz,
        )
    raise ValueError(f"Unsupported DETECTOR_BACKEND: {backend!r}")
