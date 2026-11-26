"""app/core/auth.py — RBAC decorator, current_user helper, and JWT error loaders.

Security invariant (contract §6.1 / plan §6.1):
  The JWT proves identity only. On EVERY authenticated request, roles_required
  re-reads the user from the DB and trusts the DB role and is_active flag.
  A disabled or demoted user loses access on the very next request.

Role hierarchy (encoded ONCE in _role_satisfies):
  admin satisfies any role set that includes police.
"""
from __future__ import annotations

from functools import wraps
from typing import Any, Callable

from flask import current_app, g
from flask_jwt_extended import JWTManager, get_jwt_identity, jwt_required

from app.core.errors import Forbidden, Unauthenticated
from app.core.responses import error_response
from app.models.models import User


def _role_satisfies(user_role: str, allowed_roles: tuple[str, ...]) -> bool:
    """Return True if *user_role* satisfies *allowed_roles*.

    Hierarchy: admin satisfies any role set that includes 'police'.
    """
    if user_role in allowed_roles:
        return True
    if user_role == "admin" and "police" in allowed_roles:
        return True
    return False


def roles_required(*roles: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Require an active authenticated user whose DB role satisfies *roles*."""

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(fn)
        @jwt_required()
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            raw_identity = get_jwt_identity()
            try:
                user_id = int(raw_identity)
            except (TypeError, ValueError) as exc:
                raise Unauthenticated("Invalid token identity.") from exc

            container = current_app.extensions["container"]
            user = container.user_repo.get(user_id)
            if user is None or not user.is_active:
                raise Forbidden("Account is disabled.")
            if not _role_satisfies(user.role, roles):
                raise Forbidden("Insufficient permissions.")

            g.current_user = user
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def current_user() -> User:
    """Return the authenticated User loaded by roles_required for this request."""
    user = getattr(g, "current_user", None)
    if user is None:
        raise Unauthenticated("Authentication required.")
    return user


def configure_jwt_error_loaders(jwt: JWTManager) -> None:
    """Route all Flask-JWT-Extended error responses through our contract envelope."""

    @jwt.unauthorized_loader
    def _missing_token(reason: str) -> tuple[Any, int]:
        return error_response("UNAUTHENTICATED", reason or "Missing authorization token.", status=401)

    @jwt.invalid_token_loader
    def _invalid_token(reason: str) -> tuple[Any, int]:
        return error_response("UNAUTHENTICATED", reason or "Invalid authorization token.", status=401)

    @jwt.expired_token_loader
    def _expired_token(_header: dict[str, Any], _payload: dict[str, Any]) -> tuple[Any, int]:
        return error_response("UNAUTHENTICATED", "Token has expired.", status=401)

    @jwt.revoked_token_loader
    def _revoked_token(_header: dict[str, Any], _payload: dict[str, Any]) -> tuple[Any, int]:
        return error_response("UNAUTHENTICATED", "Token has been revoked.", status=401)

    @jwt.needs_fresh_token_loader
    def _fresh_token(_header: dict[str, Any], _payload: dict[str, Any]) -> tuple[Any, int]:
        return error_response("UNAUTHENTICATED", "Fresh token required.", status=401)
