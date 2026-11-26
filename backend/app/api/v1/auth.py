"""app/api/v1/auth.py — Thin controller routes for /api/v1/auth."""
from __future__ import annotations

from flask import Blueprint, Response, current_app
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.container import get_container
from app.core.auth import current_user, roles_required
from app.core.errors import Unauthenticated
from app.core.responses import created, ok
from app.core.validation import parse_json_body, validate
from app.extensions import limiter
from app.schemas.auth import LoginRequest, RegisterRequest
from app.schemas.users import serialize_user

auth_bp = Blueprint("auth", __name__)


@auth_bp.post("/register")
@limiter.limit(lambda: current_app.config["RATELIMIT_REGISTER"])
def register() -> tuple[Response, int]:
    """Register a new citizen account."""
    req = validate(RegisterRequest, parse_json_body())
    result = get_container().auth_service.register(req)
    return created(result)


@auth_bp.post("/login")
@limiter.limit(lambda: current_app.config["RATELIMIT_LOGIN"])
def login() -> tuple[Response, int]:
    """Authenticate with email + password."""
    req = validate(LoginRequest, parse_json_body())
    result = get_container().auth_service.login(req)
    return ok(result)


@auth_bp.post("/refresh")
@jwt_required(refresh=True)
def refresh() -> tuple[Response, int]:
    """Issue a new access token from a valid refresh token."""
    raw_identity = get_jwt_identity()
    try:
        user_id = int(raw_identity)
    except (TypeError, ValueError) as exc:
        raise Unauthenticated("Invalid token identity.") from exc
    result = get_container().auth_service.refresh(user_id)
    return ok(result)


@auth_bp.get("/me")
@roles_required("citizen", "police", "admin")
def me() -> tuple[Response, int]:
    """Return the currently authenticated user's profile."""
    return ok(serialize_user(current_user()))
