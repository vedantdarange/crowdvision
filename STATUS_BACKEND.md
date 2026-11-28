# Backend status — updated 2026-11-28
## Phase: B7 (fixes verified — ready to commit)
## Done since last update
- Implemented Phase B7 (M6 — Citizen reports, privacy-preserving RAM upload, rate limiting, and retention) on `be/b7-citizen-reports` (branched from committed B6 `4e10e44`):
  - **`app/schemas/reports.py`, `app/schemas/serializers.py`, `app/repositories/report_repo.py`**:
    - Added `CrowdReportFormSchema`, `SosReportCreateRequest`, `ReportReviewRequest`, `serialize_report()` matching contract §5 & fixtures, and `ReportRepository` (`list_mine`, `list_filtered`, `delete_older_than`, and atomic `claim_review()` `WHERE id = :id AND status = 'PENDING'`).
  - **`app/services/report_service.py`, `app/api/v1/reports.py`, `app/detection/manager.py`**:
    - `POST /api/v1/reports/crowd` (`citizen+`): validates `multipart/form-data`, JPEG/PNG MIME + magic bytes, `MAX_CONTENT_LENGTH` 5 MiB (`5,242,880` B) total multipart request cap (`413 PAYLOAD_TOO_LARGE` / `422 VALIDATION_ERROR`), finite `lat`/`lng` (`-90..90` / `-180..180`), reads upload strictly in RAM via `MemoryRequest`, runs synchronous single-frame `DetectionManager.detect_once()` (`503 DETECTOR_UNAVAILABLE` when down/full/timed out; `422` on `BAD_IMAGE`), discards bytes immediately, matches GPS via `shapely` (`shape(geom).contains(Point(lng, lat))`) for `zone_id` & `density_hint`, and emits `report:new` to `role:police` after commit.
    - `POST /api/v1/reports/sos` (`citizen+`): validates `SosType`, matches GPS to active zone, persists `PENDING` SOS, emits `report:new` to `role:police`, and calls `notifier.notify_sos()` post-commit (`CRUSH_RISK`/`FIRE`/`MEDICAL` only; `LOST_CHILD`/`OTHER` in-app only).
    - `GET /reports/mine` (`citizen+`), `GET /reports` (`police+` with `kind`/`status`/`zone_id`/pagination), and atomic `PATCH /reports/{id}` (`police+`): `ReportService.review()` claims `PENDING -> VERIFIED|DISMISSED` atomically via `claim_review()`, saves winning decision + reviewer + timestamp + note + `REPORT_REVIEWED` audit entry in one transaction, commits before emitting `report:updated` once per unique connected socket (`to=["role:police", f"user:{owner}"]` deduplicating overlapping rooms), preserves `404` on missing reports, and returns `409 INVALID_TRANSITION` if already reviewed.
    - Per-user rate limiting via `_user_rate_limit_key()` (`user:{id}` from JWT identity): `1/minute` on `/reports/crowd` and `3 per 10 minutes` on `/reports/sos` returning `429 RATE_LIMITED`.
  - **`app/extensions.py`, `app/__init__.py`, `tests/conftest.py`**:
    - Fixed multi-app `RATELIMIT_ENABLED` isolation in `create_app()` (`RATELIMIT_ENABLED=True` default + `@limiter.request_filter` checking per-app `current_app.config["RATELIMIT_ENABLED"]`, avoiding storage wipes or singleton `limiter.enabled = False` leakage when sibling apps disable limits in the same process).
  - **`app/realtime/tasks.py`, `backend/README.md`, `.gitignore`**:
    - Extended hourly retention job to delete `reports` older than `REPORT_RETENTION_DAYS` (`30` days default) alongside `zone_samples` (> 7 days).
    - Documented RAM-only upload handling, 5 MiB (`5,242,880` B) total `multipart/form-data` `MAX_CONTENT_LENGTH` request cap, and `REPORT_RETENTION_DAYS` deletion policy in [backend/README.md](file:///d:/crowdvision/backend/README.md); excluded `crowd-photos-testing/` in `.gitignore`.
  - **Tests**:
    - Added [tests/integration/test_reports.py](file:///d:/crowdvision/backend/tests/integration/test_reports.py) (14 tests: inside/outside zone GPS matching, `report:new`/`report:updated` room isolation, single-delivery `report:updated` on overlapping `role:police` + `user:{id}` self-review socket, `> 500 KB` upload zero-temp-file verification, exact `5,242,880` B vs `5,242,881` B multipart boundary + 5 MiB raw file `413`, `422` validation, `503` worker down & queue full, late timed-out result discarded before next crowd report, real `crowd-photos-testing` photo with `ultralytics`, `SOS` `FIRE`/`CRUSH_RISK`/`MEDICAL` vs `OTHER`/`LOST_CHILD` `FakeNotifier` filtering, double-review `409`, post-claim rollback & retry, deterministic synchronized concurrent two-officer `VERIFIED`/`DISMISSED` race on file-backed SQLite DB, engine/alert isolation, `FakeClock` retention purge, per-user rate limits across IPs).
    - Extended [tests/integration/test_rate_limit.py](file:///d:/crowdvision/backend/tests/integration/test_rate_limit.py) (4 tests) with `test_create_app_rate_limit_isolation_across_both_orders` (`disabled_first` and `default_first` HTTP `/api/v1/reports/sos` verification).
    - Extended [tests/integration/test_role_matrix.py](file:///d:/crowdvision/backend/tests/integration/test_role_matrix.py) with all 5 `/reports/*` endpoints (`40` parametrized RBAC routes).
    - Focused reports suite (`tests/integration/test_reports.py`): **`14 passed in 46.30s`**.
    - Full backend suite (`.\.venv\Scripts\python.exe -m pytest tests/ -v --tb=short`): **`285 passed, 1 skipped in 208.45s`** (`1` expected skip: `test_journal_mode_wal` on `:memory:` SQLite, covered by `test_journal_mode_wal_on_file_db`).
    - Verified all 8 JPEG images in `crowd-photos-testing/` via `POST /api/v1/reports/crowd` on `backend/.venv-gpu` (`people_model.pt`, RTX 4060): all `8` returned `HTTP 201` with `8` `report:new` events delivered to the police Socket.IO client.

## In progress
- None (Phase B7 fixes verified on `be/b7-citizen-reports`; ready to commit before starting B8).

## Blocked / questions for Person A
- None.

## Requests for AI-B (frontend)
- Ready for F5 & F6 integration: Web Push (`GET /config` `vapid_public_key`, `/push/*`) and Citizen Reports (`/reports/crowd`, `/reports/sos`, `/reports/mine`, `/reports`, `PATCH /reports/{id}`, `report:new`, `report:updated`) are live per shared contract (`POST /reports/crowd` enforces a 5 MiB total multipart request cap via `MAX_CONTENT_LENGTH`).

## Untested / known issues
- Locked Android Chrome manual test (`docs/DEMO.md`) via `cloudflared` HTTPS tunnel + Person B's F5 push screen has not yet been run (all `pywebpush` HTTP calls in automated tests used mocked `webpush` transport).
- Browser capture-to-result latency (joint frontend webcam stream + Person B's monitor screen) remains pending Person B's monitor test.
- Carried over: `flask set-password` failure paths, `trackers` real wheel installation (`USE_TRACKER=false` default), and `test_journal_mode_wal` on `:memory:` SQLite.

## Next 3 steps
1. Commit Phase B7 changes on `be/b7-citizen-reports` (leaving `frontend/package.json` and `crowd-photos-testing/` out).
2. Run manual Android Chrome + `cloudflared` HTTPS tunnel Web Push test (`docs/DEMO.md`) and joint webcam/monitor test with Person B.
3. Begin Phase B8 (M7): Analytics summary & CSV export, startup default-password check, `/audit-logs`, and demo static serving (`SERVE_FRONTEND=true`).

## Numbers (latency, MAE, coverage) once available
- **CPU (`backend/.venv`)** — `AMD Ryzen 7 7840HS`, `people_model.pt` (`imgsz=640`, `conf=0.35`, `USE_TRACKER=false`, `torch 2.15.0+cpu`):
  - `eval/eval_latency.py` (`20` frames, `ultralytics/assets`): Worker startup `9964.2 ms` | First frame `bus.jpg#1` `5712.29 ms` infer / `5733.82 ms` in-process e2e (`bus.jpg=3`, `zidane.jpg=2`) | `infer_ms`: `p50 = 52.45 ms`, `p95 = 351.53 ms` | `in_process_e2e_ms`: `p50 = 64.71 ms`, `p95 = 366.88 ms`
  - Paced `3.0 FPS` steady state (`60` frames / `20.0 s` wall, `16` logical CPUs): Main `0.500 s` (`2.50%` of 1 core), Worker `103.234 s` (`516.16%` of 1 core), Total `103.734 s` (`518.66%` of 1 core / **`32.42%` of system CPU**); `infer_ms` `p50 = 48.81 ms` / `p95 = 86.67 ms`, `in_process_e2e_ms` `p50 = 56.54 ms` / `p95 = 94.03 ms`
- **GPU (`backend/.venv-gpu`)** — `NVIDIA GeForce RTX 4060 Laptop GPU` (`8188 MiB`, Driver `616.92`, `cuda:0`), `people_model.pt` (`imgsz=640`, `conf=0.35`, `USE_TRACKER=false`, `torch 2.14.1+cu126`, `torchvision 0.29.1+cu126`):
  - `eval/eval_latency.py` (`20` frames, `ultralytics/assets`): Worker startup `9172.4 ms` | First frame `bus.jpg#1` `1520.41 ms` infer / `1540.62 ms` in-process e2e (`bus.jpg=3`, `zidane.jpg=2`) | `infer_ms`: `p50 = 21.50 ms`, `p95 = 105.83 ms` | `in_process_e2e_ms`: `p50 = 31.04 ms`, `p95 = 116.89 ms`
  - Paced `3.0 FPS` steady state (`60` frames / `20.0 s` wall, `16` logical CPUs): Main `0.672 s` (`3.36%` of 1 core), Worker `1.688 s` (`8.44%` of 1 core), Total `2.359 s` (`11.80%` of 1 core / **`0.74%` of system CPU**); `infer_ms` `p50 = 30.23 ms` / `p95 = 38.37 ms`, `in_process_e2e_ms` `p50 = 38.18 ms` / `p95 = 48.16 ms`
- **Browser capture-to-result latency:** Pending the joint monitor test with Person B (live webcam capture + browser JPEG encode + WebSocket transport).
- Pure `app/engine/` unit coverage: **97%** (measured in B4a). Counting MAE/RMSE evaluation deferred to B9.
