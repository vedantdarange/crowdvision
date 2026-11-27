"""tests/unit/test_engine.py — Pure unit tests for B4a zone & alert engine.

Covers all 15 scenarios in B4a using FakeClock (no DB, no Flask, no sleep).
"""
from __future__ import annotations

import random
from datetime import timedelta

import pytest

from app.core.clock import FakeClock
from app.engine.alert_rules import (
    AutoClearAlert,
    ClearCondition,
    CreateAlert,
    EmitZoneUpdate,
    EscalateAlert,
    MarkReraiseChecked,
    OpenAlertSnapshot,
    RecordFeedEvent,
    Remind,
    ReopenAlert,
    ResolvedReraiseSnapshot,
    SendPush,
    UpdatePeak,
    coerce_open_alert,
    coerce_resolved_reraise,
)
from app.engine.smoothing import RollingMedian
from app.engine.zone_engine import EngineSettings, SourceConfig, ZoneConfig, ZoneEngine
from app.engine.zone_machine import ZoneMachine


def _density_engine(
    *,
    smoothing_window: int = 1,
    debounce_s: float = 3.0,
    clear_s: float = 8.0,
    hysteresis_ratio: float = 0.85,
    stale_after_s: float = 10.0,
    cooldown_s: float = 60.0,
    escalation_s: float = 60.0,
    reraise_after_s: float = 60.0,
    warning_density: float = 3.0,
    critical_density: float = 4.0,
    coverage_area_m2: float = 10.0,
    extra_sources: list[SourceConfig] | None = None,
) -> ZoneEngine:
    eng = ZoneEngine()
    zones = [
        ZoneConfig(
            id=1,
            mode="DENSITY",
            warning_density=warning_density,
            critical_density=critical_density,
        )
    ]
    sources = [SourceConfig(id=1, zone_id=1, coverage_area_m2=coverage_area_m2)]
    if extra_sources:
        sources.extend(extra_sources)
    settings = EngineSettings(
        smoothing_window=smoothing_window,
        debounce_s=debounce_s,
        clear_s=clear_s,
        hysteresis_ratio=hysteresis_ratio,
        stale_after_s=stale_after_s,
        cooldown_s=cooldown_s,
        escalation_s=escalation_s,
        reraise_after_s=reraise_after_s,
    )
    eng.boot(zones, sources, settings)
    return eng


class TestRollingMedian:
    def test_median_resize_and_clear(self):
        rm = RollingMedian(window=5)
        assert rm.value is None
        for v in (10, 2, 8, 4, 6):
            rm.push(v)
        assert len(rm) == 5
        assert rm.value == 6.0

        rm.resize(3)
        assert rm.window == 3
        assert len(rm) == 3
        assert rm.value == 6.0  # median(8, 4, 6) = 6

        rm.resize(3)  # no-op
        rm.clear()
        assert len(rm) == 0
        assert rm.value is None

    def test_invalid_window_raises(self):
        with pytest.raises(ValueError):
            RollingMedian(0)
        rm = RollingMedian(3)
        with pytest.raises(ValueError):
            rm.resize(0)


