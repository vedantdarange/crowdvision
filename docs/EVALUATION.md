# CrowdVision Evaluation Report

This document records measured evaluation results from Phase B9 scripts (`eval/eval_counting.py`, `eval/eval_latency.py`, `eval/eval_alerts.py`, and `eval/eval_soak.py`) run against real model weights and sample crowd media. Numbers below are direct measurements from the recorded runs; explicit `TODO` markers indicate steps requiring human labelling or the full 30-minute unattended soak run.

## 1. Test Environment & Configuration

| Item | Value |
| :--- | :--- |
| **OS / Platform** | `Windows-11-10.0.26300-SP0` |
| **CPU** | `AMD64 Family 25 Model 116 Stepping 1, AuthenticAMD` |
| **GPU Runtime** | `NVIDIA GeForce RTX 4060 Laptop GPU` (`torch==2.14.1+cu126`, CUDA active) |
| **CPU Baseline Env** | `torch==2.15.0+cpu` |
| **Detector Weights** | `D:\crowdvision\people_model.pt` (`ultralytics==8.4.220`, COCO class `0` person) |
| **Tracker Package** | `trackers==2.7.1` (`ByteTrackTracker`, analytics/eval comparison only) |
| **Pipeline Mode** | Single-image tracker-free detection (`USE_TRACKER=false` for live counting) |
| **Default Detector Settings** | `imgsz=640`, `detect_conf=0.35`, `target_fps=3.0` |
| **Default Engine Settings** | `smoothing_window=5`, `hysteresis_ratio=0.85`, `debounce_s=3.0`, `clear_s=8.0`, `stale_after_s=10.0` |

---

## 2. Counting Accuracy (`eval/eval_counting.py`)

Evaluated on 20 images using the supplied `labels.csv` (`eval/data/crowd-photos-and-videos/labels.csv`, files `processed_IMG_1.jpg`..`processed_IMG_20.jpg`, supplied counts spanning `29` to `291`) with **label provenance unverified**, running `UltralyticsDetector` on GPU in the exact single-image, tracker-free mode used by the live worker. Per-image predictions are saved to `eval/results/counting.csv`.

### 2.1 Per-Image Results (`imgsz=640`, `conf=0.35`)

| Image | Resolved File | True Count | Predicted Count | Signed Error | Abs Error | GPU Infer (ms) |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| `IMG_1.jpg` | `processed_IMG_1.jpg` | 233 | 10 | -223 | 223 | 28.29 |
| `IMG_2.jpg` | `processed_IMG_2.jpg` | 152 | 7 | -145 | 145 | 27.71 |
| `IMG_3.jpg` | `processed_IMG_3.jpg` | 29 | 18 | -11 | 11 | 28.99 |
| `IMG_4.jpg` | `processed_IMG_4.jpg` | 291 | 13 | -278 | 278 | 29.91 |
| `IMG_5.jpg` | `processed_IMG_5.jpg` | 96 | 17 | -79 | 79 | 31.44 |
| `IMG_6.jpg` | `processed_IMG_6.jpg` | 36 | 19 | -17 | 17 | 27.41 |
| `IMG_7.jpg` | `processed_IMG_7.jpg` | 118 | 13 | -105 | 105 | 29.31 |
| `IMG_8.jpg` | `processed_IMG_8.jpg` | 99 | 15 | -84 | 84 | 28.47 |
| `IMG_9.jpg` | `processed_IMG_9.jpg` | 167 | 8 | -159 | 159 | 28.13 |
| `IMG_10.jpg` | `processed_IMG_10.jpg` | 229 | 13 | -216 | 216 | 27.44 |
| `IMG_11.jpg` | `processed_IMG_11.jpg` | 139 | 9 | -130 | 130 | 30.01 |
| `IMG_12.jpg` | `processed_IMG_12.jpg` | 100 | 8 | -92 | 92 | 32.90 |
| `IMG_13.jpg` | `processed_IMG_13.jpg` | 117 | 20 | -97 | 97 | 28.49 |
| `IMG_14.jpg` | `processed_IMG_14.jpg` | 50 | 17 | -33 | 33 | 30.27 |
| `IMG_15.jpg` | `processed_IMG_15.jpg` | 238 | 12 | -226 | 226 | 28.23 |
| `IMG_16.jpg` | `processed_IMG_16.jpg` | 42 | 14 | -28 | 28 | 30.85 |
| `IMG_17.jpg` | `processed_IMG_17.jpg` | 49 | 14 | -35 | 35 | 26.21 |
| `IMG_18.jpg` | `processed_IMG_18.jpg` | 178 | 10 | -168 | 168 | 27.64 |
| `IMG_19.jpg` | `processed_IMG_19.jpg` | 43 | 22 | -21 | 21 | 30.49 |
| `IMG_20.jpg` | `processed_IMG_20.jpg` | 90 | 13 | -77 | 77 | 29.37 |

- **MAE (`scikit-learn`):** `111.200`
- **RMSE (`scikit-learn`):** `135.692`
- **Mean Signed Error (`pred - true`):** `-111.200` (systematic occlusion / small-head undercount)
- **Relative MAE:** `89.10%`
- **Mean GPU Inference Time:** `29.08 ms`

