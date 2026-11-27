"""tests/integration/test_fake_feed.py — Integration tests for B3 fake feed & Socket.IO emission."""
from __future__ import annotations

import threading

import pytest

_SQUARE = {
    "type": "Polygon",
    "coordinates": [[
        [77.2090, 28.6139],
        [77.2094, 28.6139],
        [77.2094, 28.6143],
        [77.2090, 28.6143],
        [77.2090, 28.6139],
    ]],
}

_PUBLIC_ZONE_KEYS = {
    "zone_id", "name", "geometry", "centroid",
    "level", "trend", "density", "updated_at",
}

_FULL_ZONE_KEYS = {
    "id", "name", "description", "geometry", "centroid",
    "area_m2", "mode", "warning_density", "critical_density",
    "warning_count", "critical_count", "is_active",
    "created_at", "updated_at",
    "level", "trend", "count", "density", "sources",
    "open_alert_id", "live_updated_at",
}


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _sio_client(app, token: str | None = None):
    from flask_socketio import SocketIOTestClient
    from app.extensions import socketio

    if token is None:
        return SocketIOTestClient(app, socketio)
    return SocketIOTestClient(app, socketio, auth={"token": token})


@pytest.fixture()
def seeded_density_zone_and_source(client, clean_db, make_user, token_for):
    admin = make_user(name="Admin", email="admin_ff@test.local", role="admin")
    police = make_user(name="Police", email="police_ff@test.local", role="police")
    admin_tok = token_for(admin.id, role="admin")
    police_tok = token_for(police.id, role="police")

    rz = client.post(
        "/api/v1/zones",
        json={
            "name": "FF Exit Lane",
            "geometry": _SQUARE,
            "mode": "DENSITY",
            "warning_density": 3.0,
            "critical_density": 4.0,
        },
        headers=_auth(admin_tok),
    )
    assert rz.status_code == 201
    zone = rz.get_json()["data"]

    rs = client.post(
        "/api/v1/sources",
        json={
            "zone_id": zone["id"],
            "name": "FF Cam",
            "kind": "VIDEO_FILE",
            "coverage_area_m2": 6.0,
        },
        headers=_auth(admin_tok),
    )
    assert rs.status_code == 201
    source = rs.get_json()["data"]
    return zone, source, police_tok


@pytest.fixture()
def seeded_count_zone_and_source(client, clean_db, make_user, token_for):
    admin = make_user(name="AdminC", email="admin_ffc@test.local", role="admin")
    police = make_user(name="PoliceC", email="police_ffc@test.local", role="police")
    admin_tok = token_for(admin.id, role="admin")
    police_tok = token_for(police.id, role="police")

    rz = client.post(
        "/api/v1/zones",
        json={
            "name": "FF Main Gate",
            "geometry": _SQUARE,
            "mode": "COUNT",
            "warning_density": 3.0,
            "critical_density": 4.0,
            "warning_count": 3,
            "critical_count": 5,
        },
        headers=_auth(admin_tok),
    )
    assert rz.status_code == 201
    zone = rz.get_json()["data"]

    rs = client.post(
        "/api/v1/sources",
        json={"zone_id": zone["id"], "name": "FF Gate Cam", "kind": "WEBCAM"},
        headers=_auth(admin_tok),
    )
    assert rs.status_code == 201
    return zone, rs.get_json()["data"], police_tok


