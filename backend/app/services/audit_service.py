"""app/services/audit_service.py — Audit log writer."""
from __future__ import annotations

import json
from typing import Any

from app.core.time import utcnow
from app.models.models import AuditLog, User
from app.repositories.audit_repo import AuditRepository
from app.schemas.serializers import serialize_audit_log


class AuditService:
    def __init__(self, audit_repo: AuditRepository) -> None:
        self._audit_repo = audit_repo

    def log(
        self,
        actor: User | None,
        action: str,
        entity_type: str,
        entity_id: int | None,
        data: dict[str, Any] | None = None,
    ) -> AuditLog:
        """Append an audit entry in the active DB transaction."""
        entry = AuditLog(
            actor_id=actor.id if actor is not None else None,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            data_json=json.dumps(data or {}),
            created_at=utcnow().replace(tzinfo=None),
        )
        return self._audit_repo.add(entry)

    def list_logs(
        self,
        *,
        action: str | None = None,
        actor_id: int | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return serialized AuditLog items and total count."""
        rows, total = self._audit_repo.list_paginated(
            action=action,
            actor_id=actor_id,
            page=page,
            limit=limit,
        )
        return [serialize_audit_log(entry, actor=actor) for entry, actor in rows], total
