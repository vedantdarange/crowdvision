"""app/repositories/zone_sample_repo.py — Data-access layer for ZoneSample time-series."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core.time import to_iso_z
from app.extensions import db
from app.models.models import ZoneSample

_LEVEL_SEVERITY = {"NO_DATA": 0, "SAFE": 1, "WARNING": 2, "CRITICAL": 3}


class ZoneSampleRepository:
    def add(self, sample: ZoneSample) -> ZoneSample:
        db.session.add(sample)
        db.session.flush()
        return sample

    def delete_older_than(self, cutoff_naive: datetime) -> int:
        deleted = (
            db.session.query(ZoneSample)
            .filter(ZoneSample.ts < cutoff_naive)
            .delete(synchronize_session=False)
        )
        return int(deleted)

    def query_history(
        self,
        zone_id: int,
        dt_from_naive: datetime,
        dt_to_naive: datetime,
        bucket_s: int,
        max_points: int = 5000,
    ) -> list[dict[str, Any]]:
        rows = (
            db.session.query(ZoneSample)
            .filter(
                ZoneSample.zone_id == zone_id,
                ZoneSample.ts >= dt_from_naive,
                ZoneSample.ts <= dt_to_naive,
            )
            .order_by(ZoneSample.ts.asc(), ZoneSample.id.asc())
            .all()
        )
        if not rows:
            return []

        buckets: dict[int, list[ZoneSample]] = {}
        for row in rows:
            ts_utc = row.ts.replace(tzinfo=timezone.utc)
            bucket_epoch = (int(ts_utc.timestamp()) // bucket_s) * bucket_s
            buckets.setdefault(bucket_epoch, []).append(row)

        points: list[dict[str, Any]] = []
        for epoch in sorted(buckets.keys()):
            group = buckets[epoch]
            counts = [r.count for r in group if r.count is not None]
            densities = [r.density for r in group if r.density is not None]
            avg_count = round(sum(counts) / len(counts), 2) if counts else 0.0
            avg_density = round(sum(densities) / len(densities), 2) if densities else 0.0
            worst_level = max(
                (r.level for r in group),
                key=lambda lvl: _LEVEL_SEVERITY.get(lvl, 0),
            )
            bucket_dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
            points.append(
                {
                    "ts": to_iso_z(bucket_dt),
                    "count": avg_count,
                    "density": avg_density,
                    "level": worst_level,
                }
            )

        if len(points) > max_points:
            points = points[-max_points:]
        return points
