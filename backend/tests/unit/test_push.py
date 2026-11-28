"""tests/unit/test_push.py — Unit tests for B6 Web Push payloads, cooldowns, and delivery rules."""
from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pywebpush import WebPushException

from app.core.clock import FakeClock
from app.engine.alert_rules import CreateAlert, SendPush
from app.engine.zone_engine import EngineSettings, SourceConfig, ZoneConfig, ZoneEngine
from app.push.notifier import (
    FakeNotifier,
    WebPushNotifier,
    build_alert_payload,
    build_sos_payload,
    is_valid_vapid_subject,
    resolve_push_config,
)


def _engine(
    *,
    cooldown_s: float = 60.0,
    escalation_s: float = 60.0,
    warning_density: float = 3.0,
    critical_density: float = 4.0,
) -> ZoneEngine:
    eng = ZoneEngine()
    eng.boot(
        [
            ZoneConfig(
                id=1,
                mode="DENSITY",
                warning_density=warning_density,
                critical_density=critical_density,
            )
        ],
        [SourceConfig(id=1, zone_id=1, coverage_area_m2=10.0)],
        EngineSettings(
            smoothing_window=1,
            debounce_s=0.0,
            clear_s=0.0,
            hysteresis_ratio=0.85,
            stale_after_s=10.0,
            cooldown_s=cooldown_s,
            escalation_s=escalation_s,
            reraise_after_s=60.0,
        ),
    )
    return eng


def _dispatch_fake(notifier: FakeNotifier, actions, *, zone_name: str = "Main Gate") -> None:
    alert_id = 100
    for act in actions:
        if isinstance(act, SendPush):
            aid = act.alert_id if act.alert_id is not None else alert_id
            payload = {
                "id": aid,
                "zone_id": act.zone_id,
                "zone_name": zone_name,
                "level": act.level,
                "peak_level": act.level,
                "peak_density": 4.2 if act.level == "CRITICAL" else 3.3,
                "peak_count": 42.0 if act.level == "CRITICAL" else 33.0,
            }
            notifier.notify_alert(payload, act.reason)