### 2.2 Hyperparameter Comparison (`imgsz` × `conf`)

Saved to `eval/results/counting_compare.csv`:

| `imgsz` | `conf` | MAE | RMSE | Mean Signed Error | Relative MAE | Mean GPU Infer (ms) |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 640 | 0.25 | 107.900 | 132.884 | -107.900 | 86.46% | 48.41 |
| 640 | 0.35 | 111.200 | 135.692 | -111.200 | 89.10% | 29.08 |
| 640 | 0.50 | 115.350 | 138.862 | -115.350 | 92.43% | 34.65 |
| 960 | 0.25 | 98.200 | 125.011 | -98.100 | 78.69% | 37.64 |
| 960 | 0.35 | 103.450 | 129.598 | -103.450 | 82.89% | 32.64 |
| 960 | 0.50 | 108.300 | 133.398 | -108.300 | 86.78% | 35.83 |

### 2.3 Video Mode: Raw Detections vs `ByteTrackTracker` Confirmed Counts

Evaluated on 60 sampled frames of `eval/data/crowd-photos-and-videos/crowd-video.mp4` (`25.00 fps` native sampled at `3.0 fps`, matching `target_fps=3.0` and `track_activation_threshold=0.35`, saved to `eval/results/counting_video.csv`). This comparison used **model outputs without hand-counted reference frames**, measuring relative detection suppression between raw `UltralyticsDetector` boxes and confirmed tracks:

- **Mean raw box count:** `2.63` detections/frame
- **Mean tracker-confirmed count:** `2.03` tracks/frame
- **Mean difference:** `+0.60` (`ByteTrackTracker` suppressed **`22.8%`** of raw detections)
- **Why ByteTrack is NOT used for live occupancy counts:** `trackers.ByteTrackTracker` enforces track activation thresholds and `minimum_consecutive_frames=2` confirmation before assigning a `tracker_id >= 0`. On Frame `0`, `3` visible people dropped to `0` confirmed tracks (`+3` lost), and stationary/momentarily occluded individuals frequently drop between sparse `3 fps` frames. Feeding raw `len(boxes)` into `ZoneEngine`'s 5-frame `RollingMedian` preserves accuracy without multi-frame track lock-in delay.
- **Pending manual reference frames:** Run `python eval/eval_counting.py --video <path> --video-labels <hand_counted_frames.csv>` with hand-counted video reference frames to score raw vs tracker MAE directly against verified ground-truth video counts.

---

## 3. Pipeline & Alert Latency (`eval/eval_latency.py`)

Measured via `SocketIOTestClient` in-process (excludes browser webcam capture & external network RTT).

| Run | Sample Size | Worker Startup | `infer_ms` (min / p50 / p95 / max) | `in_process_e2e_ms` (min / p50 / p95 / max) | `<1500 ms` Target |
| :--- | ---: | ---: | :--- | :--- | :--- |
| **GPU (`RTX 4060`, `crowd-video.mp4`)** | 20 | 9,098.7 ms | `12.26` / `15.53` / `68.55` / `993.45` | `17.68` / `24.00` / `83.11` / `1000.69` | **PASS** |
| **CPU (`torch 2.15+cpu`, `crowd-video.mp4`)** | 10 | 10,683.6 ms | `30.48` / `32.05` / `2888.51` / `5219.11` | `39.62` / `41.77` / `2895.59` / `5226.38` | **MISS** (cold frame 1 spike) |

Note on first-frame cold start: Frame 1 on a newly spawned worker incurs initial real-image CUDA/JIT warm-up (`993.45 ms` GPU, `5219.11 ms` CPU). Subsequent steady-state inference drops to `p50=15.53 ms` (GPU) and `p50=32.05 ms` (CPU).

### Alert Delivery Latency (`--mode alert`)

Measured as wall-clock latency from zone metric crossing the threshold (`debounce_s=0`, `smoothing_window=1`) to `alert:new` arrival on a connected police `SocketIOTestClient`:

- **`alert_dispatch_ms` (`ingest_count` threshold cross -> DB commit -> `alert:new` received, `n=10/10`):**
  `min = 3.53 ms` | **`p50 = 4.19 ms`** | **`p95 = 6.49 ms`** | `max = 7.57 ms`
