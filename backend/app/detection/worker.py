"""app/detection/worker.py — Spawned detection worker process loop (plan §8.2).

Designed for Windows `multiprocessing.get_context("spawn")` semantics:
  - top-level importable entry point with only picklable parameters
  - no Flask, SQLAlchemy, or Socket.IO imports
  - never writes JPEG bytes to disk or logs them
"""
from __future__ import annotations

import logging
import queue
import time
from typing import Any

from app.detection.detector import Detector, FakeDetector, build_detector
from app.detection.protocol import (
    DetectRequest,
    DetectResult,
    Ping,
    Pong,
    ResetSource,
    SetFakeCount,
    Shutdown,
)
from app.detection.tracker import INACTIVITY_RESET_S, PassThroughTracker, TrackerHook

logger = logging.getLogger(__name__)


def run_worker(
    request_queue: Any,
    result_queue: Any,
    *,
    backend: str = "fake",
    seed: int = 42,
    default_count: int = 0,
    counts: dict[int, int] | None = None,
    delay_ms: float = 0.0,
    use_tracker: bool = False,
) -> None:
    """Main worker loop running inside a spawned child process."""
    try:
        detector: Detector = build_detector(
            backend,
            seed=seed,
            default_count=default_count,
            counts=counts,
            delay_ms=delay_ms,
        )
    except Exception as exc:
        logger.error("Detection worker failed to initialize backend=%s: %s", backend, type(exc).__name__)
        return

    tracker: TrackerHook | None = PassThroughTracker() if use_tracker else None
    source_last_seen: dict[int, float] = {}

    # Signal warm-up completion so /health transitions loading -> ready.
    # ping_id=0 is the reserved "initial readiness" sentinel (no caller waiter).
    try:
        result_queue.put(Pong(ping_id=0))
    except Exception:
        return

    while True:
        try:
            msg = request_queue.get()
        except (EOFError, BrokenPipeError, OSError, KeyboardInterrupt):
            break
        except queue.Empty:
            continue

        if isinstance(msg, Shutdown):
            break

        if isinstance(msg, Ping):
            try:
                result_queue.put(Pong(ping_id=msg.ping_id))
            except Exception:
                break
            continue

        if isinstance(msg, ResetSource):
            source_last_seen.pop(msg.source_id, None)
            if tracker is not None:
                tracker.reset(msg.source_id)
            continue

        if isinstance(msg, SetFakeCount):
            if isinstance(detector, FakeDetector):
                detector.set_count(msg.source_id, msg.count)
            continue

        if isinstance(msg, DetectRequest):
            t0 = time.perf_counter()
            try:
                now_s = float(msg.received_at) if msg.received_at > 0 else time.monotonic()
                if msg.source_id >= 0:
                    last_seen = source_last_seen.get(msg.source_id)
                    inactivity_expired = (
                        last_seen is not None and (now_s - last_seen) >= INACTIVITY_RESET_S
                    )
                    if tracker is not None and (msg.reset or inactivity_expired):
                        tracker.reset(msg.source_id)
                    source_last_seen[msg.source_id] = now_s

                boxes = detector.detect(msg.jpeg, msg.source_id, msg.conf, msg.imgsz)
                raw_count = len(boxes)

                # Optional analytics tracker only; NEVER alters occupancy count.
                if tracker is not None and msg.source_id >= 0:
                    tracker.update(msg.source_id, boxes, now_s, reset=False)

                infer_ms = round((time.perf_counter() - t0) * 1000.0, 2)
                res = DetectResult(
                    source_id=msg.source_id,
                    seq=msg.seq,
                    ok=True,
                    error=None,
                    boxes=boxes,
                    count=raw_count,
                    infer_ms=infer_ms,
                    request_id=msg.request_id,
                )
            except Exception as exc:
                infer_ms = round((time.perf_counter() - t0) * 1000.0, 2)
                logger.warning(
                    "Worker inference error for source_id=%s seq=%s: %s",
                    msg.source_id,
                    msg.seq,
                    type(exc).__name__,
                )
                res = DetectResult(
                    source_id=msg.source_id,
                    seq=msg.seq,
                    ok=False,
                    error="DETECTOR_UNAVAILABLE",
                    boxes=[],
                    count=0,
                    infer_ms=infer_ms,
                    request_id=msg.request_id,
                )

            try:
                result_queue.put(res)
            except (EOFError, BrokenPipeError, OSError):
                break


if __name__ == "__main__":
    # Spawn guard for Windows multiprocessing; worker is always started via run_worker().
    pass
