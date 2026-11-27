"""tests/unit/test_detection.py — Unit tests for B3 detection, engine stub, emitter & profiles."""
from __future__ import annotations

import pickle
import sys
from unittest.mock import patch

from app.core.clock import FakeClock
from app.detection.detector import Detector, FakeDetector
from app.detection.protocol import (
    DetectRequest,
    DetectResult,
    Ping,
    Pong,
    ResetSource,
    Shutdown,
)
from app.engine.zone_engine import StubZoneEngine
from app.realtime.emitter import RealtimeEmitter
from scripts.fake_feed import (
    ProfileBounds,
    build_profile_counts,
    compute_profile_bounds,
)


class _DummyZone:
    def __init__(
        self,
        *,
        id: int = 1,
        name: str = "Test Zone",
        mode: str = "DENSITY",
        warning_density: float = 3.0,
        critical_density: float = 4.0,
        warning_count: int | None = None,
        critical_count: int | None = None,
    ) -> None:
        from datetime import datetime, timezone

        self.id = id
        self.name = name
        self.description = ""
        self.geometry_json = (
            '{"type":"Polygon","coordinates":[[[77.209,28.6139],'
            '[77.2094,28.6139],[77.2094,28.6143],[77.209,28.6143],[77.209,28.6139]]]}'
        )
        self.centroid_lat = 28.6141
        self.centroid_lng = 77.2092
        self.area_m2 = 25.0
        self.mode = mode
        self.warning_density = warning_density
        self.critical_density = critical_density
        self.warning_count = warning_count
        self.critical_count = critical_count
        self.is_active = True
        self.created_at = datetime(2026, 11, 27, 0, 0, tzinfo=timezone.utc).replace(tzinfo=None)
        self.updated_at = self.created_at


class _DummySource:
    def __init__(self, id: int = 1, zone_id: int = 1, coverage_area_m2: float = 6.0) -> None:
        self.id = id
        self.zone_id = zone_id
        self.coverage_area_m2 = coverage_area_m2


class TestProtocol:
    def test_dataclasses_pickle_roundtrip(self):
        msgs = [
            DetectRequest(1, 1, b"\xff\xd8\xff", 640, 480, False, 0.35, 640, 123.4),
            DetectResult(1, 1, True, None, [(0.1, 0.2, 0.3, 0.4, 0.9)], 1, 12.5),
            Shutdown(),
            ResetSource(1),
            Ping(),
            Pong(),
        ]
        for msg in msgs:
            restored = pickle.loads(pickle.dumps(msg))
            assert restored == msg

    def test_no_torch_imported(self):
        assert "torch" not in sys.modules


class TestFakeDetector:
    def test_implements_protocol_and_is_deterministic(self):
        d1 = FakeDetector(seed=123, default_count=5)
        d2 = FakeDetector(seed=123, default_count=5)
        assert isinstance(d1, Detector)

        boxes1 = d1.detect(None, source_id=1, conf=0.35, imgsz=640)
        boxes2 = d2.detect(None, source_id=1, conf=0.35, imgsz=640)
        assert len(boxes1) == 5
        assert boxes1 == boxes2

        for x1, y1, x2, y2, c in boxes1:
            assert 0.0 <= x1 < x2 <= 1.0
            assert 0.0 <= y1 < y2 <= 1.0
            assert 0.35 <= c <= 1.0

    def test_configurable_count_per_source(self):
        det = FakeDetector(seed=7, default_count=1)
        det.set_count(source_id=2, count=4)
        assert len(det.detect(None, source_id=1, conf=0.3, imgsz=640)) == 1
        assert len(det.detect(None, source_id=2, conf=0.3, imgsz=640)) == 4


