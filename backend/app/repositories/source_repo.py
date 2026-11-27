"""app/repositories/source_repo.py — Data-access layer for Source."""
from __future__ import annotations

from app.extensions import db
from app.models.models import Source


class SourceRepository:
    def get(self, source_id: int) -> Source | None:
        return db.session.get(Source, source_id)

    def list_all(
        self,
        zone_id: int | None = None,
        include_inactive: bool = False,
    ) -> list[Source]:
        query = db.session.query(Source)
        if zone_id is not None:
            query = query.filter(Source.zone_id == zone_id)
        if not include_inactive:
            query = query.filter(Source.is_active.is_(True))
        return query.order_by(Source.id.asc()).all()

    def list_by_zone(self, zone_id: int, include_inactive: bool = False) -> list[Source]:
        return self.list_all(zone_id=zone_id, include_inactive=include_inactive)

    def add(self, source: Source) -> Source:
        """Stage and flush a new Source within the active transaction."""
        db.session.add(source)
        db.session.flush()
        return source
