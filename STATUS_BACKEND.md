# Backend status — updated 2026-11-27 10:53 IST
## Phase: B2 (done)
## Done since last update
- Implemented Phase B2 (M2) on branch `be/b2-zones-realtime` following strict layering (`blueprint -> service -> repository -> model`) and Pydantic v2 validation:
  - **Schemas & Serializers**:
    - `app/schemas/zones.py` (`ZoneCreateRequest`, `ZonePatchRequest` — closed GeoJSON Polygon `[lng, lat]` with >= 3 distinct vertices, `shapely` `is_valid` + `exterior.is_simple`, `warning < critical` for density and counts, COUNT mode requires both counts).
    - `app/schemas/sources.py` (`SourceCreateRequest`, `SourcePatchRequest`).
    - `app/schemas/config.py` (`SettingsPatchRequest`, `HelpInfoSchema` with validated numeric ranges).
    - `app/schemas/serializers.py` (pure functions `serialize_public_zone`, `serialize_zone`, `serialize_source` + `LIVE_STATE_PLACEHOLDER` with `level="NO_DATA"`, `trend="STEADY"`, `density=None`, `count=None`, `live_updated_at=None`).
  - **Repositories & Services**:
    - `app/repositories/zone_repo.py`, `app/repositories/source_repo.py`, `app/repositories/settings_repo.py` (flush-within-transaction pattern so mutations and audit logs commit atomically).
    - `app/services/zone_service.py`: `/zones/live`, `/zones/{id}/public` (`{state, alternatives}` with nearest-3 SAFE helper), `/zones`, `/zones/{id}`, `POST /zones`, `PATCH /zones/{id}`, `DELETE /zones/{id}` (soft delete; 409 CONFLICT with open alert; frees name for reuse; server recomputes centroid + `area_m2` via `app/core/geometry.py`, 422 if client hint > 10% off, `1 <= area_m2 <= 10_000_000`, defaults from settings 3.0 / 4.0).
    - `app/services/source_service.py`: `/sources`, `POST /sources`, `PATCH /sources/{id}`, `DELETE /sources/{id}` (`coverage_area_m2` defaults to zone area, validated `1 <= coverage <= 2 * area`, admin-only — police sending it gets 403 `FORBIDDEN`; status always `OFFLINE`, `last_frame_at` null until B5).
    - `app/services/settings_service.py`: `/config` (`RuntimeConfig`, `vapid_public_key: null`, `contract_version` read from `contract/CONTRACT_VERSION`), `/help-info`, `/settings` GET/PATCH (defaults matching `app/cli.py` and contract §4.2/§5).
      - Validated `/settings` numeric ranges (default -> `[min, max]`): `detect_conf` `0.35` -> `[0.1, 0.9]`, `smoothing_window` `5` -> `[1, 15]` (int), `debounce_s` `3` -> `[0, 30]`, `clear_s` `8` -> `[0, 60]`, `hysteresis_ratio` `0.85` -> `[0.5, 0.99]`, `cooldown_s` `60` -> `[0, 600]`, `escalation_s` `60` -> `[10, 600]`, `stale_after_s` `10` -> `[3, 60]`, `reraise_after_s` `60` -> `[10, 600]`, `target_fps` `3` -> `[1, 10]` (int), `frame_width` `640` -> `[320, 1280]` (int), `jpeg_quality` `0.7` -> `[0.3, 0.95]`, `default_warning_density` `3.0` -> `[0.1, 10.0]`, `default_critical_density` `4.0` -> `[0.1, 10.0]` (plus `default_warning_density < default_critical_density` cross-check).
    - Audit entries logged atomically for `ZONE_CREATED`, `ZONE_UPDATED`, `ZONE_DELETED`, `SOURCE_CREATED`, `SOURCE_UPDATED`, `SOURCE_DELETED`, `SETTINGS_UPDATED`.
  - **Realtime (Socket.IO connect & session freshness)**:
    - `app/realtime/connect.py`: `on_connect` / `on_disconnect` registered before `socketio.init_app()` in `app/__init__.py`. Every client joins `public`; valid active users also join `user:{id}`, `role:police` (police + admin), `role:admin` (admin); invalid/expired/disabled tokens stay `public` and emit `auth:expired`; always emits `hello` `{role, server_time, contract_version}`.
    - Lock-guarded `sessions[sid]` registry and `enforce_session_freshness(now)` (leaves privileged rooms, emits `auth:expired`, disconnects expired/disabled/demoted sockets).
  - **Tests**:
    - Added `tests/integration/test_zones.py`, `tests/integration/test_sources.py`, `tests/integration/test_config.py`, `tests/integration/test_socketio.py`, `tests/unit/test_realtime.py`.
    - Extended `tests/integration/test_role_matrix.py` with all B2 routes.
    - Test suite result: `python -m pytest tests/ -v --tb=short` -> `144 passed, 1 skipped in 14.54s`.
    - Smoke test against seeded `backend/instance/app.db`: `GET /api/v1/zones/live` returned `200` with `Main Gate`, `Stage Area`, `Exit Lane` all at `NO_DATA`; Socket.IO `hello` returned `{'role': None, 'server_time': ..., 'contract_version': '1.1.0'}`.

## In progress
- None (Phase B2 complete on `be/b2-zones-realtime`, ready for review/commit; Phase B3 not started).

## Blocked / questions for Person A
- None (confirmed `GET /api/v1/zones?include_inactive=true` returns `403` for `police`, and `PATCH /api/v1/sources/{id}` stays `admin`-only per contract §6.2).

## Requests for AI-B (frontend)
- Please create `contract/examples/` fixtures when ready so backend contract tests can validate against them.
- `GET /api/v1/zones/live`, `GET /api/v1/zones/{id}/public`, `GET /api/v1/config`, `GET /api/v1/help-info`, and Socket.IO `hello` / `auth:expired` are ready on `be/b2-zones-realtime`.
- Validated `/settings` ranges for F7b are listed above under `Done since last update` (and in `backend/app/schemas/config.py` / `backend/app/services/settings_service.py`).

## Untested / known issues
- Socket.IO real TCP/WebSocket handshake from an external browser client (tested via `SocketIOTestClient` in-process).
- Real live `SAFE` zone ranking in `GET /zones/{id}/public` `alternatives` could only be tested by injecting mocked `live_states` into `ZoneService.get_public(...)` since the engine (B4) is not built yet (`GET /zones/live` and `/zones/{id}/public` over REST only return `NO_DATA`).
- Carried over from B0: `flask set-password` failure paths and `413 PAYLOAD_TOO_LARGE` (> 5 MB upload) remain untested; `test_journal_mode_wal` skips on `:memory:` SQLite (covered by `test_journal_mode_wal_on_file_db`).

## Next 3 steps
1. Review and commit `be/b2-zones-realtime`, merge into `main`.
2. Begin Phase B3 (M3 part 1): `Clock` integration, `FakeDetector`, `scripts/fake_feed.py` / `flask fake-feed` (`ramp`, `spike`, `flap`, `offline`).
3. Begin Phase B4 (M3 part 2): pure zone/alert engine, alert endpoints, advisories, `/zones/{id}/history`, and 1 Hz `tasks.py` loop.

## Numbers (latency, MAE, coverage) once available
- Not yet measured (B5 / B9).
