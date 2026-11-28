# Backend status — updated 2026-11-28
## Phase: B8 (Windows wsgi fix verified — ready to commit)
## Done since last update
- Implemented Phase B8 (M7 — Analytics, CSV export, audit log API, retention verification, demo SPA serving, and startup safety check) on branch `be/b8-analytics-demo` (branched from committed B7 `dc52f27`):
  - **`app/repositories/analytics_repo.py`, `app/services/analytics_service.py`, `app/api/v1/analytics.py`, `app/container.py`**:
    - Added `GET /api/v1/analytics/summary?from&to` (`police+`, defaults to last 24 h): computes `alerts_by_zone` (`warning`/`critical` grouped by `peak_level`), `avg_ack_seconds` / `avg_resolve_seconds` (`null` when none), `peak_hours` per zone from `zone_samples` converted to `Asia/Kolkata` (`UTC+5:30`, SQL `datetime(ts, '+330 minutes')`) before bucketing by hour with `timezone: "Asia/Kolkata"`, and `reports_by_status` (all 3 statuses always present, `0` when none).
    - Added `GET /api/v1/analytics/export/alerts.csv?from&to` (`admin`): UTF-8 with BOM (`\xef\xbb\xbf`) for Excel, `text/csv; charset=utf-8`, `Content-Disposition: attachment; filename="alerts.csv"`, RFC 4180 CSV escaping, exact contract columns (`id, zone, level, peak_level, status, peak_density, peak_count, created_at, acknowledged_at, resolved_at`), and ISO-Z timestamps.
  - **`app/repositories/audit_repo.py`, `app/services/audit_service.py`, `app/schemas/serializers.py`, `app/api/v1/audit.py`**:
    - Added `AuditRepository.list_paginated()`, `serialize_audit_log()`, and `GET /api/v1/audit-logs?page&limit&action=&actor_id=` (`admin`).
  - **`app/__init__.py`, `app/cli.py`, `wsgi.py`**:
    - Added `SERVE_FRONTEND=true` SPA static serving from `frontend/dist` (`/` and deep links such as `/police/alerts/3` fall back to `index.html` with `Cache-Control: no-cache`; `sw.js` served with `Cache-Control: no-cache`; `/assets/*` served with `Cache-Control: public, max-age=31536000, immutable`; `/api/*` and `/socket.io/*` never hit SPA fallback so `/api/unknown` returns JSON `404 NOT_FOUND`).
    - Added startup safety check (`_enforce_no_default_admin_passwords`): refuses startup when `SERVE_FRONTEND=true` and any `admin` user still verifies against `Demo@1234` unless `ALLOW_DEFAULT_PASSWORDS=true` (`flask set-password <email>` is skipped by `_one_shot_cli` so the documented fix can run).
    - Set `with_appcontext=False` on `@app.cli.command` handlers in `app/cli.py` so `CliRunner` invocations in tests do not load `wsgi.py` (`create_app()` in non-testing mode) and spawn background workers.
    - Updated `wsgi.py` so `python wsgi.py` runs `socketio.run(..., debug=False, use_reloader=False, allow_unsafe_werkzeug=True)` when `FLASK_ENV=production` (supporting `PORT` env override, default `5000`), and guarded module-level `app = create_app() if __name__ != "__mp_main__" else None` so Windows `multiprocessing.spawn` detector child processes do not create another Flask app while keeping `wsgi:app` exposed for Flask CLI and Gunicorn.
  - **`backend/README.md`**:
    - Documented dev mode, demo mode (`gunicorn -w 1 --threads 100 -b 0.0.0.0:5000 wsgi:app` on Linux/macOS with explanation of why `-w 1` is mandatory for in-process `ZoneEngine`/worker/Socket.IO/limiter state), Windows demo alternative (`python wsgi.py` and why Gunicorn/Waitress cannot be used for WebSockets on Windows), `cloudflared tunnel --url http://localhost:5000`, env variables, and the default-password startup safety check + `flask set-password`.
  - **Tests**:
    - Added [tests/integration/test_analytics_audit_demo.py](file:///d:/crowdvision/backend/tests/integration/test_analytics_audit_demo.py) (9 tests): analytics summary against seeded alerts/samples/reports, IST midnight UTC (`18:45 UTC` → hour `0`) & half-hour offset bucketing, CSV export BOM/headers/escaping/range, audit log pagination & filters, hourly `FakeClock` retention deletion of both `zone_samples` (> 7 days) and `reports` (> `REPORT_RETENTION_DAYS`), startup default-password refusal & `flask set-password` / `ALLOW_DEFAULT_PASSWORDS=true` recovery, `SERVE_FRONTEND=true` SPA deep links, cache headers, and `/api/unknown` JSON 404, plus `TestWsgiSubprocessEntryPoint` (`wsgi:app` import check and real Windows `python wsgi.py` subprocess startup with `DETECTOR_BACKEND=fake`, bounded `/api/v1/health` `detector="ready"` / `worker_alive=true`, 1 detector worker, WebSocket `frame:submit` → `frame:result`, and clean shutdown with zero orphan workers).
    - Extended [tests/integration/test_role_matrix.py](file:///d:/crowdvision/backend/tests/integration/test_role_matrix.py) with `/analytics/summary`, `/analytics/export/alerts.csv`, and `/audit-logs` (`43` parametrized RBAC routes).
    - `pip check`: **`No broken requirements found.`**
    - Full backend suite (`.\.venv\Scripts\python.exe -m pytest tests/ -v --tb=short`): **`297 passed, 1 skipped in 182.40s`** (`1` expected skip: `test_journal_mode_wal` on `:memory:` SQLite, covered by `test_journal_mode_wal_on_file_db`).

## In progress
- None (Phase B8 complete on `be/b8-analytics-demo`; awaiting `npm run build` by Person B + manual browser check at `http://localhost:5000/police/alerts/3` and commit).

## Blocked / questions for Person A
- None.

## Requests for AI-B (frontend)
- Ready for **M7 integration & demo build**: `/api/v1/analytics/summary`, `/api/v1/analytics/export/alerts.csv`, `/api/v1/audit-logs`, and `SERVE_FRONTEND=true` SPA serving (`frontend/dist` with `/police/alerts/3` fallback & `sw.js` `no-cache`) are ready. Run `npm run build` in `frontend/` and verify `http://localhost:5000/police/alerts/3`.

## Untested / known issues
- Real frontend deep-link and refresh test pending Person B’s build (SPA fallback, `sw.js`, and `/assets/*` headers verified using a temp `dist/` fixture).
- Linux `gunicorn -w 1 --threads 100 wsgi:app` verified by inspection only (Gunicorn requires POSIX and is not installed in WSL here; `wsgi:app` exposes Flask `app` cleanly under `__name__ == "wsgi"`, and `simple_websocket` source inspection confirmed `gunicorn.socket` and `werkzeug.socket` support, while Waitress lacks raw socket access for WebSockets).
- Locked Android Chrome manual test (`docs/DEMO.md`) via `cloudflared` HTTPS tunnel and joint webcam/monitor latency check remain pending Person B integration.
- Carried over: `flask set-password` failure paths, `trackers` real wheel installation (`USE_TRACKER=false` default), and `test_journal_mode_wal` on `:memory:` SQLite.

## Next 3 steps
1. Build frontend (`npm run build` by Person B) and verify opening `http://localhost:5000/police/alerts/3` directly in the browser with `SERVE_FRONTEND=true`.
2. Review and commit Phase B8 on `be/b8-analytics-demo` (leaving `frontend/package.json` and `crowd-photos-testing/` out).
3. Begin Phase B9 (M8): `eval/eval_counting.py`, `eval/eval_latency.py` alert/e2e soak testing, tracker vs raw-count comparison in `docs/EVALUATION.md`, and final freeze.

## Numbers (latency, MAE, coverage) once available
- **CPU (`backend/.venv`)** — `AMD Ryzen 7 7840HS`, `people_model.pt` (`imgsz=640`, `conf=0.35`, `USE_TRACKER=false`, `torch 2.15.0+cpu`):
  - `eval/eval_latency.py` (`20` frames, `ultralytics/assets`): Worker startup `9964.2 ms` | First frame `bus.jpg#1` `5712.29 ms` infer / `5733.82 ms` in-process e2e (`bus.jpg=3`, `zidane.jpg=2`) | `infer_ms`: `p50 = 52.45 ms`, `p95 = 351.53 ms` | `in_process_e2e_ms`: `p50 = 64.71 ms`, `p95 = 366.88 ms`
  - Paced `3.0 FPS` steady state (`60` frames / `20.0 s` wall, `16` logical CPUs): Main `0.500 s` (`2.50%` of 1 core), Worker `103.234 s` (`516.16%` of 1 core), Total `103.734 s` (`518.66%` of 1 core / **`32.42%` of system CPU**); `infer_ms` `p50 = 48.81 ms` / `p95 = 86.67 ms`, `in_process_e2e_ms` `p50 = 56.54 ms` / `p95 = 94.03 ms`
- **GPU (`backend/.venv-gpu`)** — `NVIDIA GeForce RTX 4060 Laptop GPU` (`8188 MiB`, Driver `616.92`, `cuda:0`), `people_model.pt` (`imgsz=640`, `conf=0.35`, `USE_TRACKER=false`, `torch 2.14.1+cu126`, `torchvision 0.29.1+cu126`):
  - `eval/eval_latency.py` (`20` frames, `ultralytics/assets`): Worker startup `9172.4 ms` | First frame `bus.jpg#1` `1520.41 ms` infer / `1540.62 ms` in-process e2e (`bus.jpg=3`, `zidane.jpg=2`) | `infer_ms`: `p50 = 21.50 ms`, `p95 = 105.83 ms` | `in_process_e2e_ms`: `p50 = 31.04 ms`, `p95 = 116.89 ms`
  - Paced `3.0 FPS` steady state (`60` frames / `20.0 s` wall, `16` logical CPUs): Main `0.672 s` (`3.36%` of 1 core), Worker `1.688 s` (`8.44%` of 1 core), Total `2.359 s` (`11.80%` of 1 core / **`0.74%` of system CPU**); `infer_ms` `p50 = 30.23 ms` / `p95 = 38.37 ms`, `in_process_e2e_ms` `p50 = 38.18 ms` / `p95 = 48.16 ms`
- **Browser capture-to-result latency:** Pending the joint monitor test with Person B (live webcam capture + browser JPEG encode + WebSocket transport).
- Pure `app/engine/` unit coverage: **97%** (measured in B4a). Counting MAE/RMSE evaluation deferred to B9.
