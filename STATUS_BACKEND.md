# Backend status — updated 2026-11-27 01:01 IST
## Phase: B0 (done)
## Done since last update
- Created `backend/` layout matching `01_BACKEND_PLAN.md` §5, `eval/README.md`, and `backend/scripts/fake_feed.py` placeholder.
- Created `backend/requirements.txt` (pinned B0 packages only; `torch`/`ultralytics`/`gunicorn` commented for later phases); verified with `pip check` (no broken requirements).
- Implemented `app/config.py` (`Settings`, `load_settings()`, `normalize_sqlite_url()`) as the sole reader of `os.environ`, plus `backend/.env.example` with all 18 contract §10 env vars.
- Implemented `app/extensions.py` with SQLite pragma listener (`WAL`, `busy_timeout=5000`, `foreign_keys=ON`, `synchronous=NORMAL`).
- Implemented `app/__init__.py` (`create_app`, `MemoryRequest` in-memory upload stream factory, `MAX_CONTENT_LENGTH=5MB`, `ProxyFix`, global error handlers for `AppError`, Pydantic `ValidationError`, 400/404/405/413/HTTPException, and 500 `INTERNAL`), `app/container.py`, and `wsgi.py`.
- Implemented `app/core/`: `errors.py`, `responses.py`, `logging.py` (JSON logging + `request_id`), `clock.py` (`Clock`, `SystemClock`, `FakeClock`), `time.py` (`utcnow`, `to_iso_z`), and `geometry.py` (`polygon_area_m2` and `polygon_centroid` using local equirectangular projection — shared helper for `seed-demo` and future `ZoneService`).
- Implemented all 11 SQLAlchemy models in `app/models/models.py` with contract §3 `CHECK` constraints, `NOCASE` email uniqueness, partial unique indexes (`uq_zones_name_active`, `uq_alerts_zone_open`), `reraise_check_at`, `previous_alert_id`, and `FEED_LOST`/`FEED_RESTORED` event types; generated and applied initial Flask-Migrate migration (`71a56dd5987e_initial_schema.py`).
- Implemented `GET /api/v1/health` in `app/api/v1/health.py`.
- Implemented `flask seed-demo` and `flask set-password <email>` in `app/cli.py`; verified idempotency across two consecutive runs.
- Wrote unit & integration tests (`tests/conftest.py`, `tests/unit/test_core.py`, `tests/integration/test_health.py`, `tests/integration/test_errors.py`, `tests/integration/test_pragmas.py`, `tests/integration/test_seed.py`, `tests/fixtures/shape.py`).
- Recorded B0 architecture decisions in `docs/DECISIONS.md`.
- Initialized git repository on `main`, added `origin` remote, and created root `.gitignore`.

## In progress
- None (B0 complete, awaiting Phase B1 prompt).

## Blocked / questions for Person A
- `contract/examples/` did not exist yet; created a `health.json` proposal in the B0 report for AI-B rather than committing fixtures into `/contract`.

## Requests for AI-B (frontend)
- Please create `contract/examples/health.json` (proposal provided in B0 report) and `contract/CONTRACT_VERSION` (`1.1.0`) when scaffolding `/contract`.

## Untested / known issues
- `flask set-password` with an invalid/non-existent email or short password (< 8 chars) is not yet covered by a negative test (only happy path is tested).
- `413 PAYLOAD_TOO_LARGE` handler is wired in `create_app` but not yet tested with an actual >5 MB request.
- `flask run` tested on port 5055 with `--no-reload` for live smoke check; Socket.IO events are not wired until B2.

## Next 3 steps
1. Review `contract/examples/health.json` with AI-B (M0) and push `main`.
2. Begin Phase B1: Auth (`register`, `login`, `refresh`, `me`), `argon2` verification, DB-backed `roles_required`, `users` CRUD, `AuditService`, rate limiting.
3. Add role-matrix and proxy-aware IP rate-limit tests for B1.

## Numbers (latency, MAE, coverage) once available
- Not yet measured (B5 / B9).