class TestDebounceAndSpikes:
    def test_01_one_frame_spike_ignored_and_sustained_moves_up_after_debounce(self):
        """Req #1: 1-frame spike does nothing; sustained value moves up after debounce_s."""
        clock = FakeClock(start=1000.0)
        # window=1 isolates debounce logic from smoothing; also verified with window=5
        eng = _density_engine(smoothing_window=1, debounce_s=3.0)

        # Enter SAFE immediately from NO_DATA
        eng.ingest(1, 10, clock.utcnow())  # 1.0/m² -> SAFE
        assert eng.get_zone_state(1, clock.utcnow())["level"] == "SAFE"

        # 1-frame spike to WARNING (35/10 = 3.5) at t+1s, then back to SAFE at t+2s
        clock.advance(1.0)
        actions = eng.ingest(1, 35, clock.utcnow())
        assert eng.get_zone_state(1, clock.utcnow())["level"] == "SAFE"
        assert not any(isinstance(a, CreateAlert) for a in actions)

        clock.advance(1.0)
        eng.ingest(1, 10, clock.utcnow())  # resets pending timer
        assert eng.get_zone_state(1, clock.utcnow())["level"] == "SAFE"

        # Sustained WARNING starting at t=1003.0 -> held at 1005.0 (2s < 3s) -> still SAFE
        clock.advance(1.0)  # t=1003
        eng.ingest(1, 35, clock.utcnow())
        clock.advance(2.0)  # t=1005
        eng.ingest(1, 35, clock.utcnow())
        assert eng.get_zone_state(1, clock.utcnow())["level"] == "SAFE"

        # At t=1006 (3.0s elapsed) -> moves to WARNING and creates alert
        clock.advance(1.0)  # t=1006
        actions = eng.ingest(1, 35, clock.utcnow())
        assert eng.get_zone_state(1, clock.utcnow())["level"] == "WARNING"
        assert any(isinstance(a, CreateAlert) and a.level == "WARNING" for a in actions)

    def test_pending_timer_resets_when_candidate_target_changes(self):
        clock = FakeClock(start=100.0)
        eng = _density_engine(smoothing_window=1, debounce_s=3.0)
        eng.ingest(1, 0, clock.utcnow())  # SAFE

        # Candidate CRITICAL at t=101
        clock.advance(1.0)
        eng.ingest(1, 45, clock.utcnow())  # 4.5 -> pending CRITICAL since 101
        # Drops to WARNING at t=103 (after 2s) -> candidate changes to WARNING, timer resets to 103
        clock.advance(2.0)
        eng.ingest(1, 32, clock.utcnow())
        assert eng.get_zone_state(1, clock.utcnow())["level"] == "SAFE"
        # At t=104 (only 1s as WARNING) -> still SAFE
        clock.advance(1.0)
        eng.ingest(1, 32, clock.utcnow())
        assert eng.get_zone_state(1, clock.utcnow())["level"] == "SAFE"
        # At t=106 (3s as WARNING) -> transitions to WARNING
        clock.advance(2.0)
        eng.ingest(1, 32, clock.utcnow())
        assert eng.get_zone_state(1, clock.utcnow())["level"] == "WARNING"


class TestHysteresisAndPaths:
    @pytest.mark.parametrize(
        "metric_count,expected_after_hold",
        [
            (28, "WARNING"),  # 2.8 >= W*h (2.55) -> stays WARNING
            (26, "WARNING"),  # 2.6 >= 2.55 -> stays WARNING
            (25, "SAFE"),     # 2.5 < 2.55 for clear_s -> drops to SAFE
        ],
    )
    def test_02_hysteresis_warning_boundaries(self, metric_count, expected_after_hold):
        """Req #2a: W=3, h=0.85 -> 2.8 stays WARNING, 2.5 (<2.55) for clear_s returns to SAFE."""
        clock = FakeClock(start=0.0)
        eng = _density_engine(smoothing_window=1, clear_s=8.0, hysteresis_ratio=0.85)
        eng.ingest(1, 32, clock.utcnow())  # start in WARNING directly from NO_DATA
        assert eng.get_zone_state(1, clock.utcnow())["level"] == "WARNING"

        clock.advance(1.0)
        eng.ingest(1, metric_count, clock.utcnow())
        clock.advance(8.0)
        eng.ingest(1, metric_count, clock.utcnow())
        assert eng.get_zone_state(1, clock.utcnow())["level"] == expected_after_hold

    @pytest.mark.parametrize(
        "metric_count,expected_after_hold",
        [
            (35, "CRITICAL"),  # 3.5 >= C*h (3.4) -> stays CRITICAL
            (33, "WARNING"),   # 3.3 < 3.4 for clear_s -> drops to WARNING
        ],
    )
    def test_02_hysteresis_critical_boundaries(self, metric_count, expected_after_hold):
        """Req #2b: C=4, h=0.85 -> 3.5 stays CRITICAL, 3.3 (<3.4) for clear_s drops to WARNING."""
        clock = FakeClock(start=0.0)
        eng = _density_engine(smoothing_window=1, clear_s=8.0, hysteresis_ratio=0.85)
        eng.ingest(1, 45, clock.utcnow())  # start in CRITICAL
        assert eng.get_zone_state(1, clock.utcnow())["level"] == "CRITICAL"

        clock.advance(1.0)
        eng.ingest(1, metric_count, clock.utcnow())
        clock.advance(8.0)
        eng.ingest(1, metric_count, clock.utcnow())
        assert eng.get_zone_state(1, clock.utcnow())["level"] == expected_after_hold

    def test_03_critical_to_warning_to_safe_and_direct_paths(self):
        """Req #3: CRITICAL->WARNING->SAFE and CRITICAL->SAFE direct paths with clear_s holds."""
        # Path 1: CRITICAL -> WARNING -> SAFE
        clock = FakeClock(start=0.0)
        eng = _density_engine(smoothing_window=1, clear_s=8.0)
        eng.ingest(1, 45, clock.utcnow())  # CRITICAL

        clock.advance(1.0)
        eng.ingest(1, 30, clock.utcnow())  # 3.0 < 3.4 -> pending WARNING
        clock.advance(7.0)
        eng.ingest(1, 30, clock.utcnow())  # still CRITICAL (<8s)
        assert eng.get_zone_state(1, clock.utcnow())["level"] == "CRITICAL"
        clock.advance(1.0)
        eng.ingest(1, 30, clock.utcnow())  # 8s -> WARNING
        assert eng.get_zone_state(1, clock.utcnow())["level"] == "WARNING"

        clock.advance(1.0)
        eng.ingest(1, 20, clock.utcnow())  # 2.0 < 2.55 -> pending SAFE
        clock.advance(8.0)
        eng.ingest(1, 20, clock.utcnow())
        assert eng.get_zone_state(1, clock.utcnow())["level"] == "SAFE"

        # Path 2: CRITICAL -> SAFE direct
        clock2 = FakeClock(start=0.0)
        eng2 = _density_engine(smoothing_window=1, clear_s=8.0)
        eng2.ingest(1, 45, clock2.utcnow())  # CRITICAL
        clock2.advance(1.0)
        eng2.ingest(1, 10, clock2.utcnow())  # 1.0 < 2.55 -> pending SAFE
        clock2.advance(7.5)
        eng2.ingest(1, 10, clock2.utcnow())
        assert eng2.get_zone_state(1, clock2.utcnow())["level"] == "CRITICAL"
        clock2.advance(0.5)
        eng2.ingest(1, 10, clock2.utcnow())
        assert eng2.get_zone_state(1, clock2.utcnow())["level"] == "SAFE"


