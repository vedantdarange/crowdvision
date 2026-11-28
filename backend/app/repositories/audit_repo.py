"""app/repositories/audit_repo.py — Database queries for AuditLog."""
from __future__ import annotations

from sqlalchemy import func

from app.extensions import db
from app.models.models import AuditLog, User


class AuditRepository:
    def add(self, entry: AuditLog) -> AuditLog:
        db.session.add(entry)
        db.session.flush()
        return entry

    def list_paginated(
        self,
        *,
        action: str | None = None,
        actor_id: int | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[tuple[AuditLog, User | None]], int]:
        query = db.session.query(AuditLog, User).outerjoin(
            User, AuditLog.actor_id == User.id
        )
        if action is not None:
            query = query.filter(AuditLog.action == action)
        if actor_id is not None:
            query = query.filter(AuditLog.actor_id == actor_id)

        total = query.with_entities(func.count(AuditLog.id)).scalar() or 0
        rows = (
            query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )
        return [(entry, actor) for entry, actor in rows], int(total)
