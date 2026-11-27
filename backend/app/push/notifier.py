"""app/push/notifier.py — Push Notifier Protocol, NoOpNotifier, and FakeNotifier.

B6 will add WebPushNotifier implementing this same Protocol.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Notifier(Protocol):
    """Interface for out-of-band push notifications (Web Push in B6)."""

    def notify_alert(self, alert: dict[str, Any], reason: str) -> None:
        """Notify police/admin subscribers about an alert event."""
        ...

    def notify_sos(self, report: dict[str, Any]) -> None:
        """Notify police/admin subscribers about a high-priority SOS report."""
        ...


class NoOpNotifier:
    """Default no-op notifier used until B6 Web Push is wired."""

    def notify_alert(self, alert: dict[str, Any], reason: str) -> None:
        return None

    def notify_sos(self, report: dict[str, Any]) -> None:
        return None


class FakeNotifier:
    """In-memory recording notifier for unit and integration tests."""

    def __init__(self) -> None:
        self.alert_calls: list[tuple[dict[str, Any], str]] = []
        self.sos_calls: list[dict[str, Any]] = []

    def notify_alert(self, alert: dict[str, Any], reason: str) -> None:
        self.alert_calls.append((alert, reason))

    def notify_sos(self, report: dict[str, Any]) -> None:
        self.sos_calls.append(report)

    def reset(self) -> None:
        self.alert_calls.clear()
        self.sos_calls.clear()
