# Backend status — updated 2026-11-28
## Phase: B6 (done — audit fixes verified, ready to commit)
## Done since last update
- Implemented Phase B6 (M5 — Web Push and reminders) + all 4 audit fixes on branch `be/b6-web-push`:
  - **`requirements.txt` & local `.env`**:
    - Installed and pinned `pywebpush==2.5.0` and `py-vapid==1.9.6` (`pip check` clean).
    - Configured local git-ignored `backend/.env` with generated VAPID keypair and `VAPID_SUBJECT=mailto:vedmodzyt@gmail.com`.
  - **`app/push/notifier.py`**:
    - Implemented contract §9 payload builders `build_alert_payload()` (supports both `DENSITY` and `COUNT` zones, title `"<LEVEL> — <Zone>"`, `/police/alerts/{id}`, `alert-{id}`) and `build_sos_payload()` (`/police/reports?focus={id}`, `sos-{id}`, `CRITICAL`, filtering strictly to `CRUSH_RISK`, `FIRE`, and `MEDICAL` while leaving `LOST_CHILD` and `OTHER` in-app only).
    - Implemented `WebPushNotifier` implementing `Notifier` (`notify_alert`, `notify_sos`, `send_test`) and wired into `Container` (`app/container.py` + `app/__init__.py` start/`atexit` stop).
    - Alert and SOS dispatches enqueue non-blockingly after commit onto a bounded background queue (`maxsize=64`) executed in a dedicated daemon thread inside `flask_app.app_context()`, so `DetectionManager._pump_loop` and the 1 Hz background loop never stall on slow push endpoints; queue overflows drop the newest item, increment `dropped_count`, and log a warning without secrets or endpoints. `POST /push/test` (`send_test`) remains synchronous to return `{sent}`.
    - Uses shared `resolve_push_config()` rule for both `WebPushNotifier` and `GET /api/v1/config`: blank keys or invalid `VAPID_SUBJECT` keep the backend running, disable push (`is_configured=False`, `vapid_public_key: null`), and log a concise warning without keys.
    - Builds a **fresh** `vapid_claims = {"sub": ...}` dict on every `webpush()` call, sets `ttl=600`, `headers={"Urgency": "high"}`, and per-request `timeout=5.0`, delivers concurrently via `ThreadPoolExecutor`, and never logs full endpoint URLs or keys.
    - Extended `FakeNotifier` with matching `notify_sos` filtering and `send_test` recording.
  - **`app/models/models.py`, `migrations/versions/a4c8e2f19b30_add_push_subscription_revision.py`, `app/repositories/push_repo.py`, `app/api/v1/push.py`, `app/services/settings_service.py`**:
    - Added `PushSubscription.revision` + Alembic migration `a4c8e2f19b30` (upgraded cleanly `71a56dd5987e -> a4c8e2f19b30`). `upsert()` increments `revision` on re-registration; `record_delivery_results()` applies `ok`/`gone` (`404`/`410` delete)/`fail` (`5` consecutive failures delete) outcomes atomically via SQL `WHERE id = :id AND revision = :rev` so stale delayed outcomes never corrupt refreshed subscriptions.
    - Added `/api/v1/push/subscriptions` (`POST` upsert by `endpoint`, `DELETE ?endpoint=` using `request.args` directly without double `unquote`) and `POST /api/v1/push/test` (`200 {data: {sent}}`), restricted to active `police`/`admin` users; broadcasts filter to active (`is_active=True`) `police`/`admin` users.
    - Updated `GET /api/v1/config` (`RuntimeConfig.vapid_public_key`) using `resolve_push_config()` so `/config` and `WebPushNotifier` always agree.
  - **`docs/DEMO.md`**:
    - Added manual M5 Web Push verification checklist for locked Android Chrome via `cloudflared` HTTPS tunnel + Person B's F5 push UI.
  - **Tests**:
    - Added [tests/unit/test_push.py](file:///d:/crowdvision/backend/tests/unit/test_push.py) (13 tests: Alert & SOS payloads in `DENSITY`/`COUNT`, `LOST_CHILD`/`OTHER` exclusion, shared `resolve_push_config`/`mailto:` validation without key leaks, `FakeClock` + `FakeNotifier` cooldown/CRITICAL/escalation/reminder rules, fresh `vapid_claims` per call, log secret redaction, non-blocking failed/410 delivery).
    - Added [tests/integration/test_push.py](file:///d:/crowdvision/backend/tests/integration/test_push.py) (11 tests: RBAC + upsert + delete, encoded `%2B`/`%3D` unsubscribe owner-only, `/config` + notifier consistency on blank keys & invalid `VAPID_SUBJECT`, `/push/test` caller-scoped count, HTTP `410` delete, `5`-failure delete & success reset, stale delayed `410` vs same-row re-registration revision protection, disabled user exclusion, end-to-end `AlertService.apply` cooldown/CRITICAL/REOPENED/ESCALATED/REMINDER, and held-transport non-blocking pump/2nd-frame/tick-loop + full-queue overflow tests).
    - Extended [tests/integration/test_role_matrix.py](file:///d:/crowdvision/backend/tests/integration/test_role_matrix.py) with the 3 `/push/*` endpoints (`35` parametrized RBAC assertions total).
    - Focused B6/config/RBAC check (`tests/unit/test_push.py`, `tests/integration/test_push.py`, `tests/integration/test_config.py`, `tests/integration/test_role_matrix.py`): **`67 passed in 16.59s`**.
    - Full backend suite (`tests/`): **`264 passed, 1 skipped in 136.21s`** (`1` skipped: `test_journal_mode_wal` on `:memory:` SQLite, covered by `test_journal_mode_wal_on_file_db`).

## In progress
- None (Phase B6 audit fixes complete on `be/b6-web-push`; awaiting manual Android Chrome + HTTPS tunnel push verification).

## Blocked / questions for Person A
- None.

## Requests for AI-B (frontend)
- Ready for F5 integration: `GET /api/v1/config` exposes `vapid_public_key`, and `/api/v1/push/subscriptions` (`POST`/`DELETE`) + `POST /api/v1/push/test` are live with contract §9 payloads.

## Untested / known issues
- Locked Android Chrome manual test (`docs/DEMO.md`) via `cloudflared` HTTPS tunnel + Person B's F5 push screen has not yet been run (all `pywebpush` HTTP calls in automated tests used mocked `webpush` transport).
- Browser capture-to-result latency (joint frontend webcam stream + Person B's monitor screen) remains pending Person B's monitor test.
- Carried over: retention cleanup of citizen reports (`B7`), `flask set-password` failure paths, `trackers` real wheel installation (`USE_TRACKER=false` default), and `test_journal_mode_wal` on `:memory:` SQLite.

## Next 3 steps
1. Run manual Android Chrome + `cloudflared` HTTPS tunnel Web Push test (`docs/DEMO.md`) and joint webcam/monitor latency check with Person B.
2. Begin Phase B7 (M6): Citizen reports (`/reports/crowd`, `/reports/sos`, `/reports`, `PATCH /reports/{id}`, memory-only upload, SOS `notify_sos` hook, rate limits, retention).
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
