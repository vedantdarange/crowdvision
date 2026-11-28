"""app/push/notifier.py — Notifier Protocol, NoOpNotifier, FakeNotifier, WebPushNotifier."""
from __future__ import annotations

import json
import logging
import queue
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Protocol, runtime_checkable
from urllib.parse import urlparse

from pywebpush import WebPushException, webpush

from app.core.clock import Clock, SystemClock
from app.extensions import db

if TYPE_CHECKING:
    from flask import Flask

    from app.models.models import PushSubscription
    from app.repositories.push_repo import PushSubscriptionRepository
    from app.repositories.zone_repo import ZoneRepository

logger = logging.getLogger(__name__)

PUSH_SOS_TYPES: frozenset[str] = frozenset({"CRUSH_RISK", "FIRE", "MEDICAL"})

_SOS_TITLES: dict[str, str] = {
    "CRUSH_RISK": "SOS — Crush risk",
    "FIRE": "SOS — Fire",
    "MEDICAL": "SOS — Medical",
}

_MAX_CONSECUTIVE_FAILURES = 5
_PUSH_TTL_SECONDS = 600
_DEFAULT_PUSH_TIMEOUT_S = 5.0
_MAX_WORKERS = 8
_DEFAULT_DISPATCH_QUEUE_MAXSIZE = 64


def _naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def is_valid_vapid_subject(subject: str | None) -> bool:
    """Return True if *subject* is a valid mailto: URL accepted by Web Push services."""
    if not subject or not isinstance(subject, str):
        return False
    cleaned = subject.strip()
    if not cleaned.startswith("mailto:") or any(ch.isspace() for ch in cleaned):
        return False
    address = cleaned[len("mailto:") :]
    if "@" not in address:
        return False
    local, domain = address.split("@", 1)
    if (
        not local
        or not domain
        or "." not in domain
        or domain.startswith(".")
        or domain.endswith(".")
    ):
        return False
    return True


@dataclass(frozen=True)
class PushConfigStatus:
    """Resolved Web Push configuration shared by /config and WebPushNotifier."""

    enabled: bool
    public_key: str | None
    private_key: str | None
    subject: str
    reason: str | None = None


def resolve_push_config(
    *,
    vapid_public_key: str | None,
    vapid_private_key: str | None,
    vapid_subject: str | None,
) -> PushConfigStatus:
    """Validate VAPID keys and subject with one shared rule across config & notifier."""
    pub = vapid_public_key.strip() if isinstance(vapid_public_key, str) else ""
    priv = vapid_private_key.strip() if isinstance(vapid_private_key, str) else ""
    sub = vapid_subject.strip() if isinstance(vapid_subject, str) else ""

    if not pub and not priv:
        return PushConfigStatus(
            enabled=False,
            public_key=None,
            private_key=None,
            subject=sub,
            reason="VAPID keys are not configured",
        )
    if not pub or not priv:
        return PushConfigStatus(
            enabled=False,
            public_key=None,
            private_key=None,
            subject=sub,
            reason="Incomplete VAPID keypair (both public and private keys are required)",
        )
    if not is_valid_vapid_subject(sub):
        return PushConfigStatus(
            enabled=False,
            public_key=None,
            private_key=None,
            subject=sub,
            reason="Invalid VAPID_SUBJECT (expected a valid mailto: address)",
        )
    return PushConfigStatus(
        enabled=True,
        public_key=pub,
        private_key=priv,
        subject=sub,
        reason=None,
    )


def build_alert_payload(
    alert: dict[str, Any],
    reason: str,
    *,
    zone_mode: str = "DENSITY",
) -> dict[str, Any]:
    """Build contract §9 Web Push payload for an Alert."""
    alert_id = int(alert["id"])
    zone_id = int(alert["zone_id"])
    level = str(alert["level"])
    zone_name = str(alert.get("zone_name") or f"Zone {zone_id}")

    if zone_mode == "COUNT":
        peak_count = float(alert.get("peak_count") or 0.0)
        count_display = int(round(peak_count))
        metric = f"{count_display} people (peak)"
    else:
        peak_density = float(alert.get("peak_density") or 0.0)
        metric = f"{peak_density:.1f} people/m² (peak)"

    if reason == "REMINDER":
        body = f"Unacknowledged reminder: {metric}. Tap to respond."
    else:
        body = f"{metric}. Tap to respond."

    return {
        "kind": "ALERT",
        "title": f"{level} — {zone_name}",
        "body": body,
        "url": f"/police/alerts/{alert_id}",
        "tag": f"alert-{alert_id}",
        "level": level,
        "alert_id": alert_id,
        "zone_id": zone_id,
    }


