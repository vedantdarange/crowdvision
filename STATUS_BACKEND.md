# Backend status — updated 2026-11-27 20:04 IST
## Phase: B5a (done — audit fixes + stream-restart fix + /health contract alignment complete)
## Done since last update
- Implemented Phase B5a (M4 part 1 — Spawned detection worker & `frame:submit` pipeline with `FakeDetector`) on branch `be/b5a-detection-worker` and fixed all confirmed audit findings, the same-socket stream restart bug, and the `/api/v1/health` contract shape mismatch:
  - **Protocol, Detector Factory, Tracker Hook & In-Memory JPEG Validator**:
    - `app/detection/protocol.py`: added `SetFakeCount` control message alongside `DetectRequest`, `DetectResult`, `Ping`, `Pong`, `ResetSource`, `Shutdown`. Added required `request_id: int` (no default) to `DetectRequest` and `DetectResult`, and `ping_id: int = 0` to `Ping` and `Pong` (`0` reserved for initial readiness `Pong`).
    - `app/detection/detector.py`: added `build_detector(backend)` for `DETECTOR_BACKEND=fake|ultralytics` (`fake` -> `FakeDetector` with optional `delay_ms` for flood testing; `ultralytics` raises `"Ultralytics detector backend is not installed yet (implemented in B5b)."`). No `torch` / `ultralytics` / `cv2` imports in B5a.
    - `app/detection/tracker.py`: added `TrackerHook` Protocol and `PassThroughTracker` stub (`USE_TRACKER=false` default) enforcing explicit `reset=True` and 30 s inactivity reset per source without ever changing occupancy counts.
    - `app/detection/jpeg.py`: pure-Python in-RAM JPEG header & bounds validator (`<= 300 KB`, `width <= 1280`, SOF dimension validation) — zero temp files and zero vision dependencies.
  - **Spawned Worker Process & DetectionManager**:
    - `app/detection/worker.py`: Windows `spawn`-safe top-level `run_worker()` loop handling `DetectRequest`, `Ping`->`Pong` (echoing `ping_id` and emitting initial `Pong(ping_id=0)`), `ResetSource`, `SetFakeCount`, `Shutdown`; echoes `request_id` in `DetectResult`; maintains per-source state (`last_seen`, optional tracker); sets occupancy `count = len(boxes)`. Never logs or writes JPEG bytes.
    - `app/detection/manager.py`: spawns worker with `multiprocessing.get_context("spawn")`, bounded `request_queue(maxsize=16)`, `result_queue`, `socketio.start_background_task` pump & supervisor threads running inside `app.app_context()`.
    - Per-source leases (`SOURCE_IN_USE`, released on disconnect or after `stale_after_s`), non-blocking `put_nowait` (`DETECTOR_BUSY`), monotonic `_next_request_id >= 1` (never reset) keying `_inflight[request_id]` and `_once_waiters[request_id]` with 60 s TTL cleanup, synchronized lease/inflight validation in `_handle_worker_item` (discarding expired/disconnected/superseded/consumed results before emit or `ingest_count()`), automatic superseding/purging of prior `_inflight` entries for `source_id` on `effective_reset` in `submit_frame()` and in `reset_source()`, per-probe `_ping_waiters[ping_id]` for `check_health()`, `reset=True` and 30 s inactivity buffer clearing, `detect_once(jpeg, timeout=5)` synchronous helper (`source_id=-1`, no tracker, serialized settings reads), and supervisor auto-restart (up to 3 times with backoff `(0.1, 0.2, 0.4)`, then `"unavailable"`).
    - Guarded startup in `app/__init__.py` (`not TESTING`, reloader `WERKZEUG_RUN_MAIN == "true"` or non-debug) + `atexit` clean shutdown.
  - **Realtime Handler, Connect Lease Release & Live `/health`**:
    - `app/realtime/events.py`: `@socketio.on("frame:submit")` checks `check_session_freshness` first (`auth:expired` + disconnect if expired/disabled/demoted), enforces `police`/`admin` role (`FORBIDDEN`), active source/zone (`UNKNOWN_SOURCE`), mandatory positive-int `width` & `height` (`BAD_IMAGE`, rejecting missing/bool/non-positive values), JPEG size/width/dimension consistency (`BAD_IMAGE`), and delegates to `DetectionManager.submit_frame`.
    - `app/realtime/connect.py`: shared `_is_sid_stale` / `_expire_sid` helpers used by both 1 Hz tick and `frame:submit`; releases source leases on socket disconnect or expiry.
    - `app/realtime/emitter.py`: added `emit_frame_result(sid, payload)` delivering `frame:result` strictly to the sender `sid`, carrying source `count`/`boxes` and zone-level `smoothed_count`/`density`/`level`.
    - `app/api/v1/health.py`: queries `DetectionManager.check_health()` using correlated `Ping`/`Pong` for `detector` (`loading`|`ready`|`unavailable`) and `worker_alive`, and returns the contract §6.2 / `contract/examples/health.json` top-level JSON `{status, db, detector, worker_alive, version}` (removed the incorrect `{"data": ...}` wrapper).
  - **Tests**:
    - Updated `tests/integration/test_health.py` and `tests/integration/test_detection_pipeline.py` to expect the top-level `/api/v1/health` JSON shape per contract §6.2 & `contract/examples/health.json`.
    - Extended `tests/unit/test_detection.py` and `tests/integration/test_detection_pipeline.py` with regressions for delayed-result routing after disconnect, same-socket stream restart (`reset=True, seq=1` superseding pending pre-restart frames without smoother contamination or alerts), concurrent health probe `Pong` isolation, mandatory `width`/`height` validation, overlapping `detect_once` (with and without timeout), worker kill with pending requests + `/health` recovery, 30 s inactivity reset in both worker tracker and manager smoother, and `TESTING=False` startup/clean shutdown.
    - Focused B5a + Health suite (`python -m pytest tests/unit/test_detection.py tests/integration/test_detection_pipeline.py tests/integration/test_health.py -v --tb=short`): **`43 passed in 65.81s`**.
    - Full backend suite (`python -m pytest tests/ -v --tb=short`): **`228 passed, 1 skipped in 83.05s`** (skipped test is `test_journal_mode_wal` on `:memory:` SQLite, covered by `test_journal_mode_wal_on_file_db`).

