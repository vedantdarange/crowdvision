"""tests/unit/test_bounded_state.py — Bounded-memory & leak-prevention tests (B9)."""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone

from app.core.clock import FakeClock
from app.detection.manager import DetectionManager, INFLIGHT_TTL_S
from app.detection.tracker import PassThroughTracker
from app.engine.alert_rules import MarkReraiseChecked, ResolvedReraiseSnapshot
from app.engine.zone_engine import ZoneEngine
from app.realtime.emitter import RealtimeEmitter
from app.realtime.tasks import BackgroundSchedulerState, SourceStatusTracker


def test_emitter_prune_zones_and_stale() -> None:
    clock = FakeClock(start=1_000_000.0)
    emitter = RealtimeEmitter(clock=clock, min_interval_s=1.0)

    for zid in range(1, 51):
        assert emitter._should_emit("zone:update", zid, "NORMAL", "STEADY")
        assert emitter._should_emit("zone:detail", zid, "NORMAL", "STEADY")

    assert emitter.stats()["throttle_entries"] == 100

    removed = emitter.prune_zones({1, 2, 3})
    assert removed == 94
    assert emitter.stats()["throttle_entries"] == 6

    clock.advance(seconds=3605)
    assert emitter.prune_stale(max_age_s=3600.0) == 6
    assert emitter.stats()["throttle_entries"] == 0


def test_scheduler_and_source_status_prune() -> None:
    tracker = SourceStatusTracker()
    for sid in range(1, 21):
        tracker.check_and_record(sid, "ONLINE")
    assert tracker.prune_sources({1, 2}) == 18
    assert set(tracker._status.keys()) == {1, 2}

    state = BackgroundSchedulerState()
    now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    for zid in range(1, 21):
        state.last_sample_at[zid] = now
    assert state.prune_zones({2, 5}) == 18
    assert set(state.last_sample_at.keys()) == {2, 5}


def test_zone_engine_pending_reraise_empty_keys_popped() -> None:
    engine = ZoneEngine(auto_commit_alerts=True)
    now_ts = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    snap = ResolvedReraiseSnapshot(
        id=10,
        zone_id=99,
        status="RESOLVED",
        resolved_at=now_ts,
        reraise_check_at=now_ts + timedelta(seconds=300),
    )
    engine._pending_reraises[99] = [snap]
    engine._apply_actions_in_memory(
        [MarkReraiseChecked(zone_id=99, alert_id=10)],
        snap.resolved_at + timedelta(seconds=10),
    )
    assert 99 not in engine._pending_reraises


def test_detection_manager_prune_runtime_state() -> None:
    dm = DetectionManager.__new__(DetectionManager)
    dm._pipeline_lock = threading.Lock()
    dm._request_queue = None
    dm._result_queue = None
    dm._process = None
    dm._detector_status = "unavailable"
    dm._inflight = {}
    dm._leases = {}
    dm._once_waiters = {}
    dm._ping_waiters = {}
    dm._pending_reset = {}
    dm._source_last_submitted_mono = {}
    dm._fake_counts = {}

    now_mono = time.monotonic()
    dm._inflight = {
        1: ("sid-a", 1, 1, False, now_mono - (INFLIGHT_TTL_S + 5.0)),
        2: ("sid-b", 2, 1, False, now_mono),
        3: ("sid-c", 999, 1, False, now_mono),
    }
    dm._leases = {
        1: ("sid-a", now_mono - 120.0),
        2: ("sid-b", now_mono),
        999: ("sid-c", now_mono),
    }
    dm._source_last_submitted_mono = {
        1: now_mono - 120.0,
        2: now_mono,
        999: now_mono,
    }
    dm._pending_reset = {2: False, 999: True}

    summary = dm.prune_runtime_state(active_source_ids={1, 2}, stale_after_s=10.0)
    assert summary["inflight_pruned"] >= 2
    assert summary["leases_pruned"] >= 1
    assert summary["inactive_sources_pruned"] >= 1

    stats = dm.runtime_stats()
    assert stats["inflight"] == 1
    assert stats["leases"] == 1
    assert stats["pending_reset"] == 1
    assert stats["last_submitted_sources"] == 1


def test_tracker_prune_inactive() -> None:
    pt = PassThroughTracker(inactivity_reset_s=30.0)
    pt.update(1, [], now_s=100.0)
    pt.update(2, [], now_s=125.0)
    assert pt.prune_inactive(now_s=135.0) == 1
    assert 1 not in pt._last_seen_s
    assert 2 in pt._last_seen_s
