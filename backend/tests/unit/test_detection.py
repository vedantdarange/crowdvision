"""tests/unit/test_detection.py — Unit tests for B3 detection, engine stub, emitter & profiles."""
from __future__ import annotations

import pickle
import sys
from unittest.mock import patch

from app.core.clock import FakeClock
from app.detection.detector import Detector, FakeDetector, build_detector
from app.detection.jpeg import MAX_FRAME_BYTES, validate_jpeg_frame
from app.detection.protocol import (
    DetectRequest,
    DetectResult,
    Ping,
    Pong,
    ResetSource,
    SetFakeCount,
    Shutdown,
)
from app.detection.tracker import PassThroughTracker, TrackerHook
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
            DetectRequest(1, 1, b"\xff\xd8\xff", 640, 480, False, 0.35, 640, 123.4, request_id=7),
            DetectResult(1, 1, True, None, [(0.1, 0.2, 0.3, 0.4, 0.9)], 1, 12.5, request_id=7),
            Shutdown(),
            ResetSource(1),
            Ping(ping_id=42),
            Pong(ping_id=42),
        ]
        for msg in msgs:
            restored = pickle.loads(pickle.dumps(msg))
            assert restored == msg

    def test_ping_pong_default_zero(self):
        """ping_id=0 is the initial readiness sentinel; callers always use >0."""
        p0 = Ping()
        p1 = Ping(ping_id=5)
        assert p0.ping_id == 0
        assert p1.ping_id == 5
        assert Pong().ping_id == 0
        assert Pong(ping_id=5).ping_id == 5

    def test_request_id_is_required_with_no_default(self):
        """request_id has no default so callers cannot construct un-correlated requests/results."""
        import pytest

        with pytest.raises(TypeError):
            DetectRequest(1, 1, b"\xff\xd8\xff", 640, 480, False, 0.35, 640, 1.0)  # type: ignore[call-arg]
        with pytest.raises(TypeError):
            DetectResult(1, 1, True, None, [], 0, 1.0)  # type: ignore[call-arg]

        req_explicit = DetectRequest(1, 1, b"\xff\xd8\xff", 640, 480, False, 0.35, 640, 1.0, request_id=99)
        assert req_explicit.request_id == 99
        res = DetectResult(1, 1, True, None, [], 0, 1.0, request_id=99)
        assert res.request_id == 99

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