## In progress
- None (Phase B5a complete and verified on `be/b5a-detection-worker`; ready to commit and begin B5b. Changes left uncommitted).

## Blocked / questions for Person A
- None.

## Requests for AI-B (frontend)
- `frame:submit` -> `frame:result` pipeline is wired end-to-end on `be/b5a-detection-worker` with `FakeDetector` (leases, `SOURCE_IN_USE`, `DETECTOR_BUSY`, `BAD_IMAGE` including mandatory positive-int `width`/`height`, `UNKNOWN_SOURCE`, `FORBIDDEN`, `/health` correlated `Ping`/`Pong`, top-level `/api/v1/health` JSON matching `contract/examples/health.json`). Real YOLOv8n (`UltralyticsDetector`) arrives in B5b.

## Untested / known issues
- Child-process zero disk writes/JPEG logging: runtime `open`/`tempfile` monkeypatches verify the main Flask process only; child-process `worker.py` / `detector.py` zero-disk-write behavior is verified by code inspection.
- External Socket.IO WebSocket browser test across Werkzeug debug reloader (`WERKZEUG_RUN_MAIN` dual-process guard) and live webcam / `UltralyticsDetector` (real YOLO model) — deferred to B5b (`DETECTOR_BACKEND=ultralytics` currently raises `"not installed yet"`).
- Real DB-failure `/api/v1/health` degraded path (`db="error"`, `status="degraded"`) is verified by inspection only in B5a; tests cover `db="ok"` + live worker transitions (`ready` / `unavailable` / `loading`).
- Carried over: retention cleanup of citizen reports (`B7`), `flask set-password` failure paths, `413 PAYLOAD_TOO_LARGE`, and `test_journal_mode_wal` on `:memory:` SQLite (covered by `test_journal_mode_wal_on_file_db`).

## Next 3 steps
1. Review and commit `be/b5a-detection-worker`.
2. Begin Phase B5b (M4 part 2): `UltralyticsDetector` (`yolov8n.pt` / `best.pt`), OpenCV decode, warm-up, optional `ByteTrackTracker`, `eval/eval_latency.py`, and real webcam test.
3. Begin Phase B6 (M5): `WebPushNotifier` (`pywebpush` + `py-vapid`) and `/push/*` endpoints.

## Numbers (latency, MAE, coverage) once available
- Pure `app/engine/` unit coverage: **97%** (measured in B4a). Real YOLO latency/MAE pending B5b/B9.
