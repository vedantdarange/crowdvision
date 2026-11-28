"""app/repositories/report_repo.py — Database queries for Citizen Reports (B7)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func

from app.extensions import db
from app.models.models import Report


class ReportRepository:
    def add(self, report: Report) -> Report:
        db.session.add(report)
        db.session.flush()
        return report

    def get(self, report_id: int) -> Report | None:
        return db.session.get(Report, report_id)

    def claim_review(
        self,
        report_id: int,
        *,
        status: str,
        reviewed_by: int,
        reviewed_at: datetime,
        review_note: str | None,
    ) -> int:
        """Atomically transition a PENDING report row; returns updated row count (0 or 1)."""
        updated = (
            db.session.query(Report)
            .filter(Report.id == report_id, Report.status == "PENDING")
            .update(
                {
                    Report.status: status,
                    Report.reviewed_by: reviewed_by,
                    Report.reviewed_at: reviewed_at,
                    Report.review_note: review_note,
                },
                synchronize_session=False,
            )
        )
        return int(updated)

    def list_mine(
        self,
        user_id: int,
        *,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[Report], int]:
        query = db.session.query(Report).filter(Report.created_by == user_id)
        total = query.with_entities(func.count(Report.id)).scalar() or 0
        items = (
            query.order_by(Report.created_at.desc(), Report.id.desc())
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )
        return items, int(total)

    def list_filtered(
        self,
        *,
        kind: str | None = None,
        status: str | None = None,
        zone_id: int | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[Report], int]:
        query = db.session.query(Report)
        if kind is not None:
            query = query.filter(Report.kind == kind)
        if status is not None:
            query = query.filter(Report.status == status)
        if zone_id is not None:
            query = query.filter(Report.zone_id == zone_id)
        total = query.with_entities(func.count(Report.id)).scalar() or 0
        items = (
            query.order_by(Report.created_at.desc(), Report.id.desc())
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )
        return items, int(total)

    def delete_older_than(self, cutoff_naive: datetime) -> int:
        deleted = (
            db.session.query(Report)
            .filter(Report.created_at < cutoff_naive)
            .delete(synchronize_session=False)
        )
        return int(deleted)
