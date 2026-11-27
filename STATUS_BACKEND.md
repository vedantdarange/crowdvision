# Backend status — updated 2026-11-27 12:49 IST
## Phase: B3 (done)
## Done since last update
- Implemented Phase B3 (M3 part 1 — Fake detector and fake feed) on branch `be/b3-fake-feed`:
  - **Protocol & Detector (`app/detection/`)**:
    - `app/detection/protocol.py`: pure primitive dataclasses (`DetectRequest`, `DetectResult`, `Shutdown`, `ResetSource`, `Ping`, `Pong`, `Box` alias) ready for multiprocessing queues in B5; no `torch` imports anywhere.
    - `app/detection/detector.py`: `Detector` Protocol and deterministic `FakeDetector(seed=..., default_count=...)` returning configurable normalised `[x1, y1, x2, y2, conf]` boxes.
    - `app/detection/manager.py`: `DetectionManager` skeleton with `ingest_count(source_id, count, now)` as the single shared entry point for `fake-feed` (B3) and real worker results (B5).
  - **Temporary Engine Stub (`app/engine/zone_engine.py`)**:
    - Implemented `StubZoneEngine` (pure Python, `# TEMPORARY until B4`) storing per-source `last_frame_at` and naive in-memory `LiveState` (`density = count / coverage_area_m2`, threshold-based level without debounce/hysteresis, naive `trend`). Wired into `ZoneService` and `SourceService` so REST views reflect live state too. B4 will replace this with the full `ZoneEngine`.
  - **Realtime Emitter (`app/realtime/emitter.py`)**:
    - `RealtimeEmitter` (plus module-level `emit_zone_update` / `emit_zone_detail` wrappers): emits `zone:update` (`PublicZoneState` to room `public`) and `zone:detail` (`ZoneState` to room `role:police`) using B2 serializers only, throttled to `<= 1/s/zone` unless `level` or `trend` changed.
  - **Fake Feed Script, CLI & Docs**:
    - `scripts/fake_feed.py` + `flask fake-feed --zone <id> --profile ramp|spike|flap|offline [--source <id>] [--speed 1.0] [--serve] [--port 5000]` in `app/cli.py`.
    - Profile counts auto-scale to each zone's `mode` (`COUNT` vs `DENSITY`), thresholds, and `source.coverage_area_m2`.
    - Documented setup and `flask fake-feed` usage in `backend/README.md`.
  - **Tests**:
    - Added `tests/unit/test_detection.py` and `tests/integration/test_fake_feed.py` (protocol pickling, no `torch`, deterministic `FakeDetector`, `StubZoneEngine`, `RealtimeEmitter` `FakeClock` throttling, relative profile bounds, `SocketIOTestClient` police `zone:detail` vs public-only `PublicZoneState` key-set equality, CLI invocation).
    - Full suite (`python -m pytest tests/ -v --tb=short`): `157 passed, 1 skipped in 20.47s`.
    - CLI smoke check: `flask fake-feed --zone 1 --profile ramp --speed 200` stepped Zone 1 (`Main Gate`) from `SAFE` -> `WARNING` -> `CRITICAL` -> `SAFE` across 60 frames.

## In progress
- None (Phase B3 complete on `be/b3-fake-feed`, ready for review/commit; Phase B4 not started).

## Blocked / questions for Person A
- None (confirmed `--serve` flag kept on `flask fake-feed` for single-process live browser testing without Redis, and 60 s total `ramp` cycle: 30 s up + 30 s down). Also verified standalone `python scripts/fake_feed.py --zone 1 --profile spike --speed 200` and post-edit `pytest` (`157 passed, 1 skipped in 19.54s`).

## Requests for AI-B (frontend)
- **Live fake-feed command for frontend dev** (run from `backend/`):
  - Single-process live server + ramp on Zone 1 (Main Gate): `flask fake-feed --zone 1 --profile ramp --serve`
  - Available profiles: `ramp`, `spike`, `flap`, `offline` (add `--speed 2.0` to run 2x faster, or `--zone 3` for Exit Lane `DENSITY` mode).
- `zone:update` (room `public`, `PublicZoneState`) and `zone:detail` (room `role:police`, `ZoneState`) now emit live during fake-feed runs.

## Untested / known issues
- `--serve` flag in `flask fake-feed` (starting the Werkzeug/Socket.IO HTTP server in a live process) was not tested via automated subprocess test; the background profile execution (`run_fake_feed`), Socket.IO emits (`SocketIOTestClient`), and non-`--serve` CLI runner were all tested.
- `offline` profile does not yet cause an active zone to transition *back* to `NO_DATA` after receiving data (that `stale_after_s` 1 Hz tick belongs to B4).
- Carried over from B0/B2: real browser WebSocket TCP handshake, `SAFE` `alternatives` ranking over REST, `flask set-password` failure paths, `413 PAYLOAD_TOO_LARGE`, and `test_journal_mode_wal` on `:memory:` SQLite (covered by `test_journal_mode_wal_on_file_db`).

## Next 3 steps
1. Review and commit `be/b3-fake-feed`, merge into `main`.
2. Begin Phase B4 (M3 part 2): pure `ZoneEngine` + `alert_rules` (with all 14 table-driven tests), `AlertService`, alert transitions, advisories, `/zones/{id}/history`, and 1 Hz `tasks.py` loop.
3. Begin Phase B5 (M4): separate-process YOLOv8n worker, `frame:submit` / `frame:result`, and per-source leases.

## Numbers (latency, MAE, coverage) once available
- Not yet measured (B5 / B9).
