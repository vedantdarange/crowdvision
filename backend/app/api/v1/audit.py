"""app/api/v1/audit.py — Audit log query endpoint (contract §6.2).

Route table (all under /api/v1):
  GET /audit-logs?page&limit&action=&actor_id=  — admin
"""
from __future__ import annotations

from flask import Blueprint, request

from app.container import get_container
from app.core.auth import current_user, roles_required
from app.core.errors import ValidationAppError
from app.core.responses import paginated

audit_bp = Blueprint("audit", __name__)


@audit_bp.get("/audit-logs")
@roles_required("admin")
def list_audit_logs():
    current_user()
    action = (request.args.get("action") or "").strip() or None

    raw_actor = request.args.get("actor_id")
    actor_id: int | None = None
    if raw_actor is not None and raw_actor != "":
        try:
            actor_id = int(raw_actor)
        except ValueError as exc:
            raise ValidationAppError(
                "actor_id must be an integer.",
                details={"actor_id": ["Must be an integer"]},
            ) from exc

    try:
        page = max(1, int(request.args.get("page", 1)))
        limit = max(1, min(100, int(request.args.get("limit", 20))))
    except ValueError as exc:
        raise ValidationAppError("page and limit must be integers.") from exc

    container = get_container()
    items, total = container.audit_service.list_logs(
        action=action,
        actor_id=actor_id,
        page=page,
        limit=limit,
    )
    return paginated(items, total, page, limit)
