"""app/repositories/push_repo.py — Database queries for PushSubscription."""
from __future__ import annotations

from datetime import datetime

from app.extensions import db
from app.models.models import PushSubscription, User


class PushSubscriptionRepository:
    def get(self, sub_id: int) -> PushSubscription | None:
        return db.session.get(PushSubscription, sub_id)

    def get_by_endpoint(self, endpoint: str) -> PushSubscription | None:
        return (
            db.session.query(PushSubscription)
            .filter(PushSubscription.endpoint == endpoint)
            .first()
        )

    def upsert(
        self,
        *,
        user_id: int,
        endpoint: str,
        p256dh: str,
        auth: str,
        user_agent: str,
        now: datetime,
    ) -> PushSubscription:
        """Create or update a subscription keyed by endpoint, bumping revision."""
        updated = (
            db.session.query(PushSubscription)
            .filter(PushSubscription.endpoint == endpoint)
            .update(
                {
                    PushSubscription.user_id: user_id,
                    PushSubscription.p256dh: p256dh,
                    PushSubscription.auth: auth,
                    PushSubscription.user_agent: user_agent,
                    PushSubscription.failure_count: 0,
                    PushSubscription.revision: PushSubscription.revision + 1,
                },
                synchronize_session=False,
            )
        )
        if updated:
            db.session.expire_all()
            existing = self.get_by_endpoint(endpoint)
            assert existing is not None
            return existing

        sub = PushSubscription(  # pyrefly: ignore[unexpected-keyword]
            user_id=user_id,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            user_agent=user_agent,
            created_at=now,
            last_success_at=None,
            failure_count=0,
            revision=1,
        )
        db.session.add(sub)
        db.session.flush()
        return sub

    def delete_by_endpoint(self, endpoint: str, *, user_id: int | None = None) -> int:
        """Delete matching subscription(s) and return number of deleted rows."""
        query = db.session.query(PushSubscription).filter(
            PushSubscription.endpoint == endpoint
        )
        if user_id is not None:
            query = query.filter(PushSubscription.user_id == user_id)
        return int(query.delete(synchronize_session=False))

    def list_for_user(self, user_id: int) -> list[PushSubscription]:
        return (
            db.session.query(PushSubscription)
            .join(User, PushSubscription.user_id == User.id)
            .filter(
                PushSubscription.user_id == user_id,
                User.is_active.is_(True),
            )
            .order_by(PushSubscription.id.asc())
            .all()
        )

    def list_active_police_subscriptions(self) -> list[PushSubscription]:
        """Return subscriptions owned by active police or admin users."""
        return (
            db.session.query(PushSubscription)
            .join(User, PushSubscription.user_id == User.id)
            .filter(
                User.is_active.is_(True),
                User.role.in_(("police", "admin")),
            )
            .order_by(PushSubscription.id.asc())
            .all()
        )

    def record_delivery_results(
        self,
        outcomes: list[tuple[int, int, str]],
        *,
        now: datetime,
        max_failures: int = 5,
    ) -> None:
        """Atomically apply delivery outcomes only when subscription revision matches."""
        if not outcomes:
            return
        for sub_id, expected_revision, status in outcomes:
            if status == "ok":
                db.session.query(PushSubscription).filter(
                    PushSubscription.id == sub_id,
                    PushSubscription.revision == expected_revision,
                ).update(
                    {
                        PushSubscription.failure_count: 0,
                        PushSubscription.last_success_at: now,
                    },
                    synchronize_session=False,
                )
            elif status == "gone":
                db.session.query(PushSubscription).filter(
                    PushSubscription.id == sub_id,
                    PushSubscription.revision == expected_revision,
                ).delete(synchronize_session=False)
            elif status == "fail":
                updated = (
                    db.session.query(PushSubscription)
                    .filter(
                        PushSubscription.id == sub_id,
                        PushSubscription.revision == expected_revision,
                    )
                    .update(
                        {PushSubscription.failure_count: PushSubscription.failure_count + 1},
                        synchronize_session=False,
                    )
                )
                if updated:
                    db.session.query(PushSubscription).filter(
                        PushSubscription.id == sub_id,
                        PushSubscription.revision == expected_revision,
                        PushSubscription.failure_count >= max_failures,
                    ).delete(synchronize_session=False)
        db.session.commit()
        db.session.expire_all()
