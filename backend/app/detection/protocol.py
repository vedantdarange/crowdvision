"""app/detection/protocol.py — Multiprocessing queue protocol dataclasses (plan §8.2).

Every message is a plain dataclass with primitive/built-in fields so it
pickles cleanly across `multiprocessing.get_context("spawn")` queues in B5.
No torch, OpenCV, or Flask imports here.
"""
from __future__ import annotations

from dataclasses import dataclass

Box = tuple[float, float, float, float, float]  # (x1, y1, x2, y2, conf) normalised 0..1


@dataclass(frozen=True)
class DetectRequest:
    source_id: int
    seq: int
    jpeg: bytes
    width: int
    height: int
    reset: bool
    conf: float
    imgsz: int
    received_at: float


@dataclass(frozen=True)
class DetectResult:
    source_id: int
    seq: int
    ok: bool
    error: str | None
    boxes: list[Box]
    count: int
    infer_ms: float


# ---------------------------------------------------------------------------
# Control messages (worker process lifecycle)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Shutdown:
    pass


@dataclass(frozen=True)
class ResetSource:
    source_id: int


@dataclass(frozen=True)
class Ping:
    pass


@dataclass(frozen=True)
class Pong:
    pass
