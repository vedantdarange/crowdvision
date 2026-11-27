"""app/repositories/zone_repo.py — Data-access layer for Zone."""
from __future__ import annotations

from app.extensions import db
from app.models.models import AlertModel, Zone

_OPEN_ALERT_STATUSES = ("NEW", "ACKNOWLEDGED", "RESPONDING")


class ZoneRepository:
    def get(self, zone_id: int) -> Zone | None:
        return db.session.get(Zone, zone_id)

    def get_by_name_active(self, name: str) -> Zone | None:
        """Return an active zone with the given name (case-insensitive), or None."""
        return (
            db.session.query(Zone)
            .filter(
                Zone.is_active.is_(True),
                Zone.name.ilike(name),
            )
            .first()
        )

    def add(self, zone: Zone) -> Zone:
        """Stage and flush a new Zone within the active transaction."""
        db.session.add(zone)
        db.session.flush()
        return zone

    def list_all(self, include_inactive: bool = False) -> list[Zone]:
        query = db.session.query(Zone)
        if not include_inactive:
            query = query.filter(Zone.is_active.is_(True))
        return query.order_by(Zone.id.asc()).all()

    def list_active(self) -> list[Zone]:
        return (
            db.session.query(Zone)
            .filter(Zone.is_active.is_(True))
            .order_by(Zone.id.asc())
            .all()
        )

    def get_open_alert_id(self, zone_id: int) -> int | None:
        """Return the id of the zone's open alert if one exists, else None."""
        row = (
            db.session.query(AlertModel.id)
            .filter(
                AlertModel.zone_id == zone_id,
                AlertModel.status.in_(_OPEN_ALERT_STATUSES),
            )
            .first()
        )
        return int(row[0]) if row is not None else None

    def get_open_alert_ids_map(self) -> dict[int, int]:
        """Return {zone_id: open_alert_id} for all zones with open alerts."""
        rows = (
            db.session.query(AlertModel.zone_id, AlertModel.id)
            .filter(AlertModel.status.in_(_OPEN_ALERT_STATUSES))
            .all()
        )
        return {int(z_id): int(a_id) for z_id, a_id in rows}

    def has_open_alert(self, zone_id: int) -> bool:
        """Return True if the zone has an open (non-resolved) alert."""
        return self.get_open_alert_id(zone_id) is not None