def build_sos_payload(report: dict[str, Any]) -> dict[str, Any] | None:
    """Build contract §9 Web Push payload for CRUSH_RISK, FIRE, or MEDICAL SOS."""
    sos_type = report.get("sos_type")
    if sos_type not in PUSH_SOS_TYPES:
        return None
    report_id = int(report["id"])
    zone_name = report.get("zone_name")
    zone_id = report.get("zone_id")
    body = (
        f"Reported near {zone_name}. Tap to review."
        if zone_name
        else "Reported in venue. Tap to review."
    )
    return {
        "kind": "SOS",
        "title": _SOS_TITLES[str(sos_type)],
        "body": body,
        "url": f"/police/reports?focus={report_id}",
        "tag": f"sos-{report_id}",
        "level": "CRITICAL",
        "report_id": report_id,
        "zone_id": int(zone_id) if zone_id is not None else None,
    }


def build_test_payload() -> dict[str, Any]:
    """Build harmless test Web Push payload for POST /push/test."""
    return {
        "kind": "TEST",
        "title": "Crowd Safety Monitor — Test Push",
        "body": "Push notifications are enabled for your account.",
        "url": "/police",
        "tag": "push-test",
    }


@dataclass(frozen=True)
class _DeliveryTarget:
    id: int
    revision: int
    endpoint: str
    p256dh: str
    auth: str


@runtime_checkable
class Notifier(Protocol):
    """Interface for out-of-band push notifications."""

    def notify_alert(self, alert: dict[str, Any], reason: str) -> None:
        """Notify active police/admin subscribers about an alert event."""
        ...

    def notify_sos(self, report: dict[str, Any]) -> None:
        """Notify active police/admin subscribers about a high-priority SOS report."""
        ...

    def send_test(self, subscriptions: list["PushSubscription"]) -> int:
        """Send a test push synchronously to *subscriptions*; return count delivered."""
        ...


class NoOpNotifier:
    """Default no-op notifier."""

    def notify_alert(self, alert: dict[str, Any], reason: str) -> None:
        return None

    def notify_sos(self, report: dict[str, Any]) -> None:
        return None

    def send_test(self, subscriptions: list["PushSubscription"]) -> int:
        return 0


class FakeNotifier:
    """In-memory recording notifier for unit and integration tests."""

    def __init__(self) -> None:
        self.alert_calls: list[tuple[dict[str, Any], str]] = []
        self.sos_calls: list[dict[str, Any]] = []
        self.test_calls: list[list[int]] = []

    def notify_alert(self, alert: dict[str, Any], reason: str) -> None:
        self.alert_calls.append((alert, reason))

    def notify_sos(self, report: dict[str, Any]) -> None:
        if report.get("sos_type") not in PUSH_SOS_TYPES:
            return None
        self.sos_calls.append(report)

    def send_test(self, subscriptions: list["PushSubscription"]) -> int:
        sub_ids = [s.id for s in subscriptions]
        self.test_calls.append(sub_ids)
        return len(sub_ids)

    def reset(self) -> None:
        self.alert_calls.clear()
        self.sos_calls.clear()
        self.test_calls.clear()


