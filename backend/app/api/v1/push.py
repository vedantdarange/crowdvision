"""app/api/v1/push.py — Web Push subscription & test endpoints (contract §6.2).

Route table (all under /api/v1):
  POST   /push/subscriptions            — police/admin (upsert by endpoint)
  DELETE /push/subscriptions?endpoint=  — police/admin
  POST   /push/test                     — police/admin (sends test push to caller)
"""
from __future__ import annotations

from flask import Blueprint, request

from app.container import get_container
from app.core.auth import current_user, roles_required
from app.core.errors import ValidationAppError
from app.core.responses import created, no_content, ok
from app.core.validation import parse_json_body, validate
from app.schemas.push import PushSubscribeRequest

push_bp = Blueprint("push", __name__)


@push_bp.post("/push/subscriptions")
@roles_required("police")
def subscribe_push():
    actor = current_user()
    req = validate(PushSubscribeRequest, parse_json_body())
    user_agent = request.headers.get("User-Agent", "")
    container = get_container()
    result = container.push_service.subscribe(
        actor,
        endpoint=req.endpoint,
        p256dh=req.keys.p256dh,
        auth=req.keys.auth,
        user_agent=user_agent,
    )
    return created(result)


@push_bp.delete("/push/subscriptions")
@roles_required("police")
def unsubscribe_push():
    actor = current_user()
    raw_endpoint = request.args.get("endpoint")
    endpoint = raw_endpoint.strip() if raw_endpoint is not None else ""
    if not endpoint:
        raise ValidationAppError(
            "Validation failed.",
            details={"endpoint": ["Query parameter 'endpoint' is required."]},
        )
    container = get_container()
    container.push_service.unsubscribe(actor, endpoint=endpoint)
    return no_content()


@push_bp.post("/push/test")
@roles_required("police")
def test_push():
    actor = current_user()
    container = get_container()
    return ok(container.push_service.send_test(actor))