- **`frame_to_alert_ms` (`frame:submit` -> cold frame #1 YOLO GPU infer -> `ZoneEngine` -> `alert:new`, `n=1`):** `1001.25 ms` (warm frame dispatch adds ~`4–6 ms` above steady `in_process_e2e_ms` ~`24 ms`).

---

## 4. False / Missed Alarms & Flicker Reduction (`eval/eval_alerts.py`)

Compares the production `ZoneEngine` (`smoothing_window=5`, `hysteresis_ratio=0.85`, `debounce_s=3.0`, `clear_s=8.0`, `stale_after_s=10.0`) against a naive unsmoothed threshold (`window=1`, `hysteresis=1.0`, `debounce=0`, `clear=0`). Saved to `eval/results/alerts.csv`:

| Scenario | Engine False Alarms | Engine Missed Alarms | Naive False Alarms | Engine Level Transitions | Naive Level Transitions | Flicker Reduction |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| `transient_spike` (1-2s spikes) | 0 | 0 | 3 | 0 | 5 | **100.0%** |
| `sustained_crowd_ramp` | 0 | 0 | 0 | 3 | 3 | 0.0% |
| `boundary_oscillation` | 0 | 0 | 8 | 1 | 27 | **96.3%** |
| `camera_dropout_recovery` | 0 | 0 | 0 | 4 | 4 | 0.0% |
| `crowd-video.mp4` (1 Hz, `n=40s`, `warn=3`) | 0 | — | — | 0 | 15 | **100.0%** |

- **TODO (Human video labels):** Provide a short video paired with frame/second-level ground-truth alarm intervals to compute real-video missed-alarm recall in addition to flicker reduction.

---

## 5. Stability Soak Test & Leak Hardening (`eval/eval_soak.py`)

### 5.1 Leak Audit Fixes Applied

Before running the soak benchmark, all long-lived in-memory maps were audited and bounded:
1. `RealtimeEmitter._last_sent`: added `prune_zones(active_zone_ids)` and `prune_stale(max_age_s=3600)` invoked on each 1 Hz tick.
2. `DetectionManager`: added `prune_runtime_state(active_source_ids, stale_after_s)` sweeping expired `_inflight`, expired `_leases`, stale `_source_last_submitted_mono`, and deleted/inactive source entries (emitting `ResetSource` to the worker), plus `runtime_stats()` for queue/map telemetry.
3. `BackgroundSchedulerState.last_sample_at` & `SourceStatusTracker._status`: added `prune_zones` / `prune_sources` invoked on every tick.
4. `run_worker` & `ByteTrackTrackerHook`: added periodic sweep for abandoned >1 h stale `source_last_seen` entries when map size exceeds `256` + `prune_inactive()`.
5. `ZoneEngine._pending_reraises`: pops empty `zone_id` keys once checks finish.

Verified by unit tests in `backend/tests/unit/test_bounded_state.py`.

### 5.2 Brief 60-Second Verification Soak (Passed; 30-Minute Soak Pending)

Command: `python eval/eval_soak.py --duration-s 60 --sample-interval-s 5 --include-real`
Telemetry logged every `5 s` across all 3 seeded zones (`fake-feed` waves) + 1 live YOLO camera source (`crowd-video.mp4`):

- **60-second soak status:** **PASS** (12 samples logged to `eval/results/soak.csv`)
- **Warm-up baseline total RSS (`main + worker`):** `1480.80 MB`
- **Final total RSS (`60 s`):** `1480.77 MB` (`-0.00%`)
- **Peak total RSS post-warm-up:** `1480.88 MB` (`+0.01%`, well under the `20%` growth threshold)
- **Thread count:** `25 -> 22`
- **Post-drain queues:** `inflight=0`, `request_queue_depth=0`, `result_queue_depth=0`, `throttle_entries=6`
- **30-minute soak status:** **PENDING** — full 1,800-second soak run awaits operator execution on the demo machine:
  ```powershell
  backend\.venv-gpu\Scripts\python.exe eval/eval_soak.py --duration-s 1800 --sample-interval-s 10 --include-real
  ```

---

## 6. Limitations & Future Work

1. **Severe Dense-Crowd Undercounting:** On images with 90–291 tightly packed people (`processed_IMG_*`), box detection undercounts heavily (`MAE = 111.2`, `MeanSignedError = -111.2`). YOLO detects distinct foreground people accurately at moderate density (`crowd-video.mp4`, sparse gates/corridors), but bounding-box detectors collapse small overlapping heads in dense aerial/high-angle views. Future work should integrate a point/density-map estimator (e.g., CSRNet, DM-Count, or P2PNet) or tiled SAHI inference for high-density scenes.
2. **Unverified Label Provenance & Small Static Evaluation Set:** Image counting metrics used the supplied `labels.csv` with **label provenance unverified** (20 static dense images with supplied counts `29–291`), and the video tracker comparison used model outputs **without hand-counted reference frames**. Expanding verified evaluation across lighting, camera height, and indoor/outdoor angles is recommended before calibrating production `DENSITY` thresholds per venue.
3. **In-Process Socket Benchmark:** `eval_latency.py` uses Flask-SocketIO's `SocketIOTestClient`, omitting browser `getUserMedia`/canvas JPEG encode time and LAN/tunnel WebSocket latency. End-to-end RTT over HTTPS (`cloudflared`) scales with upload bandwidth (`<= 300 KB/frame` cap enforced).
4. **Cold-Start Frame 1 Latency:** Even after worker warm-up on a blank image, the first real-resolution frame hits JIT/CUDA allocation latency (~`1.0 s` GPU, ~`5.2 s` CPU). Future work can run warm-up on a representative non-uniform JPEG or export ONNX/TensorRT engines (`onnxruntime` / OpenVINO) for faster cold CPU throughput.
