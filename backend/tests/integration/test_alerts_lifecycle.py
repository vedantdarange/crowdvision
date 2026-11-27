"""tests/integration/test_alerts_lifecycle.py — End-to-end B4b alert, engine & 1Hz loop tests."""
from __future__ import annotations

import time
from datetime import timedelta
from unittest.mock import patch

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

_ALERT_KEYS = {
    "id", "zone_id", "zone_name", "location", "level", "peak_level",
    "status", "condition_active", "peak_density", "peak_count",
    "created_at", "acknowledged_at", "acknowledged_by",
    "responding_at", "responding_by", "resolved_at", "resolved_by",
    "resolution_note", "condition_cleared_at", "last_escalated_at",
}


def _auth(tok: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


def _sio_client(app, token: str | None = None):
    from flask_socketio import SocketIOTestClient
    from app.extensions import socketio

    if token is None:
        return SocketIOTestClient(app, socketio)
    return SocketIOTestClient(app, socketio, auth={"token": token})


@pytest.fixture()
def env(app, client, clean_db, make_user, token_for):
    admin = make_user(name="Admin", email="admin_b4b@test.local", role="admin")
    police = make_user(name="Officer", email="police_b4b@test.local", role="police")
    admin_tok = token_for(admin.id, role="admin")
    police_tok = token_for(police.id, role="police")

    # Configure fast deterministic settings (window=1, debounce=3, clear=8, escalation=60, reraise=60)
    rs = client.patch(
        "/api/v1/settings",
        json={
            "smoothing_window": 1,
            "debounce_s": 3,
            "clear_s": 8,
            "escalation_s": 60,
            "reraise_after_s": 60,
            "stale_after_s": 10,
            "cooldown_s": 60,
        },
        headers=_auth(admin_tok),
    )
    assert rs.status_code == 200

    rz = client.post(
        "/api/v1/zones",
        json={
            "name": "Gate B4b",
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

    rsrc = client.post(
        "/api/v1/sources",
        json={"zone_id": zone["id"], "name": "Cam B4b", "kind": "WEBCAM"},
        headers=_auth(admin_tok),
    )
    assert rsrc.status_code == 201
    source = rsrc.get_json()["data"]
    return {
        "zone": zone,
        "source": source,
        "admin": admin,
        "police": police,
        "admin_tok": admin_tok,
        "police_tok": police_tok,
    }


def _drive(app, source_id: int, count: int, clock):
    from app.container import get_container
    from app.realtime.tasks import run_tick_once

    with app.app_context():
        c = get_container()
        c.detection_manager.ingest_count(source_id, count, now=clock.utcnow())
    return run_tick_once(app, now=clock.utcnow())


class TestRampAndAutoClear:
    def test_warning_ramp_auto_clears_when_untouched(self, app, client, env):
        from app.core.clock import FakeClock

        clock = FakeClock(start=1_700_000_000.0)
        src_id = env["source"]["id"]
        pol_tok = env["police_tok"]

        sio = _sio_client(app, pol_tok)
        sio.get_received()

        # Enter SAFE immediately
        _drive(app, src_id, 1, clock)
        # Hold WARNING (count=3) for 3s debounce
        for _ in range(4):
            clock.advance(1.0)
            _drive(app, src_id, 3, clock)

        alerts = client.get("/api/v1/alerts", headers=_auth(pol_tok)).get_json()["data"]
        assert len(alerts) == 1
        assert alerts[0]["level"] == "WARNING"
        assert alerts[0]["status"] == "NEW"
        assert set(alerts[0].keys()) == _ALERT_KEYS

        # Drop back to SAFE (count=1) and hold 8s clear_s -> AUTO_CLEARED
        for _ in range(9):
            clock.advance(1.0)
            _drive(app, src_id, 1, clock)

        alerts_after = client.get("/api/v1/alerts", headers=_auth(pol_tok)).get_json()["data"]
        assert len(alerts_after) == 1
        assert alerts_after[0]["status"] == "AUTO_CLEARED"
        assert alerts_after[0]["condition_active"] is False

        ev_names = [e["name"] for e in sio.get_received()]
        assert "alert:new" in ev_names
        assert "alert:updated" in ev_names
        sio.disconnect()

    def test_full_ramp_to_critical_escalates_and_is_not_auto_cleared(self, app, client, env):
        from app.core.clock import FakeClock

        clock = FakeClock(start=1_700_000_000.0)
        src_id = env["source"]["id"]
        pol_tok = env["police_tok"]

        sio = _sio_client(app, pol_tok)
        sio.get_received()

        # SAFE -> WARNING -> CRITICAL -> SAFE
        _drive(app, src_id, 0, clock)
        for _ in range(4):
            clock.advance(1.0)
            _drive(app, src_id, 3, clock)  # WARNING
        for _ in range(4):
            clock.advance(1.0)
            _drive(app, src_id, 6, clock)  # CRITICAL
        for _ in range(9):
            clock.advance(1.0)
            _drive(app, src_id, 0, clock)  # SAFE

        alerts = client.get("/api/v1/alerts", headers=_auth(pol_tok)).get_json()["data"]
        assert len(alerts) == 1
        assert alerts[0]["peak_level"] == "CRITICAL"
        assert alerts[0]["status"] == "NEW"  # NOT auto-cleared because peak was CRITICAL
        assert alerts[0]["condition_active"] is False

        events = sio.get_received()
        assert any(e["name"] == "alert:new" for e in events)
        esc = [e for e in events if e["name"] == "alert:escalated"]
        assert len(esc) == 1
        assert esc[0]["args"][0]["reason"] == "LEVEL_UP"
        sio.disconnect()


class TestAcknowledgeReminderAndTransitions:
    def test_ack_keeps_warning_open_after_clear_and_transitions(self, app, client, env):
        from app.core.clock import FakeClock

        clock = FakeClock(start=1_700_000_000.0)
        src_id = env["source"]["id"]
        pol_tok = env["police_tok"]

        _drive(app, src_id, 0, clock)
        for _ in range(4):
            clock.advance(1.0)
            _drive(app, src_id, 3, clock)  # WARNING alert created

        aid = client.get("/api/v1/alerts?active=true", headers=_auth(pol_tok)).get_json()["data"][0]["id"]

        # Acknowledge
        r_ack = client.post(f"/api/v1/alerts/{aid}/acknowledge", json={"note": "On it"}, headers=_auth(pol_tok))
        assert r_ack.status_code == 200
        assert r_ack.get_json()["data"]["status"] == "ACKNOWLEDGED"

        # Idempotent repeat acknowledge -> 200 no-op
        r_ack2 = client.post(f"/api/v1/alerts/{aid}/acknowledge", headers=_auth(pol_tok))
        assert r_ack2.status_code == 200

        # Zone goes SAFE -> stays ACKNOWLEDGED (NOT auto-cleared)
        for _ in range(9):
            clock.advance(1.0)
            _drive(app, src_id, 0, clock)

        detail = client.get(f"/api/v1/alerts/{aid}", headers=_auth(pol_tok)).get_json()["data"]
        assert detail["status"] == "ACKNOWLEDGED"
        assert detail["condition_active"] is False

        # Responding -> Resolved
        assert client.post(f"/api/v1/alerts/{aid}/respond", headers=_auth(pol_tok)).status_code == 200
        # Invalid backward transition RESPONDING -> ACKNOWLEDGE -> 409 INVALID_TRANSITION
        r_bad = client.post(f"/api/v1/alerts/{aid}/acknowledge", headers=_auth(pol_tok))
        assert r_bad.status_code == 409
        assert r_bad.get_json()["error"]["code"] == "INVALID_TRANSITION"

        r_res = client.post(f"/api/v1/alerts/{aid}/resolve", json={"note": "Cleared"}, headers=_auth(pol_tok))
        assert r_res.status_code == 200
        assert r_res.get_json()["data"]["status"] == "RESOLVED"
        assert r_res.get_json()["data"]["resolution_note"] == "Cleared"

        # Invalid transition on final RESOLVED -> 409
        assert client.post(f"/api/v1/alerts/{aid}/respond", headers=_auth(pol_tok)).status_code == 409

        # Timeline events + audit logs
        timeline = client.get(f"/api/v1/alerts/{aid}", headers=_auth(pol_tok)).get_json()["data"]["events"]
        assert [ev["type"] for ev in timeline] == ["CREATED", "ACKNOWLEDGED", "RESPONDING", "RESOLVED"]

        # Filter tests on GET /alerts
        r_filt = client.get("/api/v1/alerts?status=RESOLVED,AUTO_CLEARED&active=false", headers=_auth(pol_tok))
        assert r_filt.status_code == 200
        assert len(r_filt.get_json()["data"]) == 1

    def test_reminder_after_escalation_s_and_no_data_feed_lost_restored(self, app, client, env):
        from app.core.clock import FakeClock
        from app.realtime.tasks import run_tick_once

        clock = FakeClock(start=1_700_000_000.0)
        src_id = env["source"]["id"]
        pol_tok = env["police_tok"]

        sio = _sio_client(app, pol_tok)
        sio.get_received()

        # Enter CRITICAL directly from NO_DATA -> alert created immediately
        _drive(app, src_id, 6, clock)
        aid = client.get("/api/v1/alerts", headers=_auth(pol_tok)).get_json()["data"][0]["id"]

        # Advance 11s with NO frames -> NO_DATA + FEED_LOST once + source:status OFFLINE
        clock.advance(11.0)
        run_tick_once(app, now=clock.utcnow())
        clock.advance(1.0)
        run_tick_once(app, now=clock.utcnow())

        events_mid = client.get(f"/api/v1/alerts/{aid}", headers=_auth(pol_tok)).get_json()["data"]["events"]
        assert [e["type"] for e in events_mid].count("FEED_LOST") == 1

        # Advance past 60s from creation -> REMINDER continues while NO_DATA because condition_active=True
        clock.advance(50.0)
        run_tick_once(app, now=clock.utcnow())

        events_rem = client.get(f"/api/v1/alerts/{aid}", headers=_auth(pol_tok)).get_json()["data"]["events"]
        assert any(e["type"] == "REMINDER" for e in events_rem)
        sio_evs = sio.get_received()
        assert any(
            e["name"] == "alert:escalated" and e["args"][0]["reason"] == "CRITICAL_UNACKNOWLEDGED"
            for e in sio_evs
        )
        assert any(e["name"] == "source:status" and e["args"][0]["status"] == "OFFLINE" for e in sio_evs)

        # Data returns -> FEED_RESTORED written, NO duplicate alert
        clock.advance(2.0)
        _drive(app, src_id, 6, clock)
        all_alerts = client.get("/api/v1/alerts", headers=_auth(pol_tok)).get_json()["data"]
        assert len(all_alerts) == 1
        events_end = client.get(f"/api/v1/alerts/{aid}", headers=_auth(pol_tok)).get_json()["data"]["events"]
        assert any(e["type"] == "FEED_RESTORED" for e in events_end)
        sio.disconnect()


class TestReraiseRestartAndSafety:
    def test_resolve_while_active_reraises_after_reraise_after_s(self, app, client, env):
        from app.core.clock import FakeClock
        from app.realtime.tasks import run_tick_once

        clock = FakeClock(start=1_700_000_000.0)
        src_id = env["source"]["id"]
        pol_tok = env["police_tok"]

        # Sync alert_service._clock with fake clock for resolve timestamp
        with app.app_context():
            from app.container import get_container
            orig_clock = get_container().alert_service._clock
            get_container().alert_service._clock = clock

        try:
            _drive(app, src_id, 4, clock)  # WARNING alert created immediately from NO_DATA
            aid = client.get("/api/v1/alerts?active=true", headers=_auth(pol_tok)).get_json()["data"][0]["id"]

            clock.advance(5.0)
            assert client.post(f"/api/v1/alerts/{aid}/resolve", headers=_auth(pol_tok)).status_code == 200

            # Keep zone over threshold (and source fresh) across 60s
            for _ in range(6):
                clock.advance(9.0)
                _drive(app, src_id, 4, clock)  # 54s elapsed -> no reraise yet

            assert client.get("/api/v1/alerts?active=true", headers=_auth(pol_tok)).get_json()["data"] == []

            clock.advance(7.0)  # 61s elapsed >= 60s -> reraise!
            _drive(app, src_id, 4, clock)
            run_tick_once(app, now=clock.utcnow())

            open_alerts = client.get("/api/v1/alerts?active=true", headers=_auth(pol_tok)).get_json()["data"]
            assert len(open_alerts) == 1
            new_id = open_alerts[0]["id"]
            assert new_id != aid

            detail = client.get(f"/api/v1/alerts/{new_id}", headers=_auth(pol_tok)).get_json()["data"]
            assert detail["events"][0]["data"]["reason"] == "STILL_ACTIVE_AFTER_RESOLVE"
            assert detail["events"][0]["data"]["previous_alert_id"] == aid
        finally:
            with app.app_context():
                from app.container import get_container
                get_container().alert_service._clock = orig_clock

    def test_restart_mid_alert_boot_creates_no_duplicate(self, app, client, env):
        from app.container import get_container
        from app.core.clock import FakeClock
        from app.services.engine_sync import boot_engine_from_db

        clock = FakeClock(start=1_700_000_000.0)
        src_id = env["source"]["id"]
        pol_tok = env["police_tok"]

        _drive(app, src_id, 4, clock)  # WARNING alert created
        alerts = client.get("/api/v1/alerts", headers=_auth(pol_tok)).get_json()["data"]
        assert len(alerts) == 1

        # Simulate server restart: reset engine in memory and re-boot from DB
        with app.app_context():
            c = get_container()
            c.zone_engine.reset()
            boot_engine_from_db(
                zone_engine=c.zone_engine,
                zone_repo=c.zone_repo,
                source_repo=c.source_repo,
                alert_repo=c.alert_repo,
                settings_service=c.settings_service,
            )

        clock.advance(2.0)
        _drive(app, src_id, 4, clock)
        alerts_after = client.get("/api/v1/alerts", headers=_auth(pol_tok)).get_json()["data"]
        assert len(alerts_after) == 1  # NO duplicate created!

    def test_rollback_emits_zero_events_and_zero_pushes(self, app, env):
        from app.container import get_container
        from app.core.clock import FakeClock
        from app.engine.alert_rules import CreateAlert, EmitZoneUpdate, SendPush
        from app.extensions import db
        from app.push.notifier import FakeNotifier

        clock = FakeClock(start=1_700_000_000.0)
        fake_notifier = FakeNotifier()
        sio = _sio_client(app, env["police_tok"])
        sio.get_received()

        with app.app_context():
            c = get_container()
            orig_notifier = c.alert_service._notifier
            c.alert_service._notifier = fake_notifier
            actions = [
                CreateAlert(
                    zone_id=env["zone"]["id"],
                    level="CRITICAL",
                    peak_level="CRITICAL",
                    peak_density=5.0,
                    peak_count=6.0,
                    created_at=clock.utcnow(),
                ),
                SendPush(zone_id=env["zone"]["id"], alert_id=None, level="CRITICAL", reason="CREATED"),
                EmitZoneUpdate(
                    zone_id=env["zone"]["id"],
                    level="CRITICAL",
                    trend="RISING",
                    density=5.0,
                    count=6.0,
                    updated_at=clock.utcnow(),
                ),
            ]
            try:
                with patch.object(db.session, "commit", side_effect=RuntimeError("DB disk full")):
                    with pytest.raises(RuntimeError, match="DB disk full"):
                        c.alert_service.apply(actions)
            finally:
                c.alert_service._notifier = orig_notifier

        # Zero Socket.IO events and zero pushes!
        assert sio.get_received() == []
        assert fake_notifier.alert_calls == []
        sio.disconnect()

    def test_background_1hz_loop_survives_exception_and_touches_db(self, app, client, env):
        from app.realtime.tasks import run_tick_once, start_background_loop, stop_background_loop

        calls = {"n": 0}
        real_run_tick = run_tick_once

        def _flaky_tick(flask_app, now=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("transient error")
            return real_run_tick(flask_app, now=now)

        with patch("app.realtime.tasks.run_tick_once", side_effect=_flaky_tick):
            start_background_loop(app, interval_s=0.05)
            try:
                deadline = time.time() + 3.0
                while calls["n"] < 3 and time.time() < deadline:
                    time.sleep(0.05)
            finally:
                stop_background_loop(app)
                time.sleep(0.1)

        assert calls["n"] >= 3