class WebPushNotifier:
    """VAPID Web Push notifier with bounded async background dispatch for alerts/SOS."""

    def __init__(
        self,
        *,
        push_repo: "PushSubscriptionRepository",
        zone_repo: "ZoneRepository | None" = None,
        vapid_private_key: str | None = None,
        vapid_public_key: str | None = None,
        vapid_subject: str = "mailto:you@example.com",
        clock: Clock | None = None,
        timeout_s: float = _DEFAULT_PUSH_TIMEOUT_S,
        max_failures: int = _MAX_CONSECUTIVE_FAILURES,
        max_queue_size: int = _DEFAULT_DISPATCH_QUEUE_MAXSIZE,
        flask_app: "Flask | None" = None,
        webpush_fn: Callable[..., Any] = webpush,
    ) -> None:
        self._push_repo = push_repo
        self._zone_repo = zone_repo
        self._config = resolve_push_config(
            vapid_public_key=vapid_public_key,
            vapid_private_key=vapid_private_key,
            vapid_subject=vapid_subject,
        )
        self._vapid_private_key = self._config.private_key
        self._vapid_public_key = self._config.public_key
        self._vapid_subject = self._config.subject
        self._clock: Clock = clock or SystemClock()
        self._timeout_s = float(timeout_s)
        self._max_failures = int(max_failures)
        self._webpush_fn = webpush_fn

        self._flask_app = flask_app
        self._queue: queue.Queue[tuple[str, dict[str, Any], str] | None] = queue.Queue(
            maxsize=max(1, int(max_queue_size))
        )
        self._dispatch_lock = threading.Lock()
        self._idle_cond = threading.Condition(self._dispatch_lock)
        self._inflight_jobs = 0
        self._dropped_count = 0
        self._stop_event = threading.Event()
        self._stopped_explicitly = False
        self._worker_thread: threading.Thread | None = None

        if not self._config.enabled and self._config.reason:
            logger.warning("Web Push disabled: %s", self._config.reason)

    @property
    def is_configured(self) -> bool:
        return self._config.enabled

    @property
    def config_reason(self) -> str | None:
        return self._config.reason

    @property
    def dropped_count(self) -> int:
        with self._dispatch_lock:
            return self._dropped_count

    def start(self, flask_app: "Flask | None" = None) -> None:
        """Start the background push dispatcher thread if not already running."""
        with self._dispatch_lock:
            if flask_app is not None:
                self._flask_app = flask_app
            self._stopped_explicitly = False
            self._stop_event.clear()
            self._ensure_worker_locked()

    def stop(self, timeout: float = 3.0) -> None:
        """Signal the background dispatcher to stop and wait up to *timeout* seconds."""
        with self._dispatch_lock:
            self._stopped_explicitly = True
            self._stop_event.set()
            thread = self._worker_thread
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                pass
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(0.0, float(timeout)))
        with self._dispatch_lock:
            if self._worker_thread is not None and not self._worker_thread.is_alive():
                self._worker_thread = None

    def flush(self, timeout: float = 5.0) -> bool:
        """Wait up to *timeout* seconds for queued alert/SOS dispatches to finish."""
        with self._idle_cond:
            return self._idle_cond.wait_for(
                lambda: self._inflight_jobs == 0,
                timeout=max(0.0, float(timeout)),
            )

    def reset(self) -> None:
        """Reset dropped counter and queued jobs (used by test teardown)."""
        with self._idle_cond:
            while True:
                try:
                    self._queue.get_nowait()
                    self._queue.task_done()
                except queue.Empty:
                    break
            self._dropped_count = 0
            self._inflight_jobs = 0
            self._stopped_explicitly = False
            self._stop_event.clear()
            self._idle_cond.notify_all()

    def _ensure_worker_locked(self) -> None:
        if self._flask_app is None or self._stopped_explicitly:
            return
        if self._worker_thread is None or not self._worker_thread.is_alive():
            self._stop_event.clear()
            self._worker_thread = threading.Thread(
                target=self._dispatch_loop,
                name="webpush-dispatcher",
                daemon=True,
            )
            self._worker_thread.start()

    def _enqueue(
        self,
        kind: str,
        item_dict: dict[str, Any],
        reason: str,
        *,
        ref_id: int | None,
        zone_id: int | None,
    ) -> None:
        """Enqueue push dispatch without blocking; drops newest on full queue."""
        if self._flask_app is None:
            if kind == "ALERT":
                self._execute_alert(item_dict, reason)
            elif kind == "SOS":
                self._execute_sos(item_dict)
            return

        with self._idle_cond:
            if self._stopped_explicitly:
                return
            self._ensure_worker_locked()
            try:
                self._queue.put_nowait((kind, dict(item_dict), reason))
                self._inflight_jobs += 1
            except queue.Full:
                self._dropped_count += 1
                dropped_total = self._dropped_count
                logger.warning(
                    "Web Push dispatch queue full; dropping push dispatch",
                    extra={
                        "kind": kind,
                        "reason": reason,
                        "ref_id": ref_id,
                        "zone_id": zone_id,
                        "queue_maxsize": self._queue.maxsize,
                        "dropped_total": dropped_total,
                    },
                )

    def _dispatch_loop(self) -> None:
        assert self._flask_app is not None
        while not self._stop_event.is_set():
            try:
                item = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if item is None:
                self._queue.task_done()
                break

            kind, payload_src, reason = item
            try:
                with self._flask_app.app_context():
                    try:
                        if kind == "ALERT":
                            self._execute_alert(payload_src, reason)
                        elif kind == "SOS":
                            self._execute_sos(payload_src)
                    except Exception:
                        logger.exception("Web Push dispatcher failed handling %s", kind)
                        try:
                            db.session.rollback()
                        except Exception:
                            pass
            finally:
                self._queue.task_done()
                with self._idle_cond:
                    self._inflight_jobs = max(0, self._inflight_jobs - 1)
                    self._idle_cond.notify_all()

    def notify_alert(self, alert: dict[str, Any], reason: str) -> None:
        if not self.is_configured:
            return
        self._enqueue(
            "ALERT",
            alert,
            reason,
            ref_id=int(alert["id"]) if alert.get("id") is not None else None,
            zone_id=int(alert["zone_id"]) if alert.get("zone_id") is not None else None,
        )

    def notify_sos(self, report: dict[str, Any]) -> None:
        if report.get("sos_type") not in PUSH_SOS_TYPES or not self.is_configured:
            return
        raw_zid = report.get("zone_id")
        self._enqueue(
            "SOS",
            report,
            str(report.get("sos_type") or "SOS"),
            ref_id=int(report["id"]) if report.get("id") is not None else None,
            zone_id=int(raw_zid) if raw_zid is not None else None,
        )

    def _execute_alert(self, alert: dict[str, Any], reason: str) -> None:
        if not self.is_configured:
            return
        zone_mode = "DENSITY"
        if self._zone_repo is not None:
            zone = self._zone_repo.get(int(alert["zone_id"]))
            if zone is not None:
                zone_mode = zone.mode
        payload = build_alert_payload(alert, reason, zone_mode=zone_mode)
        subs = self._push_repo.list_active_police_subscriptions()
        self._deliver(subs, payload, event_kind="ALERT", reason=reason)

    def _execute_sos(self, report: dict[str, Any]) -> None:
        payload = build_sos_payload(report)
        if payload is None or not self.is_configured:
            return
        subs = self._push_repo.list_active_police_subscriptions()
        self._deliver(
            subs,
            payload,
            event_kind="SOS",
            reason=str(report.get("sos_type") or "SOS"),
        )

    def send_test(self, subscriptions: list["PushSubscription"]) -> int:
        if not self.is_configured or not subscriptions:
            return 0
        payload = build_test_payload()
        return self._deliver(subscriptions, payload, event_kind="TEST", reason="TEST")

    def _send_one(self, target: _DeliveryTarget, data_json: str) -> tuple[int, int, str]:
        assert self._vapid_private_key is not None
        host = urlparse(target.endpoint).netloc or "unknown-host"
        # pywebpush mutates vapid_claims in place (adds aud/exp) — always construct a fresh dict.
        claims = {"sub": self._vapid_subject}
        subscription_info = {
            "endpoint": target.endpoint,
            "keys": {"p256dh": target.p256dh, "auth": target.auth},
        }
        try:
            self._webpush_fn(
                subscription_info=subscription_info,
                data=data_json,
                vapid_private_key=self._vapid_private_key,
                vapid_claims=claims,
                ttl=_PUSH_TTL_SECONDS,
                headers={"Urgency": "high"},
                timeout=self._timeout_s,
            )
            logger.info("Web Push sent", extra={"sub_id": target.id, "push_host": host})
            return target.id, target.revision, "ok"
        except WebPushException as exc:
            status = exc.status_code
            if status in (404, 410):
                logger.info(
                    "Deleting gone Web Push subscription",
                    extra={"sub_id": target.id, "push_host": host, "status_code": status},
                )
                return target.id, target.revision, "gone"
            logger.warning(
                "Web Push delivery failed",
                extra={"sub_id": target.id, "push_host": host, "status_code": status},
            )
            return target.id, target.revision, "fail"
        except Exception as exc:
            logger.warning(
                "Web Push unexpected delivery error",
                extra={"sub_id": target.id, "push_host": host, "error_type": type(exc).__name__},
            )
            return target.id, target.revision, "fail"

    def _deliver(
        self,
        subscriptions: list["PushSubscription"],
        payload: dict[str, Any],
        *,
        event_kind: str,
        reason: str,
    ) -> int:
        if not subscriptions:
            return 0

        targets = [
            _DeliveryTarget(
                id=s.id,
                revision=int(getattr(s, "revision", 1)),
                endpoint=s.endpoint,
                p256dh=s.p256dh,
                auth=s.auth,
            )
            for s in subscriptions
        ]
        data_json = json.dumps(payload, separators=(",", ":"))

        outcomes: list[tuple[int, int, str]] = []
        if len(targets) == 1:
            outcomes.append(self._send_one(targets[0], data_json))
        else:
            workers = min(_MAX_WORKERS, len(targets))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(self._send_one, tgt, data_json) for tgt in targets]
                for fut in as_completed(futures):
                    outcomes.append(fut.result())

        now_naive = _naive_utc(self._clock.utcnow())
        self._push_repo.record_delivery_results(
            outcomes,
            now=now_naive,
            max_failures=self._max_failures,
        )

        sent = sum(1 for _, _, st in outcomes if st == "ok")
        logger.info(
            "Web Push batch complete",
            extra={
                "kind": event_kind,
                "reason": reason,
                "total": len(targets),
                "sent": sent,
            },
        )
        return sent