class TestPayloadShapesAndValidation:
    def test_alert_payload_matches_contract_section_9_density_and_count(self):
        alert = {
            "id": 12,
            "zone_id": 3,
            "zone_name": "Main Gate",
            "level": "CRITICAL",
            "peak_density": 4.6,
            "peak_count": 28.0,
        }
        density_payload = build_alert_payload(alert, "CREATED", zone_mode="DENSITY")
        assert set(density_payload.keys()) == {
            "kind",
            "title",
            "body",
            "url",
            "tag",
            "level",
            "alert_id",
            "zone_id",
        }
        assert density_payload["kind"] == "ALERT"
        assert density_payload["title"] == "CRITICAL — Main Gate"
        assert "4.6 people/m²" in density_payload["body"]
        assert density_payload["url"] == "/police/alerts/12"
        assert density_payload["tag"] == "alert-12"
        assert density_payload["level"] == "CRITICAL"
        assert density_payload["alert_id"] == 12
        assert density_payload["zone_id"] == 3

        count_payload = build_alert_payload(alert, "CREATED", zone_mode="COUNT")
        assert "28 people" in count_payload["body"]
        assert count_payload["url"] == "/police/alerts/12"
        assert count_payload["tag"] == "alert-12"

    @pytest.mark.parametrize(
        "sos_type,expected_title",
        [
            ("CRUSH_RISK", "SOS — Crush risk"),
            ("FIRE", "SOS — Fire"),
            ("MEDICAL", "SOS — Medical"),
        ],
    )
    def test_sos_payload_matches_contract_for_urgent_types(self, sos_type, expected_title):
        report = {
            "id": 45,
            "sos_type": sos_type,
            "zone_id": 3,
            "zone_name": "Main Gate",
        }
        payload = build_sos_payload(report)
        assert payload is not None
        assert set(payload.keys()) == {
            "kind",
            "title",
            "body",
            "url",
            "tag",
            "level",
            "report_id",
            "zone_id",
        }
        assert payload == {
            "kind": "SOS",
            "title": expected_title,
            "body": "Reported near Main Gate. Tap to review.",
            "url": "/police/reports?focus=45",
            "tag": "sos-45",
            "level": "CRITICAL",
            "report_id": 45,
            "zone_id": 3,
        }

        no_zone_payload = build_sos_payload({"id": 46, "sos_type": sos_type, "zone_id": None, "zone_name": None})
        assert no_zone_payload is not None
        assert no_zone_payload["zone_id"] is None
        assert no_zone_payload["url"] == "/police/reports?focus=46"
        assert no_zone_payload["tag"] == "sos-46"

    @pytest.mark.parametrize("ignored_type", ["LOST_CHILD", "OTHER", None])
    def test_sos_payload_returns_none_for_in_app_only_types(self, ignored_type):
        assert build_sos_payload({"id": 9, "sos_type": ignored_type, "zone_id": 1}) is None

    def test_vapid_subject_validation(self, caplog):
        assert is_valid_vapid_subject("mailto:vedmodzyt@gmail.com") is True
        assert is_valid_vapid_subject("you@example.com") is False
        assert is_valid_vapid_subject("mailto:localhost") is False
        assert is_valid_vapid_subject("https://example.com") is False

        cfg_ws = resolve_push_config(
            vapid_public_key="   ",
            vapid_private_key="   ",
            vapid_subject="mailto:vedmodzyt@gmail.com",
        )
        assert cfg_ws.enabled is False
        assert cfg_ws.public_key is None

        cfg_bad = resolve_push_config(
            vapid_public_key="pub",
            vapid_private_key="priv",
            vapid_subject="mailto:localhost",
        )
        assert cfg_bad.enabled is False
        assert cfg_bad.public_key is None
        assert "VAPID_SUBJECT" in (cfg_bad.reason or "")

        mock_repo = MagicMock()
        with caplog.at_level(logging.WARNING):
            notifier = WebPushNotifier(
                push_repo=mock_repo,
                vapid_private_key="SECRET_PRIV_KEY_DO_NOT_LOG",
                vapid_public_key="SECRET_PUB_KEY_DO_NOT_LOG",
                vapid_subject="mailto:localhost",
            )
        assert notifier.is_configured is False
        log_blob = "\n".join(rec.getMessage() for rec in caplog.records)
        assert "VAPID_SUBJECT" in log_blob
        assert "SECRET_PRIV_KEY_DO_NOT_LOG" not in log_blob
        assert "SECRET_PUB_KEY_DO_NOT_LOG" not in log_blob


