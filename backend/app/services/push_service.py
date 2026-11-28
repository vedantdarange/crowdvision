"""app/services/push_service.py — Business logic for Web Push subscriptions & tests."""
from __future__ import annotations

from datetime import datetime, timezone

from app.core.clock import Clock, SystemClock
from app.extensions import db
from app.models.models import User
from app.push.notifier import Notifier
from app.repositories.push_repo import PushSubscriptionRepository


def _naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


class PushService:
    def __init__(
        self,
        push_repo: PushSubscriptionRepository,
        notifier: Notifier,
        *,
        clock: Clock | None = None,
    ) -> None:
        self._repo = push_repo
        self._notifier = notifier
        self._clock: Clock = clock or SystemClock()

    def subscribe(
        self,
        actor: User,
        *,
        endpoint: str,
        p256dh: str,
        auth: str,
        user_agent: str = "",
    ) -> dict[str, int]:
        """Upsert caller's Web Push subscription keyed by endpoint."""
        now_naive = _naive_utc(self._clock.utcnow())
        sub = self._repo.upsert(
            user_id=actor.id,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            user_agent=user_agent[:512],
            now=now_naive,
        )
        db.session.commit()
        return {"id": sub.id}

    def unsubscribe(self, actor: User, *, endpoint: str) -> None:
        """Delete caller's subscription matching *endpoint*."""
        self._repo.delete_by_endpoint(endpoint, user_id=actor.id)
        db.session.commit()

    def send_test(self, actor: User) -> dict[str, int]:
        """Send a harmless test push to the caller's subscriptions."""
        subs = self._repo.list_for_user(actor.id)
        sent = self._notifier.send_test(subs)
        return {"sent": int(sent)}
