"""app/repositories/audit_repo.py — Database queries for AuditLog."""
from __future__ import annotations

from app.extensions import db
from app.models.models import AuditLog


class AuditRepository:
    def add(self, entry: AuditLog) -> AuditLog:
        db.session.add(entry)
        db.session.flush()
        return entry