class TestStubZoneEngine:
    def test_density_and_count_modes(self):
        clock = FakeClock(start=1000.0)
        engine = StubZoneEngine()

        # DENSITY mode: coverage 6.0 -> 18 = 3.0 (WARNING), 24 = 4.0 (CRITICAL)
        z_density = {
            "id": 1,
            "mode": "DENSITY",
            "warning_density": 3.0,
            "critical_density": 4.0,
            "warning_count": None,
            "critical_count": None,
        }
        src = {"id": 1, "zone_id": 1, "coverage_area_m2": 6.0}

        st1 = engine.ingest(1, 6, clock.utcnow(), zone_cfg=z_density, source_cfg=src)
        assert st1["level"] == "SAFE"
        assert st1["density"] == 1.0

        clock.advance(1.0)
        st2 = engine.ingest(1, 18, clock.utcnow(), zone_cfg=z_density, source_cfg=src)
        assert st2["level"] == "WARNING"
        assert st2["trend"] == "RISING"

        clock.advance(1.0)
        st3 = engine.ingest(1, 24, clock.utcnow(), zone_cfg=z_density, source_cfg=src)
        assert st3["level"] == "CRITICAL"

        status, last_at = engine.get_source_status(1, clock.utcnow(), stale_after_s=10.0)
        assert status == "ONLINE"
        assert last_at is not None

        # COUNT mode: W=3, C=5
        z_count = {
            "id": 2,
            "mode": "COUNT",
            "warning_density": 3.0,
            "critical_density": 4.0,
            "warning_count": 3,
            "critical_count": 5,
        }
        src2 = {"id": 2, "zone_id": 2, "coverage_area_m2": 25.0}
        assert engine.ingest(2, 2, clock.utcnow(), zone_cfg=z_count, source_cfg=src2)["level"] == "SAFE"
        assert engine.ingest(2, 3, clock.utcnow(), zone_cfg=z_count, source_cfg=src2)["level"] == "WARNING"
        assert engine.ingest(2, 5, clock.utcnow(), zone_cfg=z_count, source_cfg=src2)["level"] == "CRITICAL"


class TestRealtimeEmitterThrottle:
    def test_throttles_same_level_and_trend_within_1s(self):
        clock = FakeClock(start=100.0)
        emitter = RealtimeEmitter(clock=clock, min_interval_s=1.0)
        zone = _DummyZone(id=1)

        emitted: list[tuple[str, str]] = []
        with patch("app.realtime.emitter.socketio.emit", side_effect=lambda ev, p, **kw: emitted.append((ev, kw["to"]))):
            s_safe = {"level": "SAFE", "trend": "STEADY", "density": 0.5, "count": 3.0, "live_updated_at": "2026-11-27T00:01:40Z"}
            assert emitter.emit_zone_update(zone, s_safe) is True
            assert emitter.emit_zone_detail(zone, s_safe, sources=[]) is True

            # Within 0.4s with identical level/trend -> throttled
            clock.advance(0.4)
            assert emitter.emit_zone_update(zone, s_safe) is False
            assert emitter.emit_zone_detail(zone, s_safe, sources=[]) is False

            # Within 0.8s total, but level changes -> immediate emit!
            clock.advance(0.4)
            s_warn = {"level": "WARNING", "trend": "RISING", "density": 3.1, "count": 19.0, "live_updated_at": "2026-11-27T00:01:41Z"}
            assert emitter.emit_zone_update(zone, s_warn) is True
            assert emitter.emit_zone_detail(zone, s_warn, sources=[]) is True

            # Same level/trend after >= 1.0s -> emitted
            clock.advance(1.0)
            assert emitter.emit_zone_update(zone, s_warn) is True
            assert emitter.emit_zone_detail(zone, s_warn, sources=[]) is True

        assert emitted.count(("zone:update", "public")) == 3
        assert emitted.count(("zone:detail", "role:police")) == 3


class TestFakeFeedProfiles:
    def test_bounds_relative_to_mode_and_coverage(self):
        z_cnt = _DummyZone(mode="COUNT", warning_count=3, critical_count=5)
        s_cnt = _DummySource(coverage_area_m2=25.0)
        b_cnt = compute_profile_bounds(z_cnt, s_cnt)
        assert b_cnt.below_warn_count < 3
        assert b_cnt.above_warn_count >= 3
        assert b_cnt.critical_count >= 5
        assert b_cnt.peak_count > 5

        z_den = _DummyZone(mode="DENSITY", warning_density=3.0, critical_density=4.0)
        s_den = _DummySource(coverage_area_m2=6.0)
        b_den = compute_profile_bounds(z_den, s_den)
        assert b_den.below_warn_count < 18
        assert b_den.above_warn_count >= 18
        assert b_den.critical_count >= 24
        assert b_den.peak_count > 24

    def test_profile_shapes(self):
        bounds = ProfileBounds(safe_count=0, below_warn_count=2, above_warn_count=3, critical_count=5, peak_count=7)
        ramp = build_profile_counts("ramp", bounds)
        assert ramp[0] == 0
        assert max(ramp) == 7
        assert ramp[-1] == 0
        assert len(ramp) == 60

        spike = build_profile_counts("spike", bounds)
        assert spike.count(7) == 1
        assert spike[0] == 0 and spike[-1] == 0

        flap = build_profile_counts("flap", bounds)
        assert set(flap) == {2, 3}

        offline = build_profile_counts("offline", bounds)
        assert offline == []
