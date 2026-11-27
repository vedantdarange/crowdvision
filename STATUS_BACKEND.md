# Backend status — updated 2026-11-27 14:08 IST
## Phase: B4b (done)
## Done since last update
- Implemented Phase B4b (M3 part 2b — Wire ZoneEngine, Alerts API, Advisories, History & 1 Hz loop) on branch `be/b4b-wire-engine`:
  - **Engine wiring & B3 stub removal**:
    - Removed temporary `app/engine/_stub_b3.py` (`StubZoneEngine`).
    - Replaced stub in `Container` and `DetectionManager.ingest_count` with `ZoneEngine(auto_commit_alerts=False)` guarded by a single `threading.Lock` (`engine_lock`).
    - Added `app/services/engine_sync.py`: `boot_engine_from_db()` loads active zones, active sources, DB settings, open alerts (`AlertModel`), and pending `reraise_check_at` rows at `create_app()` startup; `reload_engine_from_db()` is hooked into `ZoneService`, `SourceService`, and `SettingsService` mutations while preserving smoothing buffers, levels, and pending timers.
  - **Push Notifier interface & AlertService**:
    - `app/push/notifier.py`: `Notifier` Protocol, `NoOpNotifier` (B6 replaces with WebPush), `FakeNotifier` (tests).
    - `app/repositories/alert_repo.py` + `app/services/alert_service.py`: `persist_actions()` + `dispatch_side_effects()` (`apply()`): persists alert creation, reopens, escalations, peak updates, `FEED_LOST`/`FEED_RESTORED`, reminders, condition clear, auto-clear, `last_push_at`, and re-raise check clearing in ONE DB transaction; syncs snapshots and dispatches Socket.IO events (`alert:new`, `alert:updated`, `alert:escalated`, `zone:update`, `zone:detail`) + `Notifier` calls ONLY after commit (zero emits on rollback).
    - `app/api/v1/alerts.py`: `GET /alerts` (comma `status`, `level`, `zone_id`, `from`, `to`, `active`, pagination, `sort`), `GET /alerts/{id}` (with timeline `events`), `POST /alerts/{id}/acknowledge|respond|resolve` (`409 INVALID_TRANSITION` on illegal transitions, `200` idempotent repeat, `reraise_check_at` set on resolve while `condition_active=True`, audit logs `ALERT_ACKNOWLEDGED`/`RESPONDING`/`RESOLVED`).
  - **Advisories REST & Realtime**:
    - `app/repositories/advisory_repo.py`, `app/schemas/advisories.py`, `app/services/advisory_service.py`, `app/api/v1/advisories.py`: `GET /advisories` (public, active & non-expired, global + `?zone_id=`), `POST /advisories`, `DELETE /advisories/{id}`, realtime `advisory:new` and `advisory:retracted` on `public`, audit `ADVISORY_CREATED`/`RETRACTED`.
  - **Zone History, Live Map State & SAFE Alternatives**:
    - `app/repositories/zone_sample_repo.py` + `GET /api/v1/zones/{id}/history` (`police+`, `bucket_s` in `10|60|300`, default last 30 min, max 5000 points).
    - `GET /zones/live` and `GET /zones/{id}/public` now read live `ZoneEngine` state and compute `alternatives` = up to 3 nearest active `SAFE` zones by centroid distance.
  - **1 Hz Background Loop (`app/realtime/tasks.py`)**:
    - `socketio.start_background_task` loop running inside `app.app_context()` with exception logging + rollback resilience: `enforce_session_freshness`, `engine.tick` + `alert_service.persist_actions`, `source:status` change emission (`ONLINE`/`OFFLINE`), `zone_samples` persistence (`<= 1 per 2 s` per zone with data), advisory expiry (`advisory:retracted {id}`), and hourly retention delete (`zone_samples > 7 days`).
  - **Tests & Smoke Check**:
    - Added `tests/integration/test_alerts_lifecycle.py`, `tests/integration/test_advisories_history.py`, extended `tests/integration/test_role_matrix.py` (all 32 routes).
    - Full suite (`python -m pytest tests/ -v --tb=short`): **`200 passed, 1 skipped in 18.19s`**.
    - Smoke test (`flask db upgrade`, `flask seed-demo`, `run_fake_feed(..., profile='ramp')`, `GET /api/v1/alerts`, police `SocketIOTestClient`): alert created + escalated (`peak_level='CRITICAL'`, `GET /alerts` status `200`), Socket.IO police client received `['alert:new', 'alert:escalated']`.

## In progress
- None (Phase B4b complete on `be/b4b-wire-engine`; ready for review/commit. Phase B5 not started).

## Blocked / questions for Person A
- None.

## Requests for AI-B (frontend)
- M3 backend is live on `be/b4b-wire-engine`: alerts (`/alerts*`), advisories (`/advisories*`), zone history (`/zones/{id}/history`), nearest-SAFE `alternatives` on `/zones/{id}/public`, and realtime events (`zone:update`, `zone:detail`, `alert:new`, `alert:updated`, `alert:escalated`, `source:status`, `advisory:new`, `advisory:retracted`).
- Run `flask fake-feed --zone 1 --profile ramp --serve` from `backend/` to drive a live demo server on `:5000`.

## Untested / known issues
- Live external browser WebSocket + `--serve` subprocess test (in-process `SocketIOTestClient` and background loop thread with `app_context` were verified).
- Retention deletion of citizen `reports > REPORT_RETENTION_DAYS` will hook into the hourly retention step once `ReportService` / B7 lands (B4b prunes `zone_samples > 7 days`).
- Carried over from B0: `flask set-password` failure paths, `413 PAYLOAD_TOO_LARGE`, and `test_journal_mode_wal` on `:memory:` SQLite (covered by `test_journal_mode_wal_on_file_db`).

## Next 3 steps
1. Review and commit `be/b4b-wire-engine`, merge into `main`.
2. Begin Phase B5 (M4): separate-process YOLOv8n worker, `frame:submit` / `frame:result`, per-source leases (`SOURCE_IN_USE`), queue-full `DETECTOR_BUSY`.
3. Begin Phase B6 (M5): `WebPushNotifier` (`pywebpush` + `py-vapid`) and `/push/*` endpoints.

## Numbers (latency, MAE, coverage) once available
- Pure `app/engine/` unit coverage: **97%** (measured in B4a). Latency/MAE pending B5/B9.
