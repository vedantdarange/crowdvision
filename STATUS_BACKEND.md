# Backend status — updated 2026-11-27
## Phase: B5b (done — ready for review)
## Done since last update
- Implemented Phase B5b (M4 part 2 — Real `UltralyticsDetector` worker & latency evaluation) on branch `be/b5b-real-detector`:
  - **`app/detection/model_loader.py` (NEW)**:
    - `resolve_model_path()` checks CWD, `BACKEND_DIR`, and repo root for `MODEL_PATH` before importing `torch`/`ultralytics`.
    - `extract_person_classes()` inspects `model.names` dynamically for `"person"` (case-insensitive) instead of hardcoding `0`, falling back to `classes=None` (no filter) when labels are unexpected.
    - `load_ultralytics_model()` loads the YOLO weights once, logs `model.names` and resolved `person_classes`, and runs a blank-frame warm-up inference before reporting ready.
  - **`app/detection/detector.py` & `app/detection/worker.py`**:
    - Added `UltralyticsDetector` with lazy imports (`cv2`, `numpy`, `supervision`, `model_loader`): decodes JPEG frames strictly in RAM (`cv2.imdecode`), calls `model.predict(img, imgsz=imgsz, conf=conf, classes=..., verbose=False)`, converts via `supervision.Detections.from_ultralytics`, clamps/normalizes `boxes` to `0..1`, and enforces `score >= conf`. Raw occupancy count remains `len(boxes)`.
    - Added `FrameDecodeError(ValueError)` strictly for JPEG byte/empty/decode validation in `UltralyticsDetector` (without catching unrelated `ValueError`s from `model.predict()` or `supervision`), and mapped `FrameDecodeError` in `run_worker()` to `BAD_IMAGE` while preserving `DETECTOR_UNAVAILABLE` for genuine detector/inference failures.
    - Updated `build_detector("ultralytics", ...)` to construct `UltralyticsDetector` while keeping `fake` as default for tests/CI and keeping the main Flask process completely free of `torch`/`ultralytics`.
  - **`app/detection/tracker.py`, `manager.py`, `container.py`**:
    - Added optional `ByteTrackTrackerHook` & `build_tracker()` (`USE_TRACKER=true`) using `trackers.ByteTrackTracker(frame_rate=..., track_activation_threshold=...)` per source (with `PassThroughTracker` fallback if `trackers` is uninstalled). Analytics only — never alters occupancy count; resets on `reset=True`, `ResetSource`, and 30 s inactivity.
    - Updated `DetectionManager.__init__` and `start()` so `DETECTOR_BACKEND=ultralytics` only validates `MODEL_PATH` in the main process and passes `model_path`, `target_fps`, `detect_conf`, and `warmup_imgsz` into the spawned `run_worker()` process (`container.py` wires `cfg.model_path`).
    - Tightened `check_health()` `worker_alive` check during `stop()` teardown (`self._started and self._detector_status != "unavailable"`).
  - **`eval/eval_latency.py` & `docs/DECISIONS.md`**:
    - Built `eval/eval_latency.py` supporting `--input` (image folder or video file), `--frames`, `--model`, `--backend`, `--conf`, `--imgsz`, `--use-tracker`, and `--timeout` over the real spawned worker + Socket.IO `frame:submit` pipeline.
    - Fail-fast setup checking: validates responses from `PATCH /api/v1/settings`, `POST /api/v1/zones`, and `POST /api/v1/sources`, printing validation errors and exiting nonzero before inference (`--conf 0.05` verified exiting `1` with `422 VALIDATION_ERROR`), and printing `effective_imgsz` / `effective_conf` on success (`--conf 0.85 --imgsz 480` verified reaching detector).
    - Full per-frame accounting (`submitted`, `succeeded`, `busy_dropped`, `other_failed`, `timed_out`), strict `seq` matching that ignores late timed-out results, separate `Worker startup` and `First frame` reporting, `sample_size` percentile reporting (omitting percentiles and flagging `[PARTIAL RUN]` when `succeeded == 0`), and explicit **in-process submit-to-result** latency labeling.
    - Measured against `D:\crowdvision\people_model.pt` (`{0: 'person'}`) on `AMD Ryzen 7 7840HS w/ Radeon 780M Graphics` (`torch 2.15.0+cpu`, `ultralytics 8.4.220`, `opencv-python 5.1.0.95`, `supervision 0.32.3`, `imgsz=640`, `conf=0.35`, `USE_TRACKER=false`, `20` frames from `ultralytics/assets`):
      - `Worker startup`: **`5710.3 ms`** (`spawn + YOLO load + blank warm-up`)
      - `Frames`: `submitted=20 | succeeded=20 | busy_dropped=0 | other_failed=0 | timed_out=0`
      - `First frame`: `bus.jpg#1 -> count=3, infer_ms=814.20, in_process_e2e_ms=830.75`
      - `infer_ms (sample_size=20)`: `min=25.53 | p50=32.39 | p95=82.04 | max=814.20`
      - `in_process_e2e_ms (sample_size=20)`: `min=33.70 | p50=40.07 | p95=95.19 | max=830.75` (**PASS**, `<1500 ms` target)
    - Recorded ADR in `docs/DECISIONS.md` keeping `.pt` CPU default over OpenVINO/ONNX given >12x p95 headroom.
  - **Tests**:
    - Extended `tests/unit/test_detection.py` (`extract_person_classes`, `resolve_model_path`, `UltralyticsDetector` JPEG decode/normalization/unfiltered fallback, `FrameDecodeError` vs `ValueError` separation, `run_worker` `BAD_IMAGE` vs `DETECTOR_UNAVAILABLE` mapping, `ByteTrackTrackerHook`, and `"torch" not in sys.modules` in main process).
    - Extended `tests/integration/test_detection_pipeline.py` with `TestUltralyticsRealWorkerEndToEnd` (cleanly skipped when `torch`/model absent): real YOLO inference counts (`zidane.jpg`, `bus.jpg`), normalized boxes, `/api/v1/health`, `detect_once()`, zero main-process disk writes, `"torch" not in sys.modules` verification, worker kill/restart recovery with post-restart `zidane.jpg` inference, and decode failure returning `BAD_IMAGE` while preserving prior zone state and recovering cleanly.
    - Focused B5a+B5b detection suite (`.\.venv\Scripts\python.exe -m pytest tests/unit/test_detection.py tests/integration/test_detection_pipeline.py -v --tb=short`): **`44 passed, 72 warnings in 82.77s`**.
    - Full backend suite (`.\.venv\Scripts\python.exe -m pytest tests/ -v --tb=short`): **`237 passed, 1 skipped, 339 warnings in 97.65s`** (`1` skipped: `test_journal_mode_wal` on `:memory:` SQLite, covered by `test_journal_mode_wal_on_file_db`).

