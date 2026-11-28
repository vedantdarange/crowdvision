"""app/services/analytics_service.py — Analytics summary and CSV export business logic (B8)."""
from __future__ import annotations

import codecs
import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.clock import Clock, SystemClock
from app.core.errors import ValidationAppError
from app.core.time import to_iso_z
from app.repositories.analytics_repo import AnalyticsRepository

_CSV_COLUMNS = [
    "id",
    "zone",
    "level",
    "peak_level",
    "status",
    "peak_density",
    "peak_count",
    "created_at",
    "acknowledged_at",
    "resolved_at",
]


def _naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


class AnalyticsService:
    def __init__(
        self,
        analytics_repo: AnalyticsRepository,
        *,
        clock: Clock | None = None,
    ) -> None:
        self._repo = analytics_repo
        self._clock: Clock = clock or SystemClock()

    def _resolve_range(
        self, dt_from: datetime | None, dt_to: datetime | None
    ) -> tuple[datetime, datetime]:
        now_naive = _naive_utc(self._clock.utcnow())
        to_naive = _naive_utc(dt_to) if dt_to is not None else now_naive
        from_naive = (
            _naive_utc(dt_from)
            if dt_from is not None
            else (to_naive - timedelta(hours=24))
        )
        if from_naive > to_naive:
            raise ValidationAppError(
                "'from' must be before 'to'.",
                details={"from": ["Must be <= 'to'"]},
            )
        return from_naive, to_naive

    def get_summary(
        self,
        *,
        dt_from: datetime | None = None,
        dt_to: datetime | None = None,
    ) -> dict[str, Any]:
        """Compute contract §5 AnalyticsSummary across [from, to] (default last 24 h)."""
        from_naive, to_naive = self._resolve_range(dt_from, dt_to)
        alerts_by_zone = self._repo.alerts_by_zone(from_naive, to_naive)
        avg_ack, avg_resolve = self._repo.alert_response_averages(from_naive, to_naive)
        peak_hours = self._repo.peak_hours_ist(from_naive, to_naive)
        reports_by_status = self._repo.reports_by_status(from_naive, to_naive)
        return {
            "from": to_iso_z(from_naive),
            "to": to_iso_z(to_naive),
            "alerts_by_zone": alerts_by_zone,
            "avg_ack_seconds": avg_ack,
            "avg_resolve_seconds": avg_resolve,
            "timezone": "Asia/Kolkata",
            "peak_hours": peak_hours,
            "reports_by_status": reports_by_status,
        }

    def export_alerts_csv(
        self,
        *,
        dt_from: datetime | None = None,
        dt_to: datetime | None = None,
    ) -> bytes:
        """Render contract §6.2 alerts CSV encoded as UTF-8 with BOM for Excel."""
        from_naive, to_naive = self._resolve_range(dt_from, dt_to)
        rows = self._repo.list_alerts_for_export(from_naive, to_naive)

        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\r\n")
        writer.writerow(_CSV_COLUMNS)
        for alert, zone_name in rows:
            writer.writerow(
                [
                    alert.id,
                    zone_name,
                    alert.level,
                    alert.peak_level,
                    alert.status,
                    round(float(alert.peak_density), 4),
                    int(round(alert.peak_count)),
                    to_iso_z(alert.created_at) or "",
                    to_iso_z(alert.acknowledged_at) or "",
                    to_iso_z(alert.resolved_at) or "",
                ]
            )
        return codecs.BOM_UTF8 + buf.getvalue().encode("utf-8")
