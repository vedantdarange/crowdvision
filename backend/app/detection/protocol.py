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
    request_id: int  # Required unique monotonic ID assigned by DetectionManager; no default


@dataclass(frozen=True)
class DetectResult:
    source_id: int
    seq: int
    ok: bool
    error: str | None
    boxes: list[Box]
    count: int
    infer_ms: float
    request_id: int  # Required ID echoed from DetectRequest; no default


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
    ping_id: int = 0  # 0 = reserved for initial readiness Pong; callers use >0


@dataclass(frozen=True)
class Pong:
    ping_id: int = 0  # Echoed from Ping; 0 means worker warm-up complete (no caller waiter)


@dataclass(frozen=True)
class SetFakeCount:
    source_id: int
    count: int

