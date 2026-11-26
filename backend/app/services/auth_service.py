"""app/services/auth_service.py — Authentication business logic."""
from __future__ import annotations

import logging
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from flask_jwt_extended import create_access_token, create_refresh_token
from sqlalchemy.exc import IntegrityError

from app.core.errors import Conflict, Forbidden, Unauthenticated
from app.core.time import utcnow
from app.extensions import db
from app.models.models import User
from app.repositories.user_repo import UserRepository
from app.schemas.auth import LoginRequest, RegisterRequest
from app.schemas.users import serialize_user

logger = logging.getLogger(__name__)

ACCESS_EXPIRES_SECONDS = 60 * 60


class AuthService:
    def __init__(self, user_repo: UserRepository) -> None:
        self._user_repo = user_repo
        self._ph = PasswordHasher()

    def register(self, req: RegisterRequest) -> dict[str, Any]:
        """Create a new citizen user and issue access + refresh tokens."""
        if self._user_repo.get_by_email(req.email) is not None:
            raise Conflict("Email is already registered.")

        now = utcnow().replace(tzinfo=None)
        user = User(
            name=req.name,
            email=req.email,
            password_hash=self._ph.hash(req.password),
            role="citizen",
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        try:
            self._user_repo.add(user)
            db.session.commit()
        except IntegrityError as exc:
            db.session.rollback()
            raise Conflict("Email is already registered.") from exc

        return self._build_auth_payload(user)

    def login(self, req: LoginRequest) -> dict[str, Any]:
        """Verify credentials and issue access + refresh tokens.

        Returns the exact same 401 message for unknown email and wrong password
        to prevent user enumeration. Disabled users receive 403 FORBIDDEN.
        """
        user = self._user_repo.get_by_email(req.email)
        if user is None:
            raise Unauthenticated("Invalid email or password.")

        try:
            self._ph.verify(user.password_hash, req.password)
        except (VerifyMismatchError, VerificationError, InvalidHashError) as exc:
            raise Unauthenticated("Invalid email or password.") from exc

        if not user.is_active:
            raise Forbidden("Account is disabled.")

        return self._build_auth_payload(user)

    def refresh(self, user_id: int) -> dict[str, Any]:
        """Issue a fresh access token using the user's current DB role & status."""
        user = self._user_repo.get(user_id)
        if user is None:
            raise Unauthenticated("Invalid token.")
        if not user.is_active:
            raise Forbidden("Account is disabled.")

        access_token = create_access_token(
            identity=str(user.id),
            additional_claims={"role": user.role},
        )
        return {
            "access_token": access_token,
            "expires_in": ACCESS_EXPIRES_SECONDS,
        }

    def _build_auth_payload(self, user: User) -> dict[str, Any]:
        access_token = create_access_token(
            identity=str(user.id),
            additional_claims={"role": user.role},
        )
        refresh_token = create_refresh_token(identity=str(user.id))
        return {
            "user": serialize_user(user),
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": ACCESS_EXPIRES_SECONDS,
        }