## In progress
- None (Phase B5b fixes complete and verified on `be/b5b-real-detector`; awaiting review/commit. Phase B6 not started).

## Blocked / questions for Person A
- None.

## Requests for AI-B (frontend)
- `DETECTOR_BACKEND=ultralytics` works end-to-end with `people_model.pt` (`p95 in-process submit-to-result = 95.19 ms` on CPU at `640 px`); ready for joint webcam/monitor testing (`DETECTOR_BACKEND=ultralytics` in local `backend/.env` using `backend/.venv\Scripts\python.exe`).

## Untested / known issues
- Browser capture-to-result latency (webcam capture, browser JPEG encoding, and WebSocket transport over a live frontend connection to Person B's monitor screen) is **pending Person B's monitor test**; measured `95.19 ms` p95 is strictly **in-process submit-to-result**.
- Real `trackers` (`2.7.x`) package was not installed in `backend/.venv` (keeping `USE_TRACKER=false` default per setup notes); `ByteTrackTrackerHook` constructor (`frame_rate`, `track_activation_threshold`) and `update(..., timestamp=...)` / `reset()` were verified against the `trackers==2.7.1` wheel source and tested with a matching stub.
- Child-process zero disk writes/JPEG logging (`worker.py` / `detector.py`) verified by code inspection; main-process zero disk writes verified via `open`/`tempfile` spies during real YOLO execution.
- Carried over: retention cleanup of citizen reports (`B7`), `flask set-password` failure paths, `413 PAYLOAD_TOO_LARGE`, and `test_journal_mode_wal` on `:memory:` SQLite (covered by `test_journal_mode_wal_on_file_db`).

## Next 3 steps
1. Run manual live webcam / crowd video test against Person B's monitor screen with `DETECTOR_BACKEND=ultralytics` in `backend/.env` to measure browser capture-to-result latency.
2. Review and commit `be/b5b-real-detector` (and merge B5a + B5b PRs).
3. Begin Phase B6 (M5): `WebPushNotifier` (`pywebpush` + `py-vapid`) and `/push/*` endpoints.

## Numbers (latency, MAE, coverage) once available
- CPU (`AMD Ryzen 7 7840HS`), `people_model.pt` (`imgsz=640`, `conf=0.35`, `USE_TRACKER=false`, `torch 2.15.0+cpu`, `sample_size=20`):
  - Worker startup (`spawn + YOLO load + blank warm-up`): **`5710.3 ms`**
  - First frame (`bus.jpg#1`): **`814.20 ms` infer**, **`830.75 ms` in-process submit-to-result**
  - Inference (`infer_ms`): **`p50 = 32.39 ms`**, **`p95 = 82.04 ms`**
  - In-process submit-to-result (`in_process_e2e_ms`): **`p50 = 40.07 ms`**, **`p95 = 95.19 ms`** (target `< 1500 ms`; browser capture-to-result pending Person B's monitor test)
- Pure `app/engine/` unit coverage: **97%** (measured in B4a). Counting MAE/RMSE evaluation deferred to B9.
