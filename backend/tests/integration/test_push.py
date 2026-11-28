"""tests/integration/test_push.py — End-to-end B6 Web Push, DB cleanup, /config, and AlertService tests."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pywebpush import WebPushException

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


def _auth(tok: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


def _sub_payload(endpoint: str = "https://push.example.com/sub/1", p256dh: str = "k1", auth: str = "a1"):
    return {
        "endpoint": endpoint,
        "keys": {"p256dh": p256dh, "auth": auth},
    }


@pytest.fixture()
def users(make_user, token_for, clean_db):
    cit = make_user(name="Cit", email="cit_push@test.local", role="citizen")
    pol = make_user(name="Pol", email="pol_push@test.local", role="police")
    adm = make_user(name="Adm", email="adm_push@test.local", role="admin")
    return {
        "cit": cit,
        "pol": pol,
        "adm": adm,
        "cit_tok": token_for(cit.id, role="citizen"),
        "pol_tok": token_for(pol.id, role="police"),
        "adm_tok": token_for(adm.id, role="admin"),
    }


class TestPushEndpointsAndConfig:
    def test_only_police_and_admin_can_subscribe_unsubscribe_and_test(self, client, users):
        body = _sub_payload()

        # Citizen denied on all push endpoints
        assert client.post("/api/v1/push/subscriptions", json=body, headers=_auth(users["cit_tok"])).status_code == 403
        assert (
            client.delete(
                "/api/v1/push/subscriptions?endpoint=https%3A%2F%2Fpush.example.com%2Fsub%2F1",
                headers=_auth(users["cit_tok"]),
            ).status_code
            == 403
        )
        assert client.post("/api/v1/push/test", headers=_auth(users["cit_tok"])).status_code == 403

        # Unauthenticated denied
        assert client.post("/api/v1/push/subscriptions", json=body).status_code == 401
        assert client.post("/api/v1/push/test").status_code == 401

        # Police & Admin allowed
        r_pol = client.post("/api/v1/push/subscriptions", json=body, headers=_auth(users["pol_tok"]))
        assert r_pol.status_code == 201
        sub_id = r_pol.get_json()["data"]["id"]
        assert isinstance(sub_id, int)

        # Upsert same endpoint updates existing row rather than failing uniqueness
        r_adm = client.post(
            "/api/v1/push/subscriptions",
            json=_sub_payload(p256dh="k2", auth="a2"),
            headers=_auth(users["adm_tok"]),
        )
        assert r_adm.status_code == 201
        assert r_adm.get_json()["data"]["id"] == sub_id

        # Delete missing query param -> 422
        assert client.delete("/api/v1/push/subscriptions", headers=_auth(users["adm_tok"])).status_code == 422

        # Delete by endpoint -> 204
        r_del = client.delete(
            "/api/v1/push/subscriptions?endpoint=https%3A%2F%2Fpush.example.com%2Fsub%2F1",
            headers=_auth(users["adm_tok"]),
        )
        assert r_del.status_code == 204

    def test_config_exposes_vapid_public_key_only_when_configured(self, client, clean_db, monkeypatch):
        # Default test env has no VAPID keys -> null
        assert client.get("/api/v1/config").get_json()["data"]["vapid_public_key"] is None

        # App created with VAPID keys -> /config returns vapid_public_key
        monkeypatch.setenv(
            "VAPID_PUBLIC_KEY",
            "BEeKqu0lZHZDzjT0RYt049T2hhIdCka3vglXP4xKDPTcskBAP_2T2SYDzi2XNQyh-jWwrmhwzUmYK0fDST22KA4",
        )
        monkeypatch.setenv("VAPID_PRIVATE_KEY", "ZwTg74Y4VeyGVxxMGCWTcNM43gWxW3NcQB1znWVxs7o")
        monkeypatch.setenv("VAPID_SUBJECT", "mailto:vedmodzyt@gmail.com")

        from app import create_app
        from app.extensions import db

        app_with_keys = create_app(
            config_override={
                "TESTING": True,
                "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                "RATELIMIT_ENABLED": False,
            }
        )
        with app_with_keys.app_context():
            db.create_all()
            with app_with_keys.test_client() as c2:
                pub = c2.get("/api/v1/config").get_json()["data"]["vapid_public_key"]
                assert (
                    pub
                    == "BEeKqu0lZHZDzjT0RYt049T2hhIdCka3vglXP4xKDPTcskBAP_2T2SYDzi2XNQyh-jWwrmhwzUmYK0fDST22KA4"
                )
            db.drop_all()

    def test_push_test_endpoint_returns_number_sent_to_caller_only(self, app, client, users):
        from app.container import get_container
        from app.models.models import PushSubscription
        from app.push.notifier import FakeNotifier, WebPushNotifier

        # Police creates 2 subscriptions; Admin creates 1 subscription
        assert client.post(
            "/api/v1/push/subscriptions",
            json=_sub_payload("https://push.example.com/p/1"),
            headers=_auth(users["pol_tok"]),
        ).status_code == 201
        assert client.post(
            "/api/v1/push/subscriptions",
            json=_sub_payload("https://push.example.com/p/2"),
            headers=_auth(users["pol_tok"]),
        ).status_code == 201
        assert client.post(
            "/api/v1/push/subscriptions",
            json=_sub_payload("https://push.example.com/a/1"),
            headers=_auth(users["adm_tok"]),
        ).status_code == 201

        # 1) With FakeNotifier wired on push_service
        fake = FakeNotifier()
        with app.app_context():
            c = get_container()
            orig_notifier = c.push_service._notifier
            c.push_service._notifier = fake
        try:
            r = client.post("/api/v1/push/test", headers=_auth(users["pol_tok"]))
            assert r.status_code == 200
            assert r.get_json()["data"]["sent"] == 2
            assert len(fake.test_calls) == 1 and len(fake.test_calls[0]) == 2
        finally:
            with app.app_context():
                get_container().push_service._notifier = orig_notifier

        # 2) With real WebPushNotifier + mocked webpush: also test caller scoping & count
        sent_endpoints: list[str] = []

        def fake_webpush(**kwargs):
            sent_endpoints.append(kwargs["subscription_info"]["endpoint"])
            return SimpleNamespace(status_code=201)

        with app.app_context():
            c = get_container()
            orig_notifier = c.push_service._notifier
            wp = WebPushNotifier(
                push_repo=c.push_repo,
                zone_repo=c.zone_repo,
                vapid_private_key="priv",
                vapid_public_key="pub",
                vapid_subject="mailto:vedmodzyt@gmail.com",
                webpush_fn=fake_webpush,
            )
            c.push_service._notifier = wp
        try:
            r_adm = client.post("/api/v1/push/test", headers=_auth(users["adm_tok"]))
            assert r_adm.status_code == 200
            assert r_adm.get_json()["data"]["sent"] == 1
            assert sent_endpoints == ["https://push.example.com/a/1"]
        finally:
            with app.app_context():
                c = get_container()
                c.push_service._notifier = orig_notifier
                assert c.push_repo.get_by_endpoint("https://push.example.com/a/1") is not None


class TestSubscriptionCleanupAndDisabledUsers:
    def test_410_deletes_subscription_immediately(self, app, client, users):
        from app.container import get_container
        from app.models.models import PushSubscription
        from app.push.notifier import WebPushNotifier

        assert client.post(
            "/api/v1/push/subscriptions",
            json=_sub_payload("https://push.example.com/gone-410"),
            headers=_auth(users["pol_tok"]),
        ).status_code == 201

        resp_410 = SimpleNamespace(status_code=410, status=410, text="Gone", headers={})

        def raise_410(**_kwargs):
            raise WebPushException("410 Gone", response=resp_410)

        with app.app_context():
            c = get_container()
            wp = WebPushNotifier(
                push_repo=c.push_repo,
                zone_repo=c.zone_repo,
                vapid_private_key="priv",
                vapid_public_key="pub",
                vapid_subject="mailto:vedmodzyt@gmail.com",
                webpush_fn=raise_410,
            )
            wp.notify_sos({"id": 11, "sos_type": "FIRE", "zone_id": None, "zone_name": None})
            assert c.push_repo.get_by_endpoint("https://push.example.com/gone-410") is None

    def test_five_consecutive_failures_delete_subscription_and_success_resets_counter(self, app, client, users):
        from app.container import get_container
        from app.push.notifier import WebPushNotifier

        ep = "https://push.example.com/flaky"
        assert client.post(
            "/api/v1/push/subscriptions",
            json=_sub_payload(ep),
            headers=_auth(users["pol_tok"]),
        ).status_code == 201

        resp_500 = SimpleNamespace(status_code=500, status=500, text="Error", headers={})
        mode = {"fail": True}

        def fake_webpush(**_kwargs):
            if mode["fail"]:
                raise WebPushException("500 Internal", response=resp_500)
            return SimpleNamespace(status_code=201)

        with app.app_context():
            c = get_container()
            wp = WebPushNotifier(
                push_repo=c.push_repo,
                zone_repo=c.zone_repo,
                vapid_private_key="priv",
                vapid_public_key="pub",
                vapid_subject="mailto:vedmodzyt@gmail.com",
                webpush_fn=fake_webpush,
            )

            # 3 failures -> kept with failure_count == 3
            for _ in range(3):
                wp.notify_sos({"id": 1, "sos_type": "MEDICAL", "zone_id": None, "zone_name": None})
            sub = c.push_repo.get_by_endpoint(ep)
            assert sub is not None
            assert sub.failure_count == 3

            # 1 success -> resets failure_count to 0 and records last_success_at
            mode["fail"] = False
            wp.notify_sos({"id": 2, "sos_type": "MEDICAL", "zone_id": None, "zone_name": None})
            sub = c.push_repo.get_by_endpoint(ep)
            assert sub is not None
            assert sub.failure_count == 0
            assert sub.last_success_at is not None

            # Now 4 failures -> still present (failure_count == 4); 5th deletes it
            mode["fail"] = True
            for expected in range(1, 5):
                wp.notify_sos({"id": 10 + expected, "sos_type": "FIRE", "zone_id": None, "zone_name": None})
                sub = c.push_repo.get_by_endpoint(ep)
                assert sub is not None and sub.failure_count == expected

            wp.notify_sos({"id": 99, "sos_type": "FIRE", "zone_id": None, "zone_name": None})
            assert c.push_repo.get_by_endpoint(ep) is None

    def test_disabled_user_receives_no_pushes(self, app, client, users):
        from app.container import get_container
        from app.extensions import db
        from app.models.models import User
        from app.push.notifier import WebPushNotifier

        assert client.post(
            "/api/v1/push/subscriptions",
            json=_sub_payload("https://push.example.com/pol-disabled"),
            headers=_auth(users["pol_tok"]),
        ).status_code == 201
        assert client.post(
            "/api/v1/push/subscriptions",
            json=_sub_payload("https://push.example.com/adm-active"),
            headers=_auth(users["adm_tok"]),
        ).status_code == 201

        delivered: list[str] = []

        def fake_webpush(**kwargs):
            delivered.append(kwargs["subscription_info"]["endpoint"])
            return SimpleNamespace(status_code=201)

        with app.app_context():
            pol_row = db.session.get(User, users["pol"].id)
            assert pol_row is not None
            pol_row.is_active = False
            db.session.commit()

            c = get_container()
            wp = WebPushNotifier(
                push_repo=c.push_repo,
                zone_repo=c.zone_repo,
                vapid_private_key="priv",
                vapid_public_key="pub",
                vapid_subject="mailto:vedmodzyt@gmail.com",
                webpush_fn=fake_webpush,
            )
            wp.notify_sos({"id": 5, "sos_type": "CRUSH_RISK", "zone_id": None, "zone_name": None})

        assert delivered == ["https://push.example.com/adm-active"]


class TestAlertServicePostCommitPushIntegration:
    def test_alert_lifecycle_triggers_alert_service_notifier_after_commit(self, app, client, users):
        """Drive engine + AlertService.apply with FakeClock & FakeNotifier across create/cooldown/critical/reminder."""
        from app.container import get_container
        from app.core.clock import FakeClock
        from app.push.notifier import FakeNotifier
        from app.realtime.tasks import run_tick_once

        clock = FakeClock(start=1_700_000_000.0)
        fake_notifier = FakeNotifier()

        assert client.patch(
            "/api/v1/settings",
            json={
                "smoothing_window": 1,
                "debounce_s": 0,
                "clear_s": 0,
                "cooldown_s": 60,
                "escalation_s": 60,
                "stale_after_s": 10,
            },
            headers=_auth(users["adm_tok"]),
        ).status_code == 200

        rz = client.post(
            "/api/v1/zones",
            json={
                "name": "Main Gate B6",
                "geometry": _SQUARE,
                "mode": "COUNT",
                "warning_density": 3.0,
                "critical_density": 4.0,
                "warning_count": 3,
                "critical_count": 5,
            },
            headers=_auth(users["adm_tok"]),
        )
        assert rz.status_code == 201
        zone_id = rz.get_json()["data"]["id"]

        rs = client.post(
            "/api/v1/sources",
            json={"zone_id": zone_id, "name": "Cam B6", "kind": "WEBCAM"},
            headers=_auth(users["adm_tok"]),
        )
        assert rs.status_code == 201
        source_id = rs.get_json()["data"]["id"]

        def step(count: int):
            with app.app_context():
                c = get_container()
                c.detection_manager.ingest_count(source_id, count, now=clock.utcnow())
            return run_tick_once(app, now=clock.utcnow())

        with app.app_context():
            c = get_container()
            orig_notifier = c.alert_service._notifier
            orig_clock = c.alert_service._clock
            c.alert_service._notifier = fake_notifier
            c.alert_service._clock = clock
        try:
            step(1)  # SAFE

            # t=1: enter WARNING -> push #1
            clock.advance(1.0)
            step(3)
            assert len(fake_notifier.alert_calls) == 1
            assert fake_notifier.alert_calls[0][1] == "CREATED"
            assert fake_notifier.alert_calls[0][0]["level"] == "WARNING"

            # t=5: clear to SAFE -> auto-clear WARNING
            clock.advance(4.0)
            step(1)

            # t=10 (within 60s WARNING cooldown): WARNING alert created, push SUPPRESSED
            clock.advance(5.0)
            step(3)
            assert len(fake_notifier.alert_calls) == 1

            # t=15: clear again
            clock.advance(5.0)
            step(1)

            # t=20 (still within 60s WARNING cooldown): created AT CRITICAL -> push #2 MUST fire!
            clock.advance(5.0)
            step(6)
            assert len(fake_notifier.alert_calls) == 2
            assert fake_notifier.alert_calls[-1][1] == "CREATED"
            assert fake_notifier.alert_calls[-1][0]["level"] == "CRITICAL"

            # t=80 (60s unacknowledged CRITICAL): REMINDER -> push #3 fires!
            clock.advance(60.0)
            step(6)
            assert len(fake_notifier.alert_calls) == 3
            assert fake_notifier.alert_calls[-1][1] == "REMINDER"

            # t=85: clear to SAFE -> CRITICAL-peak alert stays open with condition_active=False
            clock.advance(5.0)
            step(1)

            # t=90: reopen directly AT CRITICAL -> REOPENED push #4 fires!
            clock.advance(5.0)
            step(6)
            assert len(fake_notifier.alert_calls) == 4
            assert fake_notifier.alert_calls[-1][1] == "REOPENED"
            assert fake_notifier.alert_calls[-1][0]["level"] == "CRITICAL"

            # Clean resolve & verify escalation WARNING -> CRITICAL also pushes
            alert_id = fake_notifier.alert_calls[-1][0]["id"]
            assert (
                client.post(
                    f"/api/v1/alerts/{alert_id}/resolve",
                    json={"note": "clear"},
                    headers=_auth(users["pol_tok"]),
                ).status_code
                == 200
            )
            clock.advance(65.0)
            step(1)  # reraise check skipped because zone is SAFE, then enter WARNING
            clock.advance(5.0)
            step(3)  # WARNING created (cooldown elapsed) -> push #5
            assert len(fake_notifier.alert_calls) == 5
            assert fake_notifier.alert_calls[-1][0]["level"] == "WARNING"
            clock.advance(5.0)
            step(6)  # WARNING -> CRITICAL escalate inside cooldown -> push #6
            assert len(fake_notifier.alert_calls) == 6
            assert fake_notifier.alert_calls[-1][1] == "ESCALATED"
            assert fake_notifier.alert_calls[-1][0]["level"] == "CRITICAL"
        finally:
            with app.app_context():
                c = get_container()
                c.alert_service._notifier = orig_notifier
                c.alert_service._clock = orig_clock


class TestB6AuditFixRegressions:
    def test_held_transport_does_not_block_pump_second_frame_or_tick_loop_and_queue_overflow_drops(
        self, app, client, users, caplog
    ):
        import logging
        import threading
        import time
        from urllib.parse import quote

        from flask_socketio import SocketIOTestClient

        from app.container import get_container
        from app.core.clock import FakeClock
        from app.detection.worker import DetectResult
        from app.extensions import socketio
        from app.push.notifier import WebPushNotifier
        from app.realtime.connect import _lock as sess_lock
        from app.realtime.connect import sessions as sio_sessions
        from app.realtime.tasks import run_tick_once

        assert (
            client.post(
                "/api/v1/push/subscriptions",
                json=_sub_payload("https://push.example.com/held-slow"),
                headers=_auth(users["adm_tok"]),
            ).status_code
            == 201
        )
        assert (
            client.patch(
                "/api/v1/settings",
                json={"smoothing_window": 1, "debounce_s": 0, "clear_s": 0, "escalation_s": 60, "stale_after_s": 10},
                headers=_auth(users["adm_tok"]),
            ).status_code
            == 200
        )
        rz = client.post(
            "/api/v1/zones",
            json={
                "name": "Gate NonBlocking",
                "geometry": _SQUARE,
                "mode": "COUNT",
                "warning_density": 3.0,
                "critical_density": 4.0,
                "warning_count": 3,
                "critical_count": 5,
            },
            headers=_auth(users["adm_tok"]),
        )
        zone_id = rz.get_json()["data"]["id"]
        rs = client.post(
            "/api/v1/sources",
            json={"zone_id": zone_id, "name": "Cam NonBlocking", "kind": "WEBCAM"},
            headers=_auth(users["adm_tok"]),
        )
        source_id = rs.get_json()["data"]["id"]

        clock = FakeClock(start=1_700_000_000.0)
        transport_entered = threading.Event()
        transport_release = threading.Event()
        delivered_kinds: list[str] = []

        def held_webpush(**kwargs):
            payload = json.loads(kwargs["data"])
            delivered_kinds.append(f"{payload['kind']}:{payload.get('level')}")
            transport_entered.set()
            assert transport_release.wait(timeout=5.0)
            return SimpleNamespace(status_code=201)

        sio = SocketIOTestClient(app, socketio, auth={"token": users["adm_tok"]})
        with sess_lock:
            sid = next(iter(sio_sessions.keys()))
        sio.get_received()

        with app.app_context():
            c = get_container()
            orig_notifier = c.alert_service._notifier
            orig_clock = c.alert_service._clock
            orig_dm_clock = c.detection_manager._clock
            wp = WebPushNotifier(
                push_repo=c.push_repo,
                zone_repo=c.zone_repo,
                vapid_private_key="PRIV_SECRET_NEVER_LOG",
                vapid_public_key="PUB_KEY",
                vapid_subject="mailto:vedmodzyt@gmail.com",
                clock=clock,
                max_queue_size=1,
                flask_app=app,
                webpush_fn=held_webpush,
            )
            wp.start(app)
            c.alert_service._notifier = wp
            c.alert_service._clock = clock
            c.detection_manager._clock = clock
            dm = c.detection_manager
            with dm._pipeline_lock:
                dm._leases[source_id] = (sid, time.monotonic())
                dm._inflight[101] = (sid, source_id, 1, False, time.monotonic())
                dm._inflight[102] = (sid, source_id, 2, False, time.monotonic())

        try:
            # 1) Frame 1 triggers CRITICAL alert + holds transport open
            t0 = time.monotonic()
            with app.app_context():
                get_container().detection_manager._handle_worker_item(
                    DetectResult(
                        source_id=source_id,
                        seq=1,
                        ok=True,
                        error=None,
                        count=6,
                        boxes=[],
                        infer_ms=8.0,
                        request_id=101,
                    )
                )
            assert (time.monotonic() - t0) < 0.5
            assert transport_entered.wait(timeout=2.0)

            events_1 = sio.get_received()
            assert any(e["name"] == "alert:new" for e in events_1)
            assert any(e["name"] == "frame:result" and e["args"][0]["seq"] == 1 for e in events_1)

            # 2) While push #1 is STILL held open, frame 2 completes promptly
            with app.app_context():
                get_container().detection_manager._handle_worker_item(
                    DetectResult(
                        source_id=source_id,
                        seq=2,
                        ok=True,
                        error=None,
                        count=6,
                        boxes=[],
                        infer_ms=7.0,
                        request_id=102,
                    )
                )
            events_2 = sio.get_received()
            assert any(e["name"] == "frame:result" and e["args"][0]["seq"] == 2 for e in events_2)

            # 3) Advance clock past escalation_s -> tick dispatches REMINDER (#2 fills queue maxsize=1),
            #    and next scheduled tick still returns promptly! Also overflow (#3) drops cleanly.
            clock.advance(61.0)
            with app.app_context():
                get_container().detection_manager.ingest_count(source_id, 6, now=clock.utcnow())
            t_tick1 = time.monotonic()
            run_tick_once(app, now=clock.utcnow())
            assert (time.monotonic() - t_tick1) < 0.5

            with caplog.at_level(logging.WARNING):
                wp.notify_sos({"id": 77, "sos_type": "FIRE", "zone_id": zone_id, "zone_name": "Gate NonBlocking"})
                clock.advance(1.0)
                t_tick2 = time.monotonic()
                run_tick_once(app, now=clock.utcnow())
                assert (time.monotonic() - t_tick2) < 0.5

            assert wp.dropped_count >= 1
            log_blob = "\n".join(rec.getMessage() + " " + repr(rec.__dict__) for rec in caplog.records)
            assert "Web Push dispatch queue full" in log_blob
            assert "PRIV_SECRET_NEVER_LOG" not in log_blob
            assert "held-slow" not in log_blob

            # Release held transport & drain cleanly
            transport_release.set()
            assert wp.flush(timeout=3.0)
            wp.stop(timeout=2.0)
            assert len(delivered_kinds) >= 2
        finally:
            sio.disconnect()
            transport_release.set()
            with app.app_context():
                c = get_container()
                wp.stop(timeout=2.0)
                c.alert_service._notifier = orig_notifier
                c.alert_service._clock = orig_clock
                c.detection_manager._clock = orig_dm_clock

    def test_delete_encoded_endpoint_with_percent_sequences_owner_only(self, app, client, users):
        from urllib.parse import quote

        from app.container import get_container

        encoded_ep = "https://push.example.com/v1/sub/abc%2Bdef%3D"
        r_sub = client.post(
            "/api/v1/push/subscriptions",
            json=_sub_payload(encoded_ep),
            headers=_auth(users["pol_tok"]),
        )
        assert r_sub.status_code == 201

        q_ep = quote(encoded_ep, safe="")
        # Another officer (admin) cannot delete police owner's encoded endpoint
        assert client.delete(f"/api/v1/push/subscriptions?endpoint={q_ep}", headers=_auth(users["adm_tok"])).status_code == 204
        with app.app_context():
            assert get_container().push_repo.get_by_endpoint(encoded_ep) is not None

        # Owner deletes their own endpoint containing literal %2B and %3D
        assert client.delete(f"/api/v1/push/subscriptions?endpoint={q_ep}", headers=_auth(users["pol_tok"])).status_code == 204
        with app.app_context():
            assert get_container().push_repo.get_by_endpoint(encoded_ep) is None

    def test_stale_delayed_410_after_reregistration_preserves_refreshed_subscription(self, app, client, users):
        import threading

        from app.container import get_container
        from app.push.notifier import WebPushNotifier

        ep = "https://push.example.com/refresh-race-rev"
        r1 = client.post(
            "/api/v1/push/subscriptions",
            json=_sub_payload(ep, p256dh="OLD_KEY", auth="OLD_AUTH"),
            headers=_auth(users["pol_tok"]),
        )
        assert r1.status_code == 201
        sub_id = r1.get_json()["data"]["id"]
        with app.app_context():
            row1 = get_container().push_repo.get_by_endpoint(ep)
            assert row1 is not None and row1.revision == 1

        started = threading.Event()
        release = threading.Event()
        resp_410 = SimpleNamespace(status_code=410, status=410, text="Gone", headers={})

        def delayed_410(**_kwargs):
            started.set()
            assert release.wait(timeout=5.0)
            raise WebPushException("410 Gone", response=resp_410)

        def send_stale():
            with app.app_context():
                c = get_container()
                wp = WebPushNotifier(
                    push_repo=c.push_repo,
                    zone_repo=c.zone_repo,
                    vapid_private_key="priv",
                    vapid_public_key="pub",
                    vapid_subject="mailto:vedmodzyt@gmail.com",
                    webpush_fn=delayed_410,
                )
                wp.notify_sos({"id": 501, "sos_type": "FIRE", "zone_id": None, "zone_name": None})

        t = threading.Thread(target=send_stale)
        t.start()
        assert started.wait(timeout=2.0)

        # Re-register on the SAME endpoint (same row ID, new revision == 2)
        r2 = client.post(
            "/api/v1/push/subscriptions",
            json=_sub_payload(ep, p256dh="NEW_KEY", auth="NEW_AUTH"),
            headers=_auth(users["pol_tok"]),
        )
        assert r2.status_code == 201
        assert r2.get_json()["data"]["id"] == sub_id

        release.set()
        t.join(timeout=3.0)

        with app.app_context():
            row2 = get_container().push_repo.get_by_endpoint(ep)
            assert row2 is not None
            assert row2.id == sub_id
            assert row2.revision == 2
            assert row2.p256dh == "NEW_KEY"
            assert row2.failure_count == 0

    def test_config_and_notifier_consistent_on_blank_keys_and_invalid_subject(
        self, clean_db, monkeypatch, capsys
    ):
        from flask_jwt_extended import create_access_token

        from app import create_app
        from app.extensions import db
        from app.models.models import User

        cases = [
            ("   ", "   ", "mailto:vedmodzyt@gmail.com", "not configured"),
            ("PUB_SECRET_12345", "", "mailto:vedmodzyt@gmail.com", "Incomplete"),
            ("PUB_SECRET_12345", "PRIV_SECRET_12345", "mailto:localhost", "VAPID_SUBJECT"),
        ]
        for pub, priv, subj, expected_reason in cases:
            monkeypatch.setenv("VAPID_PUBLIC_KEY", pub)
            monkeypatch.setenv("VAPID_PRIVATE_KEY", priv)
            monkeypatch.setenv("VAPID_SUBJECT", subj)
            capsys.readouterr()
            app_case = create_app(
                config_override={
                    "TESTING": True,
                    "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                    "RATELIMIT_ENABLED": False,
                }
            )
            with app_case.app_context():
                db.create_all()
                from app.core.time import utcnow
                from argon2 import PasswordHasher

                pol = User(
                    name="PolCfg",
                    email="pol_cfg@test.local",
                    password_hash=PasswordHasher().hash("Pass@1234"),
                    role="police",
                    is_active=True,
                    created_at=utcnow().replace(tzinfo=None),
                    updated_at=utcnow().replace(tzinfo=None),
                )
                db.session.add(pol)
                db.session.commit()
                tok = create_access_token(identity=str(pol.id), additional_claims={"role": "police"})
                cnt = app_case.extensions["container"]
                assert cnt.notifier.is_configured is False
                with app_case.test_client() as tc:
                    cfg_resp = tc.get("/api/v1/config")
                    assert cfg_resp.status_code == 200
                    assert cfg_resp.get_json()["data"]["vapid_public_key"] is None
                    test_resp = tc.post("/api/v1/push/test", headers=_auth(tok))
                    assert test_resp.status_code == 200
                    assert test_resp.get_json()["data"]["sent"] == 0
                db.drop_all()
            captured = capsys.readouterr()
            log_blob = captured.out + "\n" + captured.err
            assert expected_reason in log_blob
            assert "PUB_SECRET_12345" not in log_blob
            assert "PRIV_SECRET_12345" not in log_blob
