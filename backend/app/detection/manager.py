"""app/detection/manager.py — DetectionManager supervising spawned worker & ZoneEngine pipeline."""
from __future__ import annotations

import logging
import multiprocessing
import queue
import threading
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.core.clock import Clock, SystemClock
from app.core.errors import DetectorUnavailable, NotFound
from app.core.time import to_iso_z
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
from app.detection.tracker import INACTIVITY_RESET_S
from app.detection.worker import run_worker
from app.engine.zone_engine import ZoneEngine
from app.extensions import db, socketio
from app.realtime.emitter import RealtimeEmitter
from app.realtime.tasks import SourceStatusTracker
from app.repositories.source_repo import SourceRepository
from app.repositories.zone_repo import ZoneRepository
from app.services.alert_service import AlertService
from app.services.engine_sync import format_zone_live_state, reload_engine_from_db
from app.services.settings_service import SettingsService

if TYPE_CHECKING:
    from flask import Flask

logger = logging.getLogger(__name__)

CITIZEN_REPORT_SOURCE_ID = -1
INFLIGHT_TTL_S = 60.0
REQUEST_QUEUE_MAXSIZE = 16


class DetectionManager:
    """Coordinates spawned detection worker, queues, pump, supervisor, and ZoneEngine."""

    def __init__(
        self,
        *,
        detector: Detector | None = None,
        backend: str = "fake",
        use_tracker: bool = False,
        zone_engine: ZoneEngine,
        engine_lock: threading.Lock,
        alert_service: AlertService,
        emitter: RealtimeEmitter,
        zone_repo: ZoneRepository,
        source_repo: SourceRepository,
        settings_service: SettingsService,
        source_status_tracker: SourceStatusTracker,
        clock: Clock | None = None,
        queue_maxsize: int = REQUEST_QUEUE_MAXSIZE,
        max_restarts: int = 3,
        restart_backoffs: tuple[float, ...] = (0.1, 0.2, 0.4),
        worker_seed: int = 42,
        worker_default_count: int = 0,
        worker_delay_ms: float = 0.0,
        model_path: str | None = None,
    ) -> None:
        self._backend = (backend or "fake").strip().lower()
        self._model_path = model_path
        self.detector: Detector | None
        if detector is not None:
            self.detector = detector
        elif self._backend == "fake":
            self.detector = FakeDetector(
                seed=int(worker_seed),
                default_count=max(0, int(worker_default_count)),
            )
        elif self._backend == "ultralytics":
            # Keep main process free of torch/ultralytics; worker loads & warms up.
            self.detector = None
        else:
            raise ValueError(f"Unsupported DETECTOR_BACKEND: {backend!r}")
        self._use_tracker = bool(use_tracker)
        self.engine = zone_engine
        self._engine_lock = engine_lock
        self._alert_service = alert_service
        self.emitter = emitter
        self._zone_repo = zone_repo
        self._source_repo = source_repo
        self._settings = settings_service
        self._source_status_tracker = source_status_tracker
        self._clock: Clock = clock or SystemClock()

        self._queue_maxsize = max(1, int(queue_maxsize))
        self._max_restarts = max(0, int(max_restarts))
        self._restart_backoffs = restart_backoffs or (0.1, 0.2, 0.4)
        self._worker_seed = int(worker_seed)
        self._worker_default_count = max(0, int(worker_default_count))
        self._worker_delay_ms = max(0.0, float(worker_delay_ms))

        # Locks
        self._pipeline_lock = threading.Lock()
        self._db_read_lock = threading.Lock()

        # Worker / threads state
        self._ctx = multiprocessing.get_context("spawn")
        self._request_queue: Any = None
        self._result_queue: Any = None
        self._process: Any = None
        self._flask_app: "Flask | None" = None
        self._started = False
        self._manual_stop = False
        self._stop_event = threading.Event()
        self._pump_thread: threading.Thread | None = None
        self._supervisor_thread: threading.Thread | None = None

        # Health & supervision state
        self._detector_status: str = "unavailable"
        self._restart_count: int = 0
        self._last_pong_at: float | None = None
        self._ready_since: float | None = None

        # Per-probe Ping/Pong correlation — each check_health() call gets a unique ping_id
        # so a late Pong from probe N cannot satisfy probe N+1.
        self._next_ping_id: int = 1  # starts at 1; 0 is reserved for initial readiness Pong
        self._ping_waiters: dict[int, threading.Event] = {}
        # Kept for wait_until_ready() which does not send a Ping
        self._ready_event = threading.Event()

        # Streaming pipeline state (all keyed cleanly in memory)
        # source_id -> (sid, last_frame_monotonic)
        self._leases: dict[int, tuple[str, float]] = {}
        # request_id -> (sid, source_id, seq, effective_reset, sent_at_monotonic)
        # Keyed on the unique request_id assigned at submission, NOT on (sid, source_id, seq).
        # This prevents a delayed result from routing to a new socket that reused the same seq.
        self._inflight: dict[int, tuple[str, int, int, bool, float]] = {}
        self._source_last_submitted_mono: dict[int, float] = {}
        self._pending_reset: dict[int, bool] = {}

        # Monotonic request ID counter — incremented before each DetectRequest is built.
        # Starts at 1 and is never reset within a manager's lifetime so IDs remain unique
        # across reconnects and worker restarts.
        self._next_request_id: int = 1

        # Synchronous single-frame citizen report helper state (keyed on unique request_id)
        self._once_seq = 0
        self._once_waiters: dict[int, tuple[threading.Event, list[DetectResult]]] = {}

        # Scripted counts mirrored to spawned FakeDetector
        self._fake_counts: dict[int, int] = {}

    # ------------------------------------------------------------------
    # Properties / test inspection helpers
    # ------------------------------------------------------------------
    @property
    def worker_pid(self) -> int | None:
        proc = self._process
        return proc.pid if proc is not None else None

    @property
    def restart_count(self) -> int:
        return self._restart_count

    @property
    def detector_status(self) -> str:
        return self._detector_status

    def get_lease_holder(self, source_id: int) -> str | None:
        with self._pipeline_lock:
            entry = self._leases.get(source_id)
            return entry[0] if entry is not None else None

    # ------------------------------------------------------------------
    # Worker lifecycle
    # ------------------------------------------------------------------
    def _spawn_worker_process(self) -> None:
        worker_fps, worker_conf, worker_imgsz = 3.0, 0.35, 640
        if self._flask_app is not None:
            try:
                with self._flask_app.app_context():
                    with self._db_read_lock:
                        cfg = self._settings.get_settings()
                    worker_fps = float(cfg.get("target_fps", 3.0))
                    worker_conf = float(cfg.get("detect_conf", 0.35))
                    worker_imgsz = int(cfg.get("frame_width", 640))
            except Exception:
                pass

        req_q = self._ctx.Queue(maxsize=self._queue_maxsize)
        res_q = self._ctx.Queue()
        proc = self._ctx.Process(
            target=run_worker,
            kwargs={
                "request_queue": req_q,
                "result_queue": res_q,
                "backend": self._backend,
                "seed": self._worker_seed,
                "default_count": self._worker_default_count,
                "counts": dict(self._fake_counts),
                "delay_ms": self._worker_delay_ms,
                "use_tracker": self._use_tracker,
                "model_path": self._model_path,
                "target_fps": worker_fps,
                "detect_conf": worker_conf,
                "warmup_imgsz": worker_imgsz,
            },
            daemon=True,
        )
        proc.start()
        self._request_queue = req_q
        self._result_queue = res_q
        self._process = proc
        self._detector_status = "loading"
        self._ready_since = None
        self._ready_event.clear()

    def _close_queues(self, req_q: Any, res_q: Any) -> None:
        for q in (req_q, res_q):
            if q is None:
                continue
            try:
                q.close()
                q.cancel_join_thread()
            except Exception:
                pass

    def start(self, flask_app: "Flask") -> None:
        """Start the spawned detection worker, pump task, and supervisor task."""
        with self._pipeline_lock:
            if self._started:
                return
            # Validate backend / model path synchronously before spawning (no torch import)
            if self._backend == "ultralytics":
                from app.detection.model_loader import resolve_model_path

                resolve_model_path(self._model_path)
            elif self._backend != "fake" and not isinstance(self.detector, FakeDetector):
                build_detector(self._backend, model_path=self._model_path)
            self._flask_app = flask_app
            self._manual_stop = False
            self._restart_count = 0
            self._stop_event.clear()
            self._spawn_worker_process()
            self._started = True
            self._pump_thread = socketio.start_background_task(
                self._pump_loop, flask_app
            )
            self._supervisor_thread = socketio.start_background_task(
                self._supervisor_loop, flask_app
            )
            logger.info("DetectionManager started spawned worker pid=%s", self.worker_pid)

    def stop(self, timeout: float = 2.0) -> None:
        """Cleanly shut down worker process, pump task, and supervisor task."""
        with self._pipeline_lock:
            if not self._started:
                return
            self._manual_stop = True
            self._started = False
            self._detector_status = "unavailable"
            self._stop_event.set()
            req_q = self._request_queue
            res_q = self._result_queue
            proc = self._process
            pump_t = self._pump_thread
            sup_t = self._supervisor_thread
            self._fail_pending_waiters_locked()

        # Ask worker to exit cleanly; drain if queue is momentarily full.
        if req_q is not None and proc is not None and proc.is_alive():
            try:
                req_q.put_nowait(Shutdown())
            except queue.Full:
                for _ in range(self._queue_maxsize):
                    try:
                        req_q.get_nowait()
                    except queue.Empty:
                        break
                try:
                    req_q.put_nowait(Shutdown())
                except Exception:
                    pass
            except Exception:
                pass

        if proc is not None:
            proc.join(timeout=timeout)
            if proc.is_alive():
                logger.warning("Terminating unresponsive detection worker pid=%s", proc.pid)
                proc.terminate()
                proc.join(timeout=timeout)

        for t in (pump_t, sup_t):
            if t is not None and t.is_alive():
                t.join(timeout=timeout)

        self._close_queues(req_q, res_q)
        with self._pipeline_lock:
            self._request_queue = None
            self._result_queue = None
            self._process = None
            self._pump_thread = None
            self._supervisor_thread = None
            self._leases.clear()
            self._inflight.clear()
            self._source_last_submitted_mono.clear()
            self._pending_reset.clear()
        logger.info("DetectionManager stopped cleanly")

    def reset_runtime_state(self) -> None:
        """Clear in-memory leases, inflight maps, and fake counts between tests."""
        with self._pipeline_lock:
            self._leases.clear()
            self._inflight.clear()
            self._source_last_submitted_mono.clear()
            self._pending_reset.clear()
            self._fake_counts.clear()
        if isinstance(self.detector, FakeDetector):
            self.detector._counts.clear()

    def prune_runtime_state(
        self,
        active_source_ids: set[int] | None = None,
        *,
        stale_after_s: float = 30.0,
    ) -> dict[str, int]:
        """Sweep expired inflight/lease/inactivity state and deleted sources."""
        now_mono = time.monotonic()
        lease_ttl = max(float(stale_after_s), INFLIGHT_TTL_S)
        inactivity_ttl = max(INACTIVITY_RESET_S * 2.0, 60.0)
        removed_sources: set[int] = set()

        with self._pipeline_lock:
            before_inf = len(self._inflight)
            self._cleanup_inflight_locked(now_mono)
            inflight_pruned = before_inf - len(self._inflight)

            expired_leases = [
                sid
                for sid, (_, last_s) in self._leases.items()
                if (now_mono - last_s) > lease_ttl
            ]
            for sid in expired_leases:
                self._leases.pop(sid, None)

            expired_last_sub = [
                sid
                for sid, last_s in self._source_last_submitted_mono.items()
                if (now_mono - last_s) >= inactivity_ttl
            ]
            for sid in expired_last_sub:
                self._source_last_submitted_mono.pop(sid, None)

            if active_source_ids is not None:
                inactive_leases = [
                    sid for sid in self._leases if sid not in active_source_ids
                ]
                for sid in inactive_leases:
                    self._leases.pop(sid, None)
                    removed_sources.add(sid)

                inactive_sub = [
                    sid
                    for sid in self._source_last_submitted_mono
                    if sid not in active_source_ids
                ]
                for sid in inactive_sub:
                    self._source_last_submitted_mono.pop(sid, None)
                    removed_sources.add(sid)

                inactive_resets = [
                    sid for sid in self._pending_reset if sid not in active_source_ids
                ]
                for sid in inactive_resets:
                    self._pending_reset.pop(sid, None)
                    removed_sources.add(sid)

                inactive_inf = [
                    rid
                    for rid, entry in self._inflight.items()
                    if entry[1] != CITIZEN_REPORT_SOURCE_ID
                    and entry[1] not in active_source_ids
                ]
                for rid in inactive_inf:
                    entry = self._inflight.pop(rid, None)
                    if entry is not None:
                        removed_sources.add(entry[1])
                inflight_pruned += len(inactive_inf)

            req_q = self._request_queue

        if req_q is not None:
            for sid in removed_sources:
                try:
                    req_q.put_nowait(ResetSource(source_id=sid))
                except Exception:
                    break

        return {
            "inflight_pruned": inflight_pruned,
            "leases_pruned": len(expired_leases),
            "inactive_sources_pruned": len(removed_sources),
        }

    def runtime_stats(self) -> dict[str, Any]:
        """Return queue depths and bounded-map sizes for soak/health monitoring."""
        with self._pipeline_lock:
            req_q = self._request_queue
            res_q = self._result_queue
            stats: dict[str, Any] = {
                "inflight": len(self._inflight),
                "leases": len(self._leases),
                "once_waiters": len(self._once_waiters),
                "ping_waiters": len(self._ping_waiters),
                "pending_reset": len(self._pending_reset),
                "last_submitted_sources": len(self._source_last_submitted_mono),
                "fake_counts": len(self._fake_counts),
                "worker_alive": bool(self._process is not None and self._process.is_alive()),
                "detector_status": self._detector_status,
            }

        for name, q in (("request_queue_depth", req_q), ("result_queue_depth", res_q)):
            if q is None:
                stats[name] = 0
                continue
            try:
                stats[name] = int(q.qsize())
            except (NotImplementedError, AttributeError, ValueError, OSError):
                stats[name] = -1
        return stats

    def _fail_pending_waiters_locked(self) -> None:
        """Unblock any pending detect_once callers and health-probe waiters when worker stops/crashes."""
        for req_id, (evt, holder) in list(self._once_waiters.items()):
            holder.append(
                DetectResult(
                    source_id=CITIZEN_REPORT_SOURCE_ID,
                    seq=0,
                    ok=False,
                    error="DETECTOR_UNAVAILABLE",
                    boxes=[],
                    count=0,
                    infer_ms=0.0,
                    request_id=req_id,
                )
            )
            evt.set()
        self._once_waiters.clear()
        # Unblock any concurrent check_health() callers
        for evt in self._ping_waiters.values():
            evt.set()
        self._ping_waiters.clear()

    # ------------------------------------------------------------------
    # Health & Supervision
    # ------------------------------------------------------------------
    def wait_until_ready(self, timeout: float = 3.0) -> bool:
        """Wait until the spawned worker has answered Pong (primarily for startup/tests)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._detector_status == "ready" and self._process is not None and self._process.is_alive():
                return True
            remaining = max(0.01, min(0.05, deadline - time.monotonic()))
            self._ready_event.wait(timeout=remaining)
        return self._detector_status == "ready"

    def check_health(self, timeout: float = 0.5) -> tuple[str, bool]:
        """Verify worker liveness via Ping/Pong and return (detector_status, worker_alive).

        Each call gets its own unique ping_id so a late Pong from a prior probe cannot
        satisfy a later one (Bug 2 fix).
        """
        with self._pipeline_lock:
            started = self._started
            proc = self._process
            req_q = self._request_queue
            status = self._detector_status

        if not started or proc is None or req_q is None or not proc.is_alive():
            return "unavailable", False

        if status == "loading":
            # Worker hasn't sent its initial Pong yet — wait for _ready_event
            if self._ready_event.wait(timeout=min(timeout, 0.3)) and proc.is_alive():
                return self._detector_status, True
            return ("loading" if proc.is_alive() else "unavailable"), False

        # Allocate a unique ping_id for this probe
        with self._pipeline_lock:
            ping_id = self._next_ping_id
            self._next_ping_id += 1
            probe_evt = threading.Event()
            self._ping_waiters[ping_id] = probe_evt

        try:
            req_q.put(Ping(ping_id=ping_id), timeout=0.1)
        except queue.Full:
            with self._pipeline_lock:
                self._ping_waiters.pop(ping_id, None)
            return (status if proc.is_alive() else "unavailable"), False
        except Exception:
            with self._pipeline_lock:
                self._ping_waiters.pop(ping_id, None)
            return "unavailable", False

        got_pong = probe_evt.wait(timeout=timeout)
        with self._pipeline_lock:
            self._ping_waiters.pop(ping_id, None)
        alive = bool(
            got_pong
            and self._started
            and self._detector_status != "unavailable"
            and proc.is_alive()
        )
        if alive:
            return self._detector_status, True
        return (self._detector_status if proc.is_alive() else "unavailable"), False

    def _supervisor_loop(self, flask_app: "Flask") -> None:
        """Monitor worker process and restart up to `max_restarts` times with backoff."""
        while not self._stop_event.is_set():
            with flask_app.app_context():
                try:
                    self._supervisor_step(flask_app)
                except Exception:
                    logger.exception("DetectionManager supervisor error")
            self._stop_event.wait(0.05)

    def _supervisor_step(self, flask_app: "Flask") -> None:
        with self._pipeline_lock:
            if not self._started or self._manual_stop:
                return
            proc = self._process
            if proc is not None and proc.is_alive():
                # Recover restart budget after prolonged healthy operation
                if (
                    self._detector_status == "ready"
                    and self._ready_since is not None
                    and (time.monotonic() - self._ready_since) >= 60.0
                ):
                    self._restart_count = 0
                return

            # Worker died unexpectedly
            self._detector_status = "unavailable"
            self._fail_pending_waiters_locked()
            # _inflight values are (sid, source_id, seq, reset, sent_at); extract for notification
            inflight_drop = [(v[0], v[1], v[2]) for v in self._inflight.values()]
            self._inflight.clear()
            old_req_q = self._request_queue
            old_res_q = self._result_queue

            if self._restart_count >= self._max_restarts:
                self._process = None
                self._request_queue = None
                self._result_queue = None
                self._close_queues(old_req_q, old_res_q)
                # Emit DETECTOR_UNAVAILABLE for dropped frames outside lock
                attempt_restart = False
            else:
                backoff_idx = min(self._restart_count, len(self._restart_backoffs) - 1)
                backoff_s = float(self._restart_backoffs[backoff_idx])
                self._restart_count += 1
                restart_num = self._restart_count
                attempt_restart = True

        # Notify any inflight submitters outside pipeline lock
        for sid, source_id, seq in inflight_drop:
            self.emitter.emit_frame_result(
                sid,
                {
                    "source_id": source_id,
                    "seq": seq,
                    "ok": False,
                    "error": "DETECTOR_UNAVAILABLE",
                    "count": 0,
                    "boxes": [],
                    "infer_ms": 0.0,
                    "smoothed_count": None,
                    "density": None,
                    "level": None,
                },
            )

        if not attempt_restart:
            return

        logger.warning(
            "Detection worker died; restarting (%s/%s) after %.2fs backoff",
            restart_num,
            self._max_restarts,
            backoff_s,
        )
        if self._stop_event.wait(backoff_s):
            return

        self._close_queues(old_req_q, old_res_q)
        with self._pipeline_lock:
            if not self._started or self._manual_stop:
                return
            self._spawn_worker_process()
            logger.info("Detection worker restarted pid=%s", self.worker_pid)

    # ------------------------------------------------------------------
    # Pump loop (result queue -> sender frame:result + ZoneEngine ingest)
    # ------------------------------------------------------------------
    def _pump_loop(self, flask_app: "Flask") -> None:
        while not self._stop_event.is_set():
            with self._pipeline_lock:
                res_q = self._result_queue
            if res_q is None:
                self._stop_event.wait(0.05)
                continue
            try:
                item = res_q.get(timeout=0.1)
            except queue.Empty:
                continue
            except (EOFError, OSError, ValueError):
                self._stop_event.wait(0.05)
                continue

            with flask_app.app_context():
                try:
                    self._handle_worker_item(item)
                except Exception:
                    logger.exception("DetectionManager pump failed handling result")
                    try:
                        db.session.rollback()
                    except Exception:
                        pass

    def _cleanup_inflight_locked(self, now_mono: float) -> None:
        # _inflight values: (sid, source_id, seq, effective_reset, sent_at)
        expired = [
            req_id
            for req_id, entry in self._inflight.items()
            if (now_mono - entry[4]) >= INFLIGHT_TTL_S
        ]
        for req_id in expired:
            self._inflight.pop(req_id, None)

    def _handle_worker_item(self, item: Any) -> None:
        if isinstance(item, Pong):
            now_mono = time.monotonic()
            with self._pipeline_lock:
                self._last_pong_at = now_mono
                if self._detector_status != "ready":
                    self._ready_since = now_mono
                self._detector_status = "ready"
                if item.ping_id == 0:
                    # Initial warm-up Pong from worker startup — no probe waiter
                    self._ready_event.set()
                else:
                    # Probe Pong — wake exactly the matching check_health() waiter
                    waiter_evt = self._ping_waiters.get(item.ping_id)
                    if waiter_evt is not None:
                        waiter_evt.set()
            return

        if not isinstance(item, DetectResult):
            return

        if item.source_id == CITIZEN_REPORT_SOURCE_ID:
            with self._pipeline_lock:
                waiter = self._once_waiters.pop(item.request_id, None)
            if waiter is not None:
                evt, holder = waiter
                holder.append(item)
                evt.set()
            return

        now_mono = time.monotonic()
        with self._pipeline_lock:
            self._cleanup_inflight_locked(now_mono)
            # Look up by unique request_id — prevents stale results from matching
            # a new sender that happened to reuse the same (source_id, seq).
            entry = self._inflight.pop(item.request_id, None)
            if entry is None:
                # Expired, disconnected, superseded, or already-consumed result: discard before
                # any emit or ZoneEngine ingestion.
                return
            sender_sid, req_source_id, _seq, effective_reset, _sent = entry
            lease = self._leases.get(req_source_id)
            if lease is None or lease[0] != sender_sid:
                # Lease was released or taken over while request was in-flight: discard.
                return

        if not item.ok:
            if sender_sid is not None:
                self.emitter.emit_frame_result(
                    sender_sid,
                    {
                        "source_id": item.source_id,
                        "seq": item.seq,
                        "ok": False,
                        "error": item.error or "DETECTOR_UNAVAILABLE",
                        "count": 0,
                        "boxes": [],
                        "infer_ms": float(item.infer_ms),
                        "smoothed_count": None,
                        "density": None,
                        "level": None,
                    },
                )
            return

        try:
            zone_live = self.ingest_count(
                item.source_id,
                item.count,
                now=self._clock.utcnow(),
                reset=effective_reset,
            )
        except NotFound:
            if sender_sid is not None:
                self.emitter.emit_frame_result(
                    sender_sid,
                    {
                        "source_id": item.source_id,
                        "seq": item.seq,
                        "ok": False,
                        "error": "UNKNOWN_SOURCE",
                        "count": 0,
                        "boxes": [],
                        "infer_ms": float(item.infer_ms),
                        "smoothed_count": None,
                        "density": None,
                        "level": None,
                    },
                )
            return

        if sender_sid is not None:
            self.emitter.emit_frame_result(
                sender_sid,
                {
                    "source_id": item.source_id,
                    "seq": item.seq,
                    "ok": True,
                    "count": int(item.count),
                    "boxes": [list(b) for b in item.boxes],
                    "infer_ms": float(item.infer_ms),
                    "smoothed_count": zone_live.get("count"),
                    "density": zone_live.get("density"),
                    "level": zone_live.get("level"),
                },
            )

    # ------------------------------------------------------------------
    # Frame submission, leases, reset & citizen detect_once
    # ------------------------------------------------------------------
    def submit_frame(
        self,
        *,
        sid: str,
        source_id: int,
        seq: int,
        jpeg_bytes: bytes,
        width: int,
        height: int,
        reset: bool = False,
    ) -> str | None:
        """Validate lease and enqueue a frame onto the bounded worker queue.

        Never blocks. Returns `None` if queued or an error code string otherwise.
        """
        with self._db_read_lock:
            cfg = self._settings.get_settings()
        stale_after_s = float(cfg.get("stale_after_s", 10.0))
        detect_conf = float(cfg.get("detect_conf", 0.35))
        frame_width = int(cfg.get("frame_width", 640))

        now_mono = time.monotonic()
        with self._pipeline_lock:
            self._cleanup_inflight_locked(now_mono)

            if (
                not self._started
                or self._process is None
                or not self._process.is_alive()
                or self._request_queue is None
                or self._detector_status == "unavailable"
            ):
                return "DETECTOR_UNAVAILABLE"

            lease = self._leases.get(source_id)
            if lease is not None:
                holder_sid, last_lease_s = lease
                if (now_mono - last_lease_s) > stale_after_s:
                    self._leases.pop(source_id, None)
                    # Purge stale inflight entries from the expired lease holder
                    for rid, inf_entry in list(self._inflight.items()):
                        if inf_entry[0] == holder_sid and inf_entry[1] == source_id:
                            self._inflight.pop(rid, None)
                elif holder_sid != sid:
                    return "SOURCE_IN_USE"
            self._leases[source_id] = (sid, now_mono)

            last_sub_s = self._source_last_submitted_mono.get(source_id)
            inactivity_reset = (
                last_sub_s is not None and (now_mono - last_sub_s) >= INACTIVITY_RESET_S
            )
            effective_reset = (
                bool(reset)
                or inactivity_reset
                or self._pending_reset.get(source_id, False)
            )
            if effective_reset:
                # Supersede any prior pending frames for this source so delayed
                # pre-restart results cannot reach the client, contaminate smoothing,
                # or raise alerts on the restarted stream.
                for rid, inf_entry in list(self._inflight.items()):
                    if inf_entry[1] == source_id:
                        self._inflight.pop(rid, None)

            req = DetectRequest(
                source_id=source_id,
                seq=seq,
                jpeg=jpeg_bytes,
                width=width,
                height=height,
                reset=effective_reset,
                conf=detect_conf,
                imgsz=frame_width,
                received_at=self._clock.time(),
                request_id=self._next_request_id,
            )
            self._next_request_id += 1
            try:
                self._request_queue.put_nowait(req)
            except queue.Full:
                if reset:
                    self._pending_reset[source_id] = True
                return "DETECTOR_BUSY"
            except Exception:
                return "DETECTOR_UNAVAILABLE"

            self._pending_reset.pop(source_id, None)
            self._source_last_submitted_mono[source_id] = now_mono
            # Store (sid, source_id, seq, effective_reset, sent_at) keyed on unique request_id
            self._inflight[req.request_id] = (sid, source_id, seq, effective_reset, now_mono)
            return None

    def release_leases_for_sid(self, sid: str) -> list[int]:
        """Release any source streaming leases and inflight records held by *sid*."""
        released: list[int] = []
        with self._pipeline_lock:
            for src_id, (holder, _) in list(self._leases.items()):
                if holder == sid:
                    self._leases.pop(src_id, None)
                    released.append(src_id)
            # Remove inflight entries belonging to this sid
            for req_id, entry in list(self._inflight.items()):
                if entry[0] == sid:
                    self._inflight.pop(req_id, None)
        return released

    def reset_source(self, source_id: int) -> None:
        """Clear source smoothing buffer in ZoneEngine and reset worker tracker."""
        with self._pipeline_lock:
            self._source_last_submitted_mono.pop(source_id, None)
            self._pending_reset.pop(source_id, None)
            for rid, inf_entry in list(self._inflight.items()):
                if inf_entry[1] == source_id:
                    self._inflight.pop(rid, None)
            req_q = self._request_queue

        with self._engine_lock:
            src = self.engine._sources.get(source_id)
            if src is not None:
                src.smoother.clear()

        if req_q is not None:
            try:
                req_q.put_nowait(ResetSource(source_id=source_id))
            except Exception:
                pass

    def set_fake_count(self, source_id: int, count: int) -> None:
        """Configure deterministic FakeDetector count locally and inside the worker."""
        val = max(0, int(count))
        with self._pipeline_lock:
            self._fake_counts[source_id] = val
            req_q = self._request_queue
        if isinstance(self.detector, FakeDetector):
            self.detector.set_count(source_id, val)
        if req_q is not None:
            try:
                req_q.put(SetFakeCount(source_id=source_id, count=val), timeout=0.5)
            except Exception:
                pass

    def detect_once(self, jpeg: bytes, timeout: float = 5.0) -> DetectResult:
        """Synchronous single-frame detection helper for citizen reports (B7).

        Uses dedicated source_id=-1 and never invokes tracking or smoothing.
        Raises DetectorUnavailable if worker is down, queue is full, or timeout hits.
        """
        if not isinstance(jpeg, (bytes, bytearray, memoryview)) or len(jpeg) == 0:
            raise ValueError("jpeg must be non-empty bytes.")
        jpeg_bytes = bytes(jpeg)

        with self._db_read_lock:
            cfg = self._settings.get_settings()
        detect_conf = float(cfg.get("detect_conf", 0.35))
        frame_width = int(cfg.get("frame_width", 640))

        evt = threading.Event()
        holder: list[DetectResult] = []
        with self._pipeline_lock:
            if (
                not self._started
                or self._process is None
                or not self._process.is_alive()
                or self._request_queue is None
                or self._detector_status == "unavailable"
            ):
                raise DetectorUnavailable("Detection worker is unavailable.")

            self._once_seq += 1
            seq = self._once_seq
            req_id = self._next_request_id
            self._next_request_id += 1
            self._once_waiters[req_id] = (evt, holder)

            req = DetectRequest(
                source_id=CITIZEN_REPORT_SOURCE_ID,
                seq=seq,
                jpeg=jpeg_bytes,
                width=0,
                height=0,
                reset=True,
                conf=detect_conf,
                imgsz=frame_width,
                received_at=self._clock.time(),
                request_id=req_id,
            )
            try:
                self._request_queue.put_nowait(req)
            except queue.Full as exc:
                self._once_waiters.pop(req_id, None)
                raise DetectorUnavailable("Detection queue is busy.") from exc
            except Exception as exc:
                self._once_waiters.pop(req_id, None)
                raise DetectorUnavailable("Detection worker is unavailable.") from exc

        finished = evt.wait(timeout=timeout)
        with self._pipeline_lock:
            self._once_waiters.pop(req_id, None)

        if not finished or not holder:
            raise DetectorUnavailable("Detection timed out.")
        res = holder[0]
        if not res.ok:
            if res.error == "BAD_IMAGE":
                from app.core.errors import ValidationAppError

                raise ValidationAppError(
                    "Invalid or unreadable image.",
                    details={"image": ["Could not decode JPEG or PNG image."]},
                )
            raise DetectorUnavailable(res.error or "Detection failed.")
        return res

    # ------------------------------------------------------------------
    # Shared ZoneEngine ingest entry point (fake-feed & worker pump)
    # ------------------------------------------------------------------
    def ingest_count(
        self,
        source_id: int,
        count: int,
        now: datetime | None = None,
        *,
        reset: bool = False,
    ) -> dict[str, Any]:
        """Ingest one count reading for *source_id* through ZoneEngine + AlertService."""
        ts = now or self._clock.utcnow()
        source = self._source_repo.get(source_id)
        if source is None or not source.is_active:
            raise NotFound(f"Active source {source_id} not found.")

        zone = self._zone_repo.get(source.zone_id)
        if zone is None or not zone.is_active:
            raise NotFound(f"Active zone {source.zone_id} not found.")

        with self._engine_lock:
            if (
                source.id not in self.engine._sources
                or zone.id not in self.engine._zones
            ):
                reload_engine_from_db(
                    zone_engine=self.engine,
                    zone_repo=self._zone_repo,
                    source_repo=self._source_repo,
                    settings_service=self._settings,
                )

            actions = self.engine.ingest(source_id, count, ts, reset=reset)
            effects = self._alert_service.persist_actions(
                actions, zone_engine=self.engine
            )
            eng_state = self.engine.get_zone_state(zone.id, ts)
            src_state = self.engine.get_source_state(source.id, ts)

        self._alert_service.dispatch_side_effects(effects)

        if src_state is not None and self._source_status_tracker.check_and_record(
            source.id, src_state["status"]
        ):
            self.emitter.emit_source_status(
                source.id,
                source.zone_id,
                src_state["status"],
                to_iso_z(src_state["last_frame_at"]),
            )

        return format_zone_live_state(eng_state)
