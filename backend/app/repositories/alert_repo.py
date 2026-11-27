"""app/repositories/alert_repo.py — Data-access layer for AlertModel & AlertEvent."""
from __future__ import annotations

from datetime import datetime

from app.extensions import db
from app.models.models import AlertEvent, AlertModel

OPEN_ALERT_STATUSES = ("NEW", "ACKNOWLEDGED", "RESPONDING")
FINAL_ALERT_STATUSES = ("RESOLVED", "AUTO_CLEARED")


class AlertRepository:
    def get(self, alert_id: int) -> AlertModel | None:
        return db.session.get(AlertModel, alert_id)

    def get_open_by_zone(self, zone_id: int) -> AlertModel | None:
        return (
            db.session.query(AlertModel)
            .filter(
                AlertModel.zone_id == zone_id,
                AlertModel.status.in_(OPEN_ALERT_STATUSES),
            )
            .first()
        )

    def list_open(self) -> list[AlertModel]:
        return (
            db.session.query(AlertModel)
            .filter(AlertModel.status.in_(OPEN_ALERT_STATUSES))
            .order_by(AlertModel.id.asc())
            .all()
        )

    def list_pending_reraises(self) -> list[AlertModel]:
        return (
            db.session.query(AlertModel)
            .filter(
                AlertModel.status == "RESOLVED",
                AlertModel.reraise_check_at.isnot(None),
            )
            .order_by(AlertModel.id.asc())
            .all()
        )

    def add(self, alert: AlertModel) -> AlertModel:
        db.session.add(alert)
        db.session.flush()
        return alert

    def add_event(self, event: AlertEvent) -> AlertEvent:
        db.session.add(event)
        db.session.flush()
        return event

    def list_events(self, alert_id: int) -> list[AlertEvent]:
        return (
            db.session.query(AlertEvent)
            .filter(AlertEvent.alert_id == alert_id)
            .order_by(AlertEvent.created_at.asc(), AlertEvent.id.asc())
            .all()
        )

    def has_feed_lost_since_open(self, alert_id: int) -> bool:
        """Return True if the latest feed event on this alert is FEED_LOST."""
        ev = (
            db.session.query(AlertEvent)
            .filter(
                AlertEvent.alert_id == alert_id,
                AlertEvent.type.in_(("FEED_LOST", "FEED_RESTORED")),
            )
            .order_by(AlertEvent.created_at.desc(), AlertEvent.id.desc())
            .first()
        )
        return ev is not None and ev.type == "FEED_LOST"

    def list_paginated(
        self,
        *,
        statuses: list[str] | None = None,
        level: str | None = None,
        zone_id: int | None = None,
        dt_from: datetime | None = None,
        dt_to: datetime | None = None,
        active: bool | None = None,
        page: int = 1,
        limit: int = 20,
        sort: str = "-created_at",
    ) -> tuple[list[AlertModel], int]:
        q = db.session.query(AlertModel)
        if statuses:
            q = q.filter(AlertModel.status.in_(statuses))
        if level:
            q = q.filter(AlertModel.level == level)
        if zone_id is not None:
            q = q.filter(AlertModel.zone_id == zone_id)
        if dt_from is not None:
            q = q.filter(AlertModel.created_at >= dt_from)
        if dt_to is not None:
            q = q.filter(AlertModel.created_at <= dt_to)
        if active is True:
            q = q.filter(AlertModel.status.in_(OPEN_ALERT_STATUSES))
        elif active is False:
            q = q.filter(AlertModel.status.in_(FINAL_ALERT_STATUSES))

        total = q.count()
        if sort == "created_at":
            q = q.order_by(AlertModel.created_at.asc(), AlertModel.id.asc())
        else:
            q = q.order_by(AlertModel.created_at.desc(), AlertModel.id.desc())

        items = q.offset((page - 1) * limit).limit(limit).all()
        return items, total