class TestCooldownAndReminderRules:
    def test_warning_suppressed_within_cooldown_and_critical_always_pushes(self):
        """With FakeClock + FakeNotifier: WARNING cooldown suppresses repeat WARNINGs,
        while CRITICAL creation, escalation, reopen at CRITICAL, and reminders always send."""
        clock = FakeClock(start=1_700_000_000.0)
        notifier = FakeNotifier()
        eng = _engine(cooldown_s=60.0, escalation_s=60.0)

        # Enter SAFE first
        eng.ingest(1, 10, clock.utcnow())

        # t=1: enter WARNING -> pushes once
        clock.advance(1.0)
        _dispatch_fake(notifier, eng.ingest(1, 35, clock.utcnow()))
        assert len(notifier.alert_calls) == 1
        assert notifier.alert_calls[-1][0]["level"] == "WARNING"
        assert notifier.alert_calls[-1][1] == "CREATED"

        # t=10: drop to SAFE (auto-clears WARNING alert)
        clock.advance(9.0)
        eng.ingest(1, 10, clock.utcnow())
        assert eng.get_open_alert(1) is None

        # t=20 (within 60s cooldown): enter WARNING again -> alert created, push SUPPRESSED
        clock.advance(10.0)
        act_warn_2 = eng.ingest(1, 35, clock.utcnow())
        assert any(isinstance(a, CreateAlert) for a in act_warn_2)
        assert not any(isinstance(a, SendPush) for a in act_warn_2)
        _dispatch_fake(notifier, act_warn_2)
        assert len(notifier.alert_calls) == 1

        # t=70 (69s after first WARNING push >= 60s): clear & re-enter WARNING -> pushes again
        clock.advance(25.0)
        eng.ingest(1, 10, clock.utcnow())
        clock.advance(25.0)
        _dispatch_fake(notifier, eng.ingest(1, 35, clock.utcnow()))
        assert len(notifier.alert_calls) == 2
        assert notifier.alert_calls[-1][0]["level"] == "WARNING"

        # t=80 (inside WARNING cooldown from t=70): escalate WARNING -> CRITICAL -> ALWAYS pushes
        clock.advance(10.0)
        _dispatch_fake(notifier, eng.ingest(1, 45, clock.utcnow()))
        assert len(notifier.alert_calls) == 3
        assert notifier.alert_calls[-1][0]["level"] == "CRITICAL"
        assert notifier.alert_calls[-1][1] == "ESCALATED"

        # t=140 (60s unacknowledged CRITICAL): REMINDER always pushes
        clock.advance(60.0)
        eng.ingest(1, 45, clock.utcnow())  # keep source fresh before tick
        _dispatch_fake(notifier, eng.tick(clock.utcnow()))
        assert len(notifier.alert_calls) == 4
        assert notifier.alert_calls[-1][0]["level"] == "CRITICAL"
        assert notifier.alert_calls[-1][1] == "REMINDER"

    def test_alert_created_at_critical_pushes_even_inside_warning_cooldown(self):
        clock = FakeClock(start=2_000_000_000.0)
        notifier = FakeNotifier()
        eng = _engine(cooldown_s=120.0)

        eng.ingest(1, 10, clock.utcnow())  # SAFE

        # t=1: WARNING push -> starts 120s WARNING cooldown
        clock.advance(1.0)
        _dispatch_fake(notifier, eng.ingest(1, 35, clock.utcnow()))
        assert len(notifier.alert_calls) == 1

        # t=5: back to SAFE -> auto-clears
        clock.advance(4.0)
        eng.ingest(1, 10, clock.utcnow())
        assert eng.get_open_alert(1) is None

        # t=10 (well inside 120s WARNING cooldown): spike straight to CRITICAL -> MUST push!
        clock.advance(5.0)
        act_crit = eng.ingest(1, 45, clock.utcnow())
        assert any(isinstance(a, CreateAlert) and a.level == "CRITICAL" for a in act_crit)
        _dispatch_fake(notifier, act_crit)
        assert len(notifier.alert_calls) == 2
        assert notifier.alert_calls[-1][0]["level"] == "CRITICAL"
        assert notifier.alert_calls[-1][1] == "CREATED"