class TestMultiSourceAndStale:
    def test_04_two_sources_max_and_partial_stale(self):
        """Req #4: zone metric is MAX (not sum); one stale source doesn't drop fresh source."""
        clock = FakeClock(start=0.0)
        eng = _density_engine(
            smoothing_window=1,
            stale_after_s=10.0,
            debounce_s=0.0,
            clear_s=0.0,
            extra_sources=[SourceConfig(id=2, zone_id=1, coverage_area_m2=10.0)],
        )
        # Source 1: 20 -> 2.0/m² (SAFE), Source 2: 20 -> 2.0/m² (SAFE)
        # Sum would be 4.0 (CRITICAL), MAX is 2.0 (SAFE)
        eng.ingest(1, 20, clock.utcnow())
        eng.ingest(2, 20, clock.utcnow())
        st = eng.get_zone_state(1, clock.utcnow())
        assert st["level"] == "SAFE"
        assert st["density"] == pytest.approx(2.0)

        # Source 1 jumps to 35 (3.5/m² -> WARNING)
        clock.advance(1.0)
        eng.ingest(1, 35, clock.utcnow())
        assert eng.get_zone_state(1, clock.utcnow())["level"] == "WARNING"

        # Advance 11s keeping Source 2 fresh (count=20 -> SAFE) while Source 1 goes stale
        clock.advance(11.0)
        eng.ingest(2, 20, clock.utcnow())
        assert eng.get_source_state(1, clock.utcnow())["status"] == "OFFLINE"
        assert eng.get_source_state(2, clock.utcnow())["status"] == "ONLINE"
        st2 = eng.get_zone_state(1, clock.utcnow())
        assert st2["level"] == "SAFE"  # NOT NO_DATA because source 2 is still fresh

    def test_05_all_sources_stale_becomes_no_data_and_recovers_immediately(self):
        """Req #5: all sources stale -> NO_DATA immediately; recovery applies level immediately."""
        clock = FakeClock(start=0.0)
        eng = _density_engine(smoothing_window=1, debounce_s=5.0, stale_after_s=10.0)
        eng.ingest(1, 10, clock.utcnow())  # SAFE
        assert eng.get_zone_state(1, clock.utcnow())["level"] == "SAFE"

        # At t=10.0 (exactly stale_after_s) still ONLINE/SAFE
        clock.advance(10.0)
        eng.tick(clock.utcnow())
        assert eng.get_zone_state(1, clock.utcnow())["level"] == "SAFE"

        # At t=10.1 (> stale_after_s) -> NO_DATA immediately
        clock.advance(0.1)
        actions = eng.tick(clock.utcnow())
        assert eng.get_zone_state(1, clock.utcnow())["level"] == "NO_DATA"
        assert any(isinstance(a, EmitZoneUpdate) and a.level == "NO_DATA" for a in actions)

        # Recovery at CRITICAL (50/10 = 5.0) -> applied immediately despite debounce_s=5.0
        clock.advance(1.0)
        actions_rec = eng.ingest(1, 50, clock.utcnow())
        assert eng.get_zone_state(1, clock.utcnow())["level"] == "CRITICAL"
        assert any(isinstance(a, CreateAlert) and a.level == "CRITICAL" for a in actions_rec)


