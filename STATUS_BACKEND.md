# Backend status — updated 2026-11-27 13:41 IST
## Phase: B4a (done)
## Done since last update
- Implemented Phase B4a (M3 part 2a — pure Python zone/alert engine) on branch `be/b4a-zone-engine` with zero Flask, SQLAlchemy, Socket.IO, or `threading` imports inside the engine logic (did not modify DB, endpoints, or realtime):
  - `app/engine/smoothing.py`: `RollingMedian` (per-source rolling median over last N raw counts, `resize()` preserving recent samples on reload, `clear()` on reset).
  - `app/engine/zone_machine.py`: `ZoneMachine` & `LevelTransition` (hysteresis factor `h`, `debounce_s` upgrade hold, `clear_s` downgrade hold, pending-timer reset when candidate target changes, immediate `NO_DATA` on stale outage & immediate recovery, 60 s sliding-window trend with `+/-0.3` density or `+/-2` count thresholds).
  - `app/engine/alert_rules.py`: pure functions `evaluate_alert_transition` and `evaluate_tick_alerts`, caller-supplied snapshots `OpenAlertSnapshot` & `ResolvedReraiseSnapshot` (plus dict coercion helpers), and immutable action dataclasses (`CreateAlert`, `ReopenAlert`, `EscalateAlert`, `UpdatePeak`, `ClearCondition`, `AutoClearAlert`, `RecordFeedEvent`, `Remind`, `MarkReraiseChecked`, `EmitZoneUpdate`, `SendPush`).
  - `app/engine/zone_engine.py`: `ZoneEngine` orchestrating sources -> max fresh-source metric -> `ZoneMachine` -> `alert_rules`, with `boot()` (loads open alerts and pending reraises), `reload()` (preserves smoothing buffers, levels, and pending timers), `ingest()`, `tick()`, and alert sync helpers (`acknowledge_alert`, `respond_alert`, `resolve_alert`, `set_open_alert`).
  - Temporarily isolated B3's `StubZoneEngine` in `app/engine/_stub_b3.py` (re-exported by `zone_engine.py`) so B3 callers remain untouched until B4b.
- **Tests & Coverage**:
  - Added `tests/unit/test_engine.py` covering all 15 required table-driven and property-style scenarios with `FakeClock` (3600 s invariant check, hysteresis boundaries, `COUNT` vs `DENSITY`, multi-source max/stale, `FEED_LOST`/`FEED_RESTORED`, boot restore, `CRITICAL` non-auto-clear, re-raise after resolve, `reload()` preservation, cooldown suppression, reminder timing).
  - `python -m pytest tests/unit -v --cov=app/engine --cov-report=term-missing` -> **54 passed in 4.19s**, **97% total coverage** on `app/engine/` (`alert_rules.py` 100%, `smoothing.py` 100%, `zone_machine.py` 99%, `zone_engine.py` 98%, `_stub_b3.py` 83%).

## In progress
- None (Phase B4a complete on `be/b4a-zone-engine`; ready for review/commit. Phase B4b not started).

## Blocked / questions for Person A
- None.

## Requests for AI-B (frontend)
- No API or event changes in B4a (pure engine only; B4b will wire alerts/advisories/history REST + 1 Hz background loop).

## Untested / known issues
- Integration with SQLite transactions, `AlertService.apply(actions)`, 1 Hz `tasks.py` loop, and Socket.IO emitters is deferred to Phase B4b as scoped.
- Carried over from B0-B3: `--serve` subprocess live browser test, real WebSocket TCP handshake, `SAFE` `alternatives` ranking over REST, `flask set-password` failure paths, `413 PAYLOAD_TOO_LARGE`, and `test_journal_mode_wal` on `:memory:` SQLite (covered by `test_journal_mode_wal_on_file_db`).

## Next 3 steps
1. Review and commit `be/b4a-zone-engine`, merge into `main`.
2. Begin Phase B4b (M3 part 2b): wire `ZoneEngine` into `Container` & `DetectionManager` (removing `_stub_b3.py`), build `AlertService.apply`, alert/advisory REST endpoints, `/zones/{id}/history`, and 1 Hz `tasks.py` loop.
3. Begin Phase B5 (M4): separate-process YOLOv8n worker, `frame:submit` / `frame:result`, and per-source leases.

## Numbers (latency, MAE, coverage) once available
- `app/engine/` unit coverage: **97%** (`alert_rules.py` 100%, `smoothing.py` 100%, `zone_machine.py` 99%, `zone_engine.py` 98%).