class TestFakeFeedRealtime:
    def test_police_receives_zone_detail_and_public_receives_only_public_shape(
        self, app, seeded_density_zone_and_source
    ):
        from app.container import get_container
        from app.core.clock import FakeClock
        from scripts.fake_feed import run_fake_feed

        zone, _, police_tok = seeded_density_zone_and_source

        public_client = _sio_client(app)
        police_client = _sio_client(app, token=police_tok)
        public_client.get_received()  # drain hello
        police_client.get_received()  # drain hello

        fake_clock = FakeClock(start=1_700_000_000.0)

        def _run() -> None:
            with app.app_context():
                c = get_container()
                # Wire deterministic FakeClock to emitter so all ticks emit cleanly
                orig_clock = c.emitter._clock
                c.emitter._clock = fake_clock

                def _tick_sleep(_: float) -> None:
                    fake_clock.advance(1.1)

                try:
                    run_fake_feed(
                        zone_id=zone["id"],
                        profile="ramp",
                        container=c,
                        clock=fake_clock,
                        sleep_fn=_tick_sleep,
                        step_interval_s=1.0,
                    )
                finally:
                    c.emitter._clock = orig_clock

        t = threading.Thread(target=_run)
        t.start()
        t.join(timeout=10.0)
        assert not t.is_alive()

        pub_events = public_client.get_received()
        pol_events = police_client.get_received()

        pub_updates = [e for e in pub_events if e["name"] == "zone:update"]
        pub_details = [e for e in pub_events if e["name"] == "zone:detail"]
        pol_details = [e for e in pol_events if e["name"] == "zone:detail"]

        # Public NEVER receives zone:detail
        assert pub_details == []
        assert len(pub_updates) >= 5
        for ev in pub_updates:
            payload = ev["args"][0]
            assert set(payload.keys()) == _PUBLIC_ZONE_KEYS

        # Police receives zone:detail with full ZoneState shape & level transitions
        assert len(pol_details) >= 5
        levels_seen = set()
        for ev in pol_details:
            payload = ev["args"][0]
            assert set(payload.keys()) == _FULL_ZONE_KEYS
            assert payload["sources"][0]["status"] == "ONLINE"
            assert payload["sources"][0]["last_frame_at"] is not None
            levels_seen.add(payload["level"])

        assert {"SAFE", "WARNING", "CRITICAL"}.issubset(levels_seen)

        public_client.disconnect()
        police_client.disconnect()

    def test_count_mode_ramp_hits_safe_warning_critical(self, app, seeded_count_zone_and_source):
        from app.container import get_container
        from app.core.clock import FakeClock
        from scripts.fake_feed import run_fake_feed

        zone, _, police_tok = seeded_count_zone_and_source
        police_client = _sio_client(app, token=police_tok)
        police_client.get_received()

        fake_clock = FakeClock(start=1_700_000_000.0)
        with app.app_context():
            c = get_container()
            orig_clock = c.emitter._clock
            c.emitter._clock = fake_clock
            try:
                states = run_fake_feed(
                    zone_id=zone["id"],
                    profile="ramp",
                    container=c,
                    clock=fake_clock,
                    sleep_fn=lambda _: fake_clock.advance(1.1),
                )
            finally:
                c.emitter._clock = orig_clock

        levels = [s["level"] for s in states]
        assert levels[0] == "SAFE"
        assert "WARNING" in levels
        assert "CRITICAL" in levels
        assert levels[-1] == "SAFE"

        details = [e for e in police_client.get_received() if e["name"] == "zone:detail"]
        assert len(details) >= 3
        police_client.disconnect()

    def test_throttling_enforced_over_detection_manager(self, app, seeded_density_zone_and_source):
        from app.container import get_container
        from app.core.clock import FakeClock
        from app.detection.detector import FakeDetector
        from scripts.fake_feed import step_fake_feed

        _, source, police_tok = seeded_density_zone_and_source
        police_client = _sio_client(app, token=police_tok)
        police_client.get_received()

        fake_clock = FakeClock(start=500.0)
        detector = FakeDetector(seed=1)

        with app.app_context():
            c = get_container()
            orig_clock = c.emitter._clock
            c.emitter._clock = fake_clock
            try:
                # 5 rapid frames at count=0 (all SAFE + STEADY) 0.2s apart -> total < 1s
                for _ in range(5):
                    step_fake_feed(
                        manager=c.detection_manager,
                        detector=detector,
                        source_id=source["id"],
                        count=0,
                        clock=fake_clock,
                    )
                    fake_clock.advance(0.2)
            finally:
                c.emitter._clock = orig_clock

        details = [e for e in police_client.get_received() if e["name"] == "zone:detail"]
        # First frame at t=500.0 emitted; 500.2, 500.4, 500.6, 500.8 throttled -> only 1 or 2 max
        assert len(details) <= 2
        police_client.disconnect()

    def test_rest_zones_live_reflects_fake_feed(self, app, client, seeded_count_zone_and_source):
        from app.container import get_container
        from app.core.clock import FakeClock
        from app.detection.detector import FakeDetector
        from scripts.fake_feed import step_fake_feed

        zone, source, _ = seeded_count_zone_and_source
        fake_clock = FakeClock(start=1_700_000_000.0)
        detector = FakeDetector(seed=9)
        with app.app_context():
            step_fake_feed(
                manager=get_container().detection_manager,
                detector=detector,
                source_id=source["id"],
                count=5,
                clock=fake_clock,
            )

        r = client.get("/api/v1/zones/live")
        assert r.status_code == 200
        match = [z for z in r.get_json()["data"] if z["zone_id"] == zone["id"]][0]
        assert match["level"] == "CRITICAL"

    def test_cli_fake_feed_profiles(self, app, seeded_count_zone_and_source):
        zone, _, _ = seeded_count_zone_and_source
        runner = app.test_cli_runner()

        for prof in ("spike", "flap", "offline"):
            res = runner.invoke(
                args=["fake-feed", "--zone", str(zone["id"]), "--profile", prof, "--speed", "1000"]
            )
            assert res.exit_code == 0, res.output

        bad = runner.invoke(args=["fake-feed", "--zone", "99999", "--profile", "ramp"])
        assert bad.exit_code != 0
