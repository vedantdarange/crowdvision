"""app/repositories/advisory_repo.py — Data-access layer for Advisory."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_

from app.extensions import db
from app.models.models import Advisory


class AdvisoryRepository:
    def get(self, advisory_id: int) -> Advisory | None:
        return db.session.get(Advisory, advisory_id)

    def add(self, advisory: Advisory) -> Advisory:
        db.session.add(advisory)
        db.session.flush()
        return advisory

    def list_public(self, zone_id: int | None, now_naive: datetime) -> list[Advisory]:
        q = db.session.query(Advisory).filter(
            Advisory.is_active.is_(True),
            or_(Advisory.expires_at.is_(None), Advisory.expires_at > now_naive),
        )
        if zone_id is not None:
            q = q.filter(or_(Advisory.zone_id.is_(None), Advisory.zone_id == zone_id))
        return q.order_by(Advisory.created_at.desc(), Advisory.id.desc()).all()

    def list_expired_active(self, now_naive: datetime) -> list[Advisory]:
        return (
            db.session.query(Advisory)
            .filter(
                Advisory.is_active.is_(True),
                Advisory.expires_at.isnot(None),
                Advisory.expires_at <= now_naive,
            )
            .order_by(Advisory.id.asc())
            .all()
        )