class TestAlertLifecycleRules:
    def test_06_alert_created_once_and_reopened_when_acknowledged(self):
        """Req #6: created once; reopened (not duplicated) while ACKNOWLEDGED & condition_active=False."""
        clock = FakeClock(start=0.0)
        eng = _density_engine(smoothing_window=1, debounce_s=3.0, clear_s=8.0)

        eng.ingest(1, 10, clock.utcnow())  # SAFE
        clock.advance(1.0)
        eng.ingest(1, 35, clock.utcnow())
        clock.advance(3.0)
        a1 = eng.ingest(1, 35, clock.utcnow())
        created = [a for a in a1 if isinstance(a, CreateAlert)]
        assert len(created) == 1
        alert_snap = eng.get_open_alert(1)
        assert alert_snap is not None

        # Police acknowledges
        eng.acknowledge_alert(1)
        assert eng.get_open_alert(1).status == "ACKNOWLEDGED"

        # Zone returns to SAFE -> ClearCondition only, alert stays open (ACKNOWLEDGED)
        clock.advance(1.0)
        eng.ingest(1, 10, clock.utcnow())
        clock.advance(8.0)
        a2 = eng.ingest(1, 10, clock.utcnow())
        assert any(isinstance(a, ClearCondition) for a in a2)
        assert not any(isinstance(a, AutoClearAlert) for a in a2)
        assert eng.get_open_alert(1) is not None
        assert eng.get_open_alert(1).condition_active is False

        # Zone re-enters WARNING -> ReopenAlert (NO second CreateAlert)
        clock.advance(1.0)
        eng.ingest(1, 35, clock.utcnow())
        clock.advance(3.0)
        a3 = eng.ingest(1, 35, clock.utcnow())
        assert any(isinstance(a, ReopenAlert) and a.alert_id == alert_snap.id for a in a3)
        assert not any(isinstance(a, CreateAlert) for a in a3)
        assert eng.get_open_alert(1).condition_active is True

    def test_07_escalation_reminder_timing_and_cooldown_suppression(self):
        """Req #7: escalation, reminder timing, WARNING push cooldown suppression."""
        clock = FakeClock(start=0.0)
        eng = _density_engine(
            smoothing_window=1,
            debounce_s=0.0,
            clear_s=0.0,
            cooldown_s=60.0,
            escalation_s=60.0,
        )
        # First WARNING -> CreateAlert + SendPush(WARNING)
        eng.ingest(1, 10, clock.utcnow())  # SAFE
        clock.advance(1.0)
        act_w1 = eng.ingest(1, 35, clock.utcnow())
        assert any(isinstance(a, SendPush) and a.level == "WARNING" for a in act_w1)

        # Back to SAFE -> AutoClearAlert
        clock.advance(1.0)
        eng.ingest(1, 10, clock.utcnow())

        # Re-enter WARNING 10s later (< cooldown 60s) -> CreateAlert, NO SendPush!
        clock.advance(10.0)
        act_w2 = eng.ingest(1, 35, clock.utcnow())
        assert any(isinstance(a, CreateAlert) for a in act_w2)
        assert not any(isinstance(a, SendPush) for a in act_w2)

        # Escalate WARNING -> CRITICAL immediately after -> EscalateAlert + SendPush ALWAYS
        clock.advance(1.0)
        act_esc = eng.ingest(1, 45, clock.utcnow())
        assert any(isinstance(a, EscalateAlert) and a.new_level == "CRITICAL" for a in act_esc)
        assert any(isinstance(a, SendPush) and a.reason == "ESCALATED" for a in act_esc)

        # Tick at +59s -> no reminder yet
        clock.advance(59.0)
        eng.ingest(1, 45, clock.utcnow())  # keep source fresh
        act_59 = eng.tick(clock.utcnow())
        assert not any(isinstance(a, Remind) for a in act_59)

        # Tick at +60s -> Remind + SendPush(REMINDER)
        clock.advance(1.0)
        eng.ingest(1, 45, clock.utcnow())
        act_60 = eng.tick(clock.utcnow())
        assert any(isinstance(a, Remind) for a in act_60)
        assert any(isinstance(a, SendPush) and a.reason == "REMINDER" for a in act_60)

        # Next reminder only after another 60s
        clock.advance(30.0)
        eng.ingest(1, 45, clock.utcnow())
        assert not any(isinstance(a, Remind) for a in eng.tick(clock.utcnow()))
        clock.advance(30.0)
        eng.ingest(1, 45, clock.utcnow())
        assert any(isinstance(a, Remind) for a in eng.tick(clock.utcnow()))

    def test_08_count_mode_w8_c10(self):
        """Req #8: COUNT mode with W=8, C=10."""
        clock = FakeClock(start=0.0)
        eng = ZoneEngine()
        eng.boot(
            [ZoneConfig(id=1, mode="COUNT", warning_count=8, critical_count=10)],
            [SourceConfig(id=1, zone_id=1, coverage_area_m2=100.0)],
            EngineSettings(smoothing_window=1, debounce_s=0.0, clear_s=0.0),
        )
        eng.ingest(1, 7, clock.utcnow())
        assert eng.get_zone_state(1, clock.utcnow())["level"] == "SAFE"
        clock.advance(1.0)
        eng.ingest(1, 8, clock.utcnow())
        assert eng.get_zone_state(1, clock.utcnow())["level"] == "WARNING"
        clock.advance(1.0)
        eng.ingest(1, 10, clock.utcnow())
        assert eng.get_zone_state(1, clock.utcnow())["level"] == "CRITICAL"

    def test_09_trend_rising_falling_steady(self):
        """Req #9: trend over 60 s (+/-0.3 density and +/-2 count)."""
        clock = FakeClock(start=0.0)
        eng = _density_engine(smoothing_window=1)
        eng.ingest(1, 20, clock.utcnow())  # 2.0/m²
        assert eng.get_zone_state(1, clock.utcnow())["trend"] == "STEADY"

        clock.advance(10.0)
        eng.ingest(1, 22, clock.utcnow())  # +0.2 (<0.3) -> STEADY
        assert eng.get_zone_state(1, clock.utcnow())["trend"] == "STEADY"

        clock.advance(10.0)
        eng.ingest(1, 24, clock.utcnow())  # +0.4 over oldest (>=0.3) -> RISING
        assert eng.get_zone_state(1, clock.utcnow())["trend"] == "RISING"

        # Move past 60s window so oldest drops off; now drop by >= 0.3 -> FALLING
        clock.advance(65.0)
        eng.ingest(1, 24, clock.utcnow())
        assert eng.get_zone_state(1, clock.utcnow())["trend"] == "STEADY"
        clock.advance(5.0)
        eng.ingest(1, 20, clock.utcnow())  # -0.4 -> FALLING
        assert eng.get_zone_state(1, clock.utcnow())["trend"] == "FALLING"

        # COUNT mode (+/-2 count)
        zm = ZoneMachine()
        zm.step(5.0, 0.0, warning=8, critical=10, hysteresis_ratio=0.85, debounce_s=0, clear_s=0)
        zm.step(6.0, 10.0, warning=8, critical=10, hysteresis_ratio=0.85, debounce_s=0, clear_s=0)
        assert zm.trend(10.0, "COUNT") == "STEADY"
        zm.step(7.0, 20.0, warning=8, critical=10, hysteresis_ratio=0.85, debounce_s=0, clear_s=0)
        assert zm.trend(20.0, "COUNT") == "RISING"

    def test_10_property_simulated_hour_invariants(self):
        """Req #10: 3600s random counts hold core safety/lifecycle invariants."""
        rng = random.Random(2026)
        clock = FakeClock(start=10_000.0)
        eng = _density_engine(smoothing_window=5, debounce_s=3.0, clear_s=8.0, stale_after_s=10.0)

        prev_level = "NO_DATA"
        open_alert_ids: set[int] = set()
        feed_lost_active = False

        for sec in range(3600):
            clock.advance(1.0)
            actions = []
            # Occasionally simulate an outage gap so NO_DATA & recovery happen too
            if not (600 <= sec <= 625 or 1800 <= sec <= 1820):
                count = rng.choice([5, 15, 28, 33, 38, 45, 55])
                actions.extend(eng.ingest(1, count, clock.utcnow()))
            actions.extend(eng.tick(clock.utcnow()))

            # Inspect actions for invariants
            created_this_step = [a for a in actions if isinstance(a, CreateAlert)]
            auto_cleared_this_step = [a for a in actions if isinstance(a, AutoClearAlert)]
            cleared_this_step = [a for a in actions if isinstance(a, ClearCondition)]
            feed_events = [a for a in actions if isinstance(a, RecordFeedEvent)]

            assert len(created_this_step) <= 1
            assert len(auto_cleared_this_step) <= 1
            assert len(cleared_this_step) <= 1

            for ca in created_this_step:
                # Never two open alerts for one zone
                assert len(open_alert_ids) == 0
                snap = eng.get_open_alert(1)
                if snap is not None:
                    open_alert_ids.add(snap.id)

            if auto_cleared_this_step:
                assert len(open_alert_ids) == 1
                assert auto_cleared_this_step[0].alert_id in open_alert_ids
                open_alert_ids.clear()

            for fe in feed_events:
                if fe.event_type == "FEED_LOST":
                    assert not feed_lost_active, "FEED_LOST emitted twice without restore"
                    feed_lost_active = True
                elif fe.event_type == "FEED_RESTORED":
                    feed_lost_active = False

            cur_level = eng.get_zone_state(1, clock.utcnow())["level"]
            assert cur_level in {"NO_DATA", "SAFE", "WARNING", "CRITICAL"}
            # Every EmitZoneUpdate matches current state
            emits = [a for a in actions if isinstance(a, EmitZoneUpdate)]
            if emits:
                assert emits[-1].level == cur_level

            # Randomly acknowledge or resolve open alerts to exercise all branches
            oa = eng.get_open_alert(1)
            if oa is not None:
                roll = rng.random()
                if roll < 0.02 and oa.status == "NEW":
                    eng.acknowledge_alert(1)
                elif roll < 0.03:
                    eng.resolve_alert(1, clock.utcnow())
                    open_alert_ids.clear()
                    feed_lost_active = False
            prev_level = cur_level

    def test_11_return_from_no_data_with_active_open_alert_and_boot_restart(self):
        """Req #11: returning from NO_DATA with condition_active=True writes FEED_RESTORED, no 2nd alert; boot behaves identically."""
        clock = FakeClock(start=0.0)
        eng = _density_engine(smoothing_window=1, debounce_s=0.0, stale_after_s=10.0)
        eng.ingest(1, 35, clock.utcnow())  # WARNING alert created
        orig_id = eng.get_open_alert(1).id

        # Outage -> NO_DATA (FEED_LOST)
        clock.advance(11.0)
        act_lost = eng.tick(clock.utcnow())
        assert any(isinstance(a, RecordFeedEvent) and a.event_type == "FEED_LOST" for a in act_lost)

        # Return at CRITICAL -> FEED_RESTORED + EscalateAlert, NO CreateAlert
        clock.advance(2.0)
        act_restored = eng.ingest(1, 45, clock.utcnow())
        assert any(isinstance(a, RecordFeedEvent) and a.event_type == "FEED_RESTORED" and a.alert_id == orig_id for a in act_restored)
        assert any(isinstance(a, EscalateAlert) and a.alert_id == orig_id for a in act_restored)
        assert not any(isinstance(a, CreateAlert) for a in act_restored)

        # Simulated restart via boot() with loaded open alert (condition_active=True)
        eng_booted = ZoneEngine()
        boot_alert = OpenAlertSnapshot(
            id=42,
            zone_id=1,
            status="NEW",
            level="WARNING",
            peak_level="WARNING",
            condition_active=True,
            peak_density=3.5,
            peak_count=35.0,
            created_at=clock.utcnow() - timedelta(seconds=30),
        )
        eng_booted.boot(
            [ZoneConfig(id=1, warning_density=3.0, critical_density=4.0)],
            [SourceConfig(id=1, zone_id=1, coverage_area_m2=10.0)],
            EngineSettings(smoothing_window=1),
            open_alerts=[boot_alert],
        )
        clock.advance(1.0)
        act_boot = eng_booted.ingest(1, 36, clock.utcnow())
        assert any(isinstance(a, RecordFeedEvent) and a.event_type == "FEED_RESTORED" and a.alert_id == 42 for a in act_boot)
        assert any(isinstance(a, UpdatePeak) and a.alert_id == 42 for a in act_boot)
        assert not any(isinstance(a, CreateAlert) for a in act_boot)

    def test_12_no_data_while_alert_open_keeps_alert_and_reminders_continue(self):
        """Req #12: NO_DATA keeps alert open, condition_active unchanged, exactly 1 FEED_LOST, reminders continue."""
        clock = FakeClock(start=0.0)
        eng = _density_engine(smoothing_window=1, debounce_s=0.0, stale_after_s=10.0, escalation_s=60.0)
        eng.ingest(1, 45, clock.utcnow())  # CRITICAL alert at t=0
        alert_id = eng.get_open_alert(1).id

        # t=11 -> NO_DATA + 1 FEED_LOST
        clock.advance(11.0)
        a_11 = eng.tick(clock.utcnow())
        assert eng.get_zone_state(1, clock.utcnow())["level"] == "NO_DATA"
        assert [a for a in a_11 if isinstance(a, RecordFeedEvent)] == [
            RecordFeedEvent(alert_id=alert_id, zone_id=1, event_type="FEED_LOST", occurred_at=clock.utcnow())
        ]
        assert eng.get_open_alert(1).condition_active is True

        # t=12 -> no second FEED_LOST
        clock.advance(1.0)
        a_12 = eng.tick(clock.utcnow())
        assert not any(isinstance(a, RecordFeedEvent) for a in a_12)

        # t=60 -> reminder fires even while zone is NO_DATA because condition_active=True
        clock.advance(48.0)
        a_60 = eng.tick(clock.utcnow())
        assert any(isinstance(a, Remind) and a.alert_id == alert_id for a in a_60)
        assert any(isinstance(a, SendPush) and a.reason == "REMINDER" for a in a_60)

    def test_13_critical_peak_new_not_auto_cleared_vs_warning_peak(self):
        """Req #13: CRITICAL-peak NEW stays open on SAFE; WARNING-peak NEW auto-clears."""
        clock = FakeClock(start=0.0)
        eng_w = _density_engine(smoothing_window=1, debounce_s=0.0, clear_s=0.0)
        eng_w.ingest(1, 35, clock.utcnow())  # WARNING-peak NEW
        clock.advance(1.0)
        aw_safe = eng_w.ingest(1, 10, clock.utcnow())
        assert any(isinstance(a, AutoClearAlert) for a in aw_safe)
        assert eng_w.get_open_alert(1) is None

        eng_c = _density_engine(smoothing_window=1, debounce_s=0.0, clear_s=0.0)
        eng_c.ingest(1, 45, clock.utcnow())  # CRITICAL-peak NEW
        clock.advance(1.0)
        ac_safe = eng_c.ingest(1, 10, clock.utcnow())
        assert any(isinstance(a, ClearCondition) for a in ac_safe)
        assert not any(isinstance(a, AutoClearAlert) for a in ac_safe)
        assert eng_c.get_open_alert(1) is not None
        assert eng_c.get_open_alert(1).condition_active is False

        # Reopening at CRITICAL >=60s later emits REOPENED push, NOT an immediate REMINDER on the same tick
        clock.advance(70.0)
        ac_reopen = eng_c.ingest(1, 45, clock.utcnow())
        assert any(isinstance(a, ReopenAlert) for a in ac_reopen)
        assert any(isinstance(a, SendPush) and a.reason == "REOPENED" for a in ac_reopen)
        ac_tick = eng_c.tick(clock.utcnow())
        assert not any(isinstance(a, Remind) for a in ac_tick)

    def test_14_resolve_while_active_reraises_or_noops_if_safe(self):
        """Req #14: resolve while active reraises after reraise_after_s; SAFE meanwhile creates nothing."""
        # Case A: still over limit -> re-raise
        clock = FakeClock(start=0.0)
        eng = _density_engine(smoothing_window=1, debounce_s=0.0, clear_s=0.0, reraise_after_s=60.0)
        eng.ingest(1, 35, clock.utcnow())  # WARNING alert id=1
        aid = eng.get_open_alert(1).id

        clock.advance(5.0)  # t=5
        rs = eng.resolve_alert(1, clock.utcnow())
        assert rs is not None
        assert eng.get_open_alert(1) is None

        # Keep source fresh while still WARNING before t=65
        clock.advance(59.0)  # t=64
        eng.ingest(1, 35, clock.utcnow())
        act_64 = eng.tick(clock.utcnow())
        assert not any(isinstance(a, CreateAlert) for a in act_64)

        # At t=65 (60s after resolve) -> re-raise with previous_alert_id
        clock.advance(1.0)  # t=65
        eng.ingest(1, 35, clock.utcnow())
        act_65 = eng.tick(clock.utcnow())
        assert any(isinstance(a, MarkReraiseChecked) and a.alert_id == aid for a in act_65)
        reraised = [a for a in act_65 if isinstance(a, CreateAlert)]
        assert len(reraised) == 1
        assert reraised[0].reason == "STILL_ACTIVE_AFTER_RESOLVE"
        assert reraised[0].previous_alert_id == aid
        assert any(isinstance(a, SendPush) and a.level == "CRITICAL" and a.reason == "STILL_ACTIVE_AFTER_RESOLVE" for a in act_65)

        # Case B: zone went SAFE before reraise_check_at -> nothing created
        clock2 = FakeClock(start=0.0)
        eng2 = _density_engine(smoothing_window=1, debounce_s=0.0, clear_s=0.0, reraise_after_s=60.0)
        eng2.ingest(1, 35, clock2.utcnow())
        aid2 = eng2.get_open_alert(1).id
        clock2.advance(5.0)
        eng2.resolve_alert(1, clock2.utcnow())
        clock2.advance(10.0)
        eng2.ingest(1, 10, clock2.utcnow())  # now SAFE
        clock2.advance(51.0)  # past reraise_check_at
        eng2.ingest(1, 10, clock2.utcnow())
        act_safe = eng2.tick(clock2.utcnow())
        assert any(isinstance(a, MarkReraiseChecked) and a.alert_id == aid2 for a in act_safe)
        assert not any(isinstance(a, CreateAlert) for a in act_safe)

    def test_15_reload_preserves_buffers_and_no_reminder_when_condition_inactive(self):
        """Req #15: engine.reload() preserves smoothing buffers & levels; no reminder when condition_active=False."""
        clock = FakeClock(start=0.0)
        eng = _density_engine(smoothing_window=5, debounce_s=0.0, clear_s=0.0, escalation_s=60.0)

        # Push counts [45, 45, 45, 45] -> median 45 -> CRITICAL alert
        for _ in range(4):
            clock.advance(1.0)
            eng.ingest(1, 45, clock.utcnow())
        assert eng.get_zone_state(1, clock.utcnow())["level"] == "CRITICAL"

        # Reload changing smoothing_window to 3 & adding zone 2 + source 2
        eng.reload(
            [
                ZoneConfig(id=1, warning_density=3.0, critical_density=4.0),
                ZoneConfig(id=2, warning_density=3.0, critical_density=4.0),
            ],
            [
                SourceConfig(id=1, zone_id=1, coverage_area_m2=10.0),
                SourceConfig(id=2, zone_id=2, coverage_area_m2=10.0),
            ],
            EngineSettings(smoothing_window=3, debounce_s=0.0, clear_s=0.0, escalation_s=60.0),
        )
        # Zone 1 kept its CRITICAL level and smoothed buffer (pushing 1 spike of 0 -> median(45,45,0)=45!)
        assert eng.get_zone_state(1, clock.utcnow())["level"] == "CRITICAL"
        clock.advance(1.0)
        eng.ingest(1, 0, clock.utcnow())
        assert eng.get_zone_state(1, clock.utcnow())["level"] == "CRITICAL"

        # Drop to SAFE -> condition_active becomes False (CRITICAL NEW stays open)
        for _ in range(3):
            clock.advance(1.0)
            eng.ingest(1, 0, clock.utcnow())
        assert eng.get_zone_state(1, clock.utcnow())["level"] == "SAFE"
        assert eng.get_open_alert(1).condition_active is False

        # Advance past escalation_s -> tick sends NO reminder because condition_active=False
        clock.advance(120.0)
        act_tick = eng.tick(clock.utcnow())
        assert not any(isinstance(a, Remind) for a in act_tick)


