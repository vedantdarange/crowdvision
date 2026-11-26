"""app/api/v1/users.py — Thin controller routes for /api/v1/users (admin only)."""
from __future__ import annotations

from flask import Blueprint, Response, request

from app.container import get_container
from app.core.auth import current_user, roles_required
from app.core.responses import created, ok, paginated
from app.core.validation import parse_json_body, validate
from app.schemas.users import CreateUserRequest, UpdateUserRequest, UserListQuery

users_bp = Blueprint("users", __name__)


@users_bp.get("")
@roles_required("admin")
def list_users() -> tuple[Response, int]:
    """List users with optional filtering and pagination."""
    query = validate(UserListQuery, request.args.to_dict())
    items, total = get_container().user_service.list_users(query)
    return paginated(items, total=total, page=query.page, limit=query.limit)


@users_bp.post("")
@roles_required("admin")
def create_user() -> tuple[Response, int]:
    """Create a police or admin account."""
    req = validate(CreateUserRequest, parse_json_body())
    user = get_container().user_service.create_user(req, actor=current_user())
    return created(user)


@users_bp.patch("/<int:user_id>")
@roles_required("admin")
def update_user(user_id: int) -> tuple[Response, int]:
    """Update a user's name, role, active state, or password."""
    req = validate(UpdateUserRequest, parse_json_body())
    user = get_container().user_service.update_user(
        user_id, req, actor=current_user()
    )
    return ok(user)
