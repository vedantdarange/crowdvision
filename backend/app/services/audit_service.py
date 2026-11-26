"""app/services/audit_service.py — Audit log writer."""
from __future__ import annotations

import json
from typing import Any

from app.core.time import utcnow
from app.models.models import AuditLog, User
from app.repositories.audit_repo import AuditRepository


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