class TestWebPushNotifierDelivery:
    def _sub(self, sub_id: int, suffix: str):
        return SimpleNamespace(
            id=sub_id,
            endpoint=f"https://fcm.googleapis.com/fcm/send/secret-token-{suffix}",
            p256dh=f"secret-p256dh-{suffix}",
            auth=f"secret-auth-{suffix}",
        )

    def test_fresh_vapid_claims_dict_per_call_and_headers_ttl(self):
        clock = FakeClock(start=1_700_000_000.0)
        subs = [self._sub(1, "one"), self._sub(2, "two")]
        push_repo = MagicMock()
        push_repo.list_active_police_subscriptions.return_value = subs

        recorded_claims: list[dict] = []
        recorded_claims_ids: list[int] = []
        recorded_kwargs: list[dict] = []

        def fake_webpush(**kwargs):
            claims = kwargs["vapid_claims"]
            recorded_claims_ids.append(id(claims))
            # Snapshot before mutating to prove input was clean {"sub": ...}
            recorded_claims.append(dict(claims))
            # Emulate pywebpush mutating vapid_claims in place
            claims["aud"] = "https://mutated-in-place.example"
            claims["exp"] = 9999999999
            recorded_kwargs.append(kwargs)

        notifier = WebPushNotifier(
            push_repo=push_repo,
            vapid_private_key="priv-key",
            vapid_public_key="pub-key",
            vapid_subject="mailto:vedmodzyt@gmail.com",
            clock=clock,
            webpush_fn=fake_webpush,
        )

        notifier.notify_sos(
            {"id": 7, "sos_type": "FIRE", "zone_id": 2, "zone_name": "Stage Area"}
        )

        assert len(recorded_claims) == 2
        assert recorded_claims_ids[0] != recorded_claims_ids[1]
        assert recorded_claims == [
            {"sub": "mailto:vedmodzyt@gmail.com"},
            {"sub": "mailto:vedmodzyt@gmail.com"},
        ]
        for kw in recorded_kwargs:
            assert kw["ttl"] == 600
            assert kw["headers"] == {"Urgency": "high"}
            assert kw["timeout"] == 5.0
            body = json.loads(kw["data"])
            assert body["kind"] == "SOS"
            assert body["report_id"] == 7

        outcomes = push_repo.record_delivery_results.call_args[0][0]
        assert sorted(outcomes) == [(1, 1, "ok"), (2, 1, "ok")]

    def test_notify_sos_filters_types_and_never_logs_secrets(self, caplog):
        push_repo = MagicMock()
        push_repo.list_active_police_subscriptions.return_value = [self._sub(10, "xyz")]
        fake_webpush = MagicMock()

        notifier = WebPushNotifier(
            push_repo=push_repo,
            vapid_private_key="TOP_SECRET_VAPID_PRIV",
            vapid_public_key="pub-key",
            vapid_subject="mailto:vedmodzyt@gmail.com",
            webpush_fn=fake_webpush,
        )

        with caplog.at_level(logging.INFO):
            for allowed in ("CRUSH_RISK", "FIRE", "MEDICAL"):
                notifier.notify_sos({"id": 1, "sos_type": allowed, "zone_id": 1, "zone_name": "Gate"})
            assert fake_webpush.call_count == 3

            fake_webpush.reset_mock()
            for ignored in ("LOST_CHILD", "OTHER"):
                notifier.notify_sos({"id": 2, "sos_type": ignored, "zone_id": 1, "zone_name": "Gate"})
            assert fake_webpush.call_count == 0

            # FakeNotifier enforces the exact same filter
            fn = FakeNotifier()
            fn.notify_sos({"id": 3, "sos_type": "FIRE", "zone_id": 1})
            fn.notify_sos({"id": 4, "sos_type": "LOST_CHILD", "zone_id": 1})
            fn.notify_sos({"id": 5, "sos_type": "OTHER", "zone_id": 1})
            assert len(fn.sos_calls) == 1
            assert fn.sos_calls[0]["id"] == 3

        log_blob = "\n".join(rec.getMessage() + " " + repr(rec.__dict__) for rec in caplog.records)
        assert "secret-token-xyz" not in log_blob
        assert "secret-p256dh-xyz" not in log_blob
        assert "secret-auth-xyz" not in log_blob
        assert "TOP_SECRET_VAPID_PRIV" not in log_blob

    def test_one_failing_or_gone_endpoint_does_not_block_other_endpoints(self):
        subs = [self._sub(1, "gone"), self._sub(2, "slowerr"), self._sub(3, "ok")]
        push_repo = MagicMock()
        push_repo.list_active_police_subscriptions.return_value = subs

        resp_410 = SimpleNamespace(status_code=410, status=410, text="Gone", headers={})

        def fake_webpush(**kwargs):
            ep = kwargs["subscription_info"]["endpoint"]
            if ep.endswith("gone"):
                raise WebPushException("410 Gone", response=resp_410)
            if ep.endswith("slowerr"):
                raise TimeoutError("timed out")
            return SimpleNamespace(status_code=201)

        notifier = WebPushNotifier(
            push_repo=push_repo,
            vapid_private_key="priv",
            vapid_public_key="pub",
            vapid_subject="mailto:vedmodzyt@gmail.com",
            webpush_fn=fake_webpush,
        )

        sent = notifier.send_test(subs)
        assert sent == 1
        outcomes = {(sub_id, rev): st for sub_id, rev, st in push_repo.record_delivery_results.call_args[0][0]}
        assert outcomes == {(1, 1): "gone", (2, 1): "fail", (3, 1): "ok"}
