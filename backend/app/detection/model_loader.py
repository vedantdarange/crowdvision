"""app/detection/model_loader.py — YOLO model loading & warm-up inside worker (plan §8.2).

Never import this module at top-level Flask startup so the main process stays free
of torch/ultralytics when running in fake mode or before spawn.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import BACKEND_DIR, settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoadedModel:
    """Loaded Ultralytics YOLO model and resolved person class filter."""

    model: Any
    model_path: Path
    names: Any
    person_classes: list[int] | None
    warmup_ms: float


def resolve_model_path(model_path: str | None = None) -> Path:
    """Resolve *model_path* (or `settings.model_path`) against CWD, BACKEND_DIR, or repo root."""
    raw = (model_path or settings.model_path or "").strip()
    if not raw:
        raise FileNotFoundError("MODEL_PATH is empty.")

    candidate = Path(raw)
    if candidate.is_file():
        return candidate.resolve()

    if not candidate.is_absolute():
        for base in (BACKEND_DIR, BACKEND_DIR.parent):
            probe = base / candidate
            if probe.is_file():
                return probe.resolve()

    raise FileNotFoundError(
        f"YOLO model file not found at MODEL_PATH={raw!r} "
        f"(checked CWD, {BACKEND_DIR}, and {BACKEND_DIR.parent})."
    )


def extract_person_classes(names: Any) -> list[int] | None:
    """Identify class ID(s) named 'person' from `model.names`.

    Returns `None` (no class filter) when `names` does not contain a 'person' label,
    matching plan §8.2 fallback guidance.
    """
    pairs: list[tuple[int, str]] = []
    if isinstance(names, dict):
        for k, v in names.items():
            try:
                pairs.append((int(k), str(v)))
            except (TypeError, ValueError):
                continue
    elif isinstance(names, (list, tuple)):
        for idx, v in enumerate(names):
            pairs.append((idx, str(v)))

    person_ids = sorted(
        idx for idx, label in pairs if label.strip().lower() == "person"
    )
    if person_ids:
        return person_ids

    logger.warning(
        "Model class names %r do not explicitly label 'person'; "
        "falling back to unfiltered detections (classes=None).",
        names,
    )
    return None


def load_ultralytics_model(
    model_path: str | None = None,
    *,
    warmup_imgsz: int = 640,
    conf: float = 0.35,
) -> LoadedModel:
    """Load the YOLO model once and run a blank-frame warm-up inference."""
    import time

    # Validate model path before importing heavy torch/ultralytics dependencies.
    resolved = resolve_model_path(model_path)

    import numpy as np
    from ultralytics import YOLO

    t0 = time.perf_counter()
    model = YOLO(str(resolved))
    names = getattr(model, "names", None)
    person_classes = extract_person_classes(names)

    logger.info(
        "Loaded YOLO weights path=%s names=%r person_classes=%r",
        resolved,
        names,
        person_classes,
    )

    size = max(32, int(warmup_imgsz))
    blank = np.zeros((size, size, 3), dtype=np.uint8)
    predict_kwargs: dict[str, Any] = {
        "imgsz": size,
        "conf": float(conf),
        "verbose": False,
    }
    if person_classes is not None:
        predict_kwargs["classes"] = person_classes
    model.predict(blank, **predict_kwargs)

    warmup_ms = round((time.perf_counter() - t0) * 1000.0, 2)
    logger.info("YOLO warm-up complete in %.2f ms", warmup_ms)
    return LoadedModel(
        model=model,
        model_path=resolved,
        names=names,
        person_classes=person_classes,
        warmup_ms=warmup_ms,
    )