class TestMiscCoercionAndExternalSnapshots:
    def test_dict_coercion_and_external_snapshots(self):
        clock = FakeClock(start=1000.0)
        now = clock.utcnow()
        oa = coerce_open_alert(
            {
                "id": 9,
                "zone_id": 1,
                "status": "NEW",
                "level": "WARNING",
                "peak_level": "WARNING",
                "condition_active": True,
                "peak_density": 3.1,
                "peak_count": 31.0,
                "created_at": now,
            }
        )
        assert isinstance(oa, OpenAlertSnapshot)
        rr = coerce_resolved_reraise(
            {
                "id": 10,
                "zone_id": 1,
                "resolved_at": now,
                "reraise_check_at": now + timedelta(seconds=60),
            }
        )
        assert isinstance(rr, ResolvedReraiseSnapshot)

        eng = ZoneEngine(auto_commit_alerts=False)
        eng.boot(
            [{"id": 1, "mode": "DENSITY", "warning_density": 3.0, "critical_density": 4.0}],
            [{"id": 1, "zone_id": 1, "coverage_area_m2": 10.0}],
            {"smoothing_window": 1, "debounce_s": 0.0, "clear_s": 0.0},
            open_alerts={1: oa},
            pending_reraises=[rr],
        )
        eng.respond_alert(1)
        eng.set_open_alert(1, oa)
        assert eng.get_source_state(999, now) is None
        assert eng.get_zone_state(999, now) is None
        with pytest.raises(KeyError):
            eng.ingest(999, 1, now)
        clock.advance(1.0)
        actions = eng.ingest(1, 45, clock.utcnow(), reset=True, open_alert=oa)
        assert any(isinstance(a, EscalateAlert) for a in actions)
        eng.set_open_alert(1, None)
        assert eng.get_open_alert(1) is None
