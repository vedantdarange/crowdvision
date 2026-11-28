"""app/repositories/analytics_repo.py — SQL aggregate queries for B8 analytics & CSV export."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Integer, cast, func

from app.extensions import db
from app.models.models import AlertModel, Report, Zone, ZoneSample

_REPORT_STATUSES = ("PENDING", "VERIFIED", "DISMISSED")


class AnalyticsRepository:
    """Read-only analytical aggregations across alerts, zone_samples, and reports."""

    def alerts_by_zone(
        self, dt_from: datetime, dt_to: datetime
    ) -> list[dict[str, Any]]:
        """Count alerts per zone grouped by peak_level inside [dt_from, dt_to]."""
        rows = (
            db.session.query(
                AlertModel.zone_id,
                Zone.name,
                AlertModel.peak_level,
                func.count(AlertModel.id),
            )
            .join(Zone, AlertModel.zone_id == Zone.id)
            .filter(
                AlertModel.created_at >= dt_from,
                AlertModel.created_at <= dt_to,
            )
            .group_by(AlertModel.zone_id, Zone.name, AlertModel.peak_level)
            .order_by(AlertModel.zone_id.asc())
            .all()
        )
        by_zone: dict[int, dict[str, Any]] = {}
        for zone_id, zone_name, peak_level, cnt in rows:
            entry = by_zone.setdefault(
                int(zone_id),
                {
                    "zone_id": int(zone_id),
                    "zone_name": str(zone_name),
                    "warning": 0,
                    "critical": 0,
                },
            )
            if peak_level == "WARNING":
                entry["warning"] += int(cnt)
            elif peak_level == "CRITICAL":
                entry["critical"] += int(cnt)
        return list(by_zone.values())

    def alert_response_averages(
        self, dt_from: datetime, dt_to: datetime
    ) -> tuple[float | None, float | None]:
        """Return (avg_ack_seconds, avg_resolve_seconds) across alerts in [dt_from, dt_to]."""
        rows = (
            db.session.query(
                AlertModel.created_at,
                AlertModel.acknowledged_at,
                AlertModel.resolved_at,
            )
            .filter(
                AlertModel.created_at >= dt_from,
                AlertModel.created_at <= dt_to,
            )
            .all()
        )
        ack_diffs = [
            (ack_at - created_at).total_seconds()
            for created_at, ack_at, _ in rows
            if ack_at is not None
        ]
        resolve_diffs = [
            (res_at - created_at).total_seconds()
            for created_at, _, res_at in rows
            if res_at is not None
        ]
        avg_ack = round(sum(ack_diffs) / len(ack_diffs), 2) if ack_diffs else None
        avg_resolve = (
            round(sum(resolve_diffs) / len(resolve_diffs), 2)
            if resolve_diffs
            else None
        )
        return avg_ack, avg_resolve

    def peak_hours_ist(
        self, dt_from: datetime, dt_to: datetime
    ) -> list[dict[str, Any]]:
        """Compute highest average-density hour (Asia/Kolkata, UTC+5:30) per zone."""
        ist_hour_expr = cast(
            func.strftime("%H", func.datetime(ZoneSample.ts, "+330 minutes")),
            Integer,
        )
        avg_density_expr = func.avg(ZoneSample.density)
        rows = (
            db.session.query(
                ZoneSample.zone_id,
                Zone.name,
                ist_hour_expr.label("ist_hour"),
                avg_density_expr.label("avg_density"),
            )
            .join(Zone, ZoneSample.zone_id == Zone.id)
            .filter(
                ZoneSample.ts >= dt_from,
                ZoneSample.ts <= dt_to,
                ZoneSample.density.isnot(None),
            )
            .group_by(ZoneSample.zone_id, Zone.name, ist_hour_expr)
            .order_by(
                ZoneSample.zone_id.asc(),
                avg_density_expr.desc(),
                ist_hour_expr.asc(),
            )
            .all()
        )
        peaks: list[dict[str, Any]] = []
        seen_zones: set[int] = set()
        for zone_id, zone_name, ist_hour, avg_density in rows:
            zid = int(zone_id)
            if zid in seen_zones:
                continue
            seen_zones.add(zid)
            peaks.append(
                {
                    "zone_id": zid,
                    "zone_name": str(zone_name),
                    "hour": int(ist_hour),
                    "avg_density": round(float(avg_density), 4),
                }
            )
        return peaks

    def reports_by_status(
        self, dt_from: datetime, dt_to: datetime
    ) -> dict[str, int]:
        """Count citizen reports by status inside [dt_from, dt_to], always including all 3 keys."""
        counts: dict[str, int] = {st: 0 for st in _REPORT_STATUSES}
        rows = (
            db.session.query(Report.status, func.count(Report.id))
            .filter(
                Report.created_at >= dt_from,
                Report.created_at <= dt_to,
            )
            .group_by(Report.status)
            .all()
        )
        for status, cnt in rows:
            if status in counts:
                counts[status] = int(cnt)
        return counts

    def list_alerts_for_export(
        self, dt_from: datetime, dt_to: datetime
    ) -> list[tuple[AlertModel, str]]:
        """Return (AlertModel, zone_name) ordered chronologically for CSV export."""
        rows = (
            db.session.query(AlertModel, Zone.name)
            .join(Zone, AlertModel.zone_id == Zone.id)
            .filter(
                AlertModel.created_at >= dt_from,
                AlertModel.created_at <= dt_to,
            )
            .order_by(AlertModel.created_at.asc(), AlertModel.id.asc())
            .all()
        )
        return [(alert, str(zone_name)) for alert, zone_name in rows]