class TestB5aComponents:
    def test_set_fake_count_pickles_and_ultralytics_raises_not_installed(self):
        import pytest

        msg = SetFakeCount(1, 5)
        assert pickle.loads(pickle.dumps(msg)) == msg
        assert isinstance(build_detector("fake"), FakeDetector)

        with pytest.raises(RuntimeError, match="not installed yet"):
            build_detector("ultralytics")
        with pytest.raises(ValueError):
            build_detector("unknown-backend")

    def test_tracker_hook_and_30s_inactivity_reset(self):
        tracker = PassThroughTracker(inactivity_reset_s=30.0)
        assert isinstance(tracker, TrackerHook)
        boxes = [(0.1, 0.1, 0.2, 0.2, 0.9)]
        assert tracker.update(1, boxes, now_s=100.0) == boxes
        assert tracker.reset_count_by_source.get(1, 0) == 0

        # Explicit reset triggers clear
        tracker.update(1, boxes, now_s=105.0, reset=True)
        assert tracker.reset_count_by_source[1] == 1

        # Gap >= 30s triggers automatic clear
        tracker.update(1, boxes, now_s=135.0)
        assert tracker.reset_count_by_source[1] == 2

        # Gap < 30s does not reset
        tracker.update(1, boxes, now_s=140.0)
        assert tracker.reset_count_by_source[1] == 2

    def test_validate_jpeg_frame_rules(self):
        import pytest
        import struct

        def _jpeg(w: int, h: int, pad: int = 0) -> bytes:
            b = bytearray(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")
            while pad > 0:
                c = min(pad, 60_000)
                b += b"\xff\xfe" + struct.pack(">H", c + 2) + (b"\x00" * c)
                pad -= c
            b += b"\xff\xc0\x00\x0b\x08" + struct.pack(">HH", h, w) + b"\x01\x01\x11\x00\xff\xd9"
            return bytes(b)

        raw = _jpeg(640, 480)
        parsed_bytes, w, h = validate_jpeg_frame(raw, declared_width=640, declared_height=480)
        assert (w, h) == (640, 480) and parsed_bytes == raw

        with pytest.raises(ValueError):
            validate_jpeg_frame(b"\x89PNG\r\n\x1a\n")
        with pytest.raises(ValueError):
            validate_jpeg_frame(_jpeg(1281, 720), declared_width=1281, declared_height=720)
        with pytest.raises(ValueError):
            validate_jpeg_frame(_jpeg(640, 480), declared_width=320, declared_height=480)
        with pytest.raises(ValueError):
            validate_jpeg_frame(_jpeg(640, 480, pad=MAX_FRAME_BYTES))

        # validate_jpeg_frame itself accepts None for declared_width/height (detect_once path).
        # The events.py handler is responsible for rejecting missing/invalid dimensions.
        parsed_bytes2, w2, h2 = validate_jpeg_frame(raw, declared_width=None, declared_height=None)
        assert (w2, h2) == (640, 480)

    def test_worker_loop_uses_raw_count_and_handles_ping_reset_and_once(self):
        import queue
        import threading
        from app.detection.tracker import INACTIVITY_RESET_S
        from app.detection.worker import run_worker

        created_trackers: list[PassThroughTracker] = []

        def _make_tracker() -> PassThroughTracker:
            tr = PassThroughTracker()
            created_trackers.append(tr)
            return tr

        req_q: queue.Queue = queue.Queue()
        res_q: queue.Queue = queue.Queue()
        with patch("app.detection.worker.PassThroughTracker", side_effect=_make_tracker):
            t = threading.Thread(
                target=run_worker,
                kwargs={
                    "request_queue": req_q,
                    "result_queue": res_q,
                    "backend": "fake",
                    "seed": 99,
                    "default_count": 3,
                    "use_tracker": True,
                },
                daemon=True,
            )
            t.start()

            # Initial Pong after warm-up carries ping_id=0 (readiness sentinel)
            init_pong = res_q.get(timeout=2.0)
            assert isinstance(init_pong, Pong)
            assert init_pong.ping_id == 0
            assert len(created_trackers) == 1
            tracker = created_trackers[0]

            # Explicit Ping -> Pong echoes the same ping_id
            req_q.put(Ping(ping_id=7))
            pong = res_q.get(timeout=2.0)
            assert isinstance(pong, Pong)
            assert pong.ping_id == 7

            # Configure source 5 count=4; worker returns raw count=4
            req_q.put(SetFakeCount(5, 4))
            req_q.put(DetectRequest(5, 1, b"\xff\xd8\xff", 640, 480, False, 0.35, 640, 100.0, request_id=1))
            r1 = res_q.get(timeout=2.0)
            assert isinstance(r1, DetectResult) and r1.ok and r1.count == 4 and len(r1.boxes) == 4
            assert r1.request_id == 1  # echoed from request
            assert tracker.reset_count_by_source.get(5, 0) == 0

            # After 30s inactivity gap, worker resets tracker for source 5 automatically
            req_q.put(DetectRequest(5, 2, b"\xff\xd8\xff", 640, 480, False, 0.35, 640, 100.0 + INACTIVITY_RESET_S + 1.0, request_id=2))
            r2 = res_q.get(timeout=2.0)
            assert r2.ok and r2.count == 4
            assert r2.request_id == 2
            assert tracker.reset_count_by_source.get(5, 0) == 1

            # Citizen detect_once uses source_id=-1 (bypasses tracker cleanly)
            req_q.put(DetectRequest(-1, 1, b"\xff\xd8\xff", 0, 0, True, 0.35, 640, 132.0, request_id=3))
            r_once = res_q.get(timeout=2.0)
            assert r_once.source_id == -1 and r_once.ok and r_once.count == 3
            assert r_once.request_id == 3
            assert -1 not in tracker.reset_count_by_source

            # Explicit ResetSource resets tracker again
            req_q.put(ResetSource(5))
            req_q.put(Shutdown())
            t.join(timeout=2.0)
            assert not t.is_alive()
            assert tracker.reset_count_by_source.get(5, 0) == 2

