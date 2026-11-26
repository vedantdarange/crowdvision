"""app/services/user_service.py — Admin user management rules."""
from __future__ import annotations

from typing import Any

from argon2 import PasswordHasher
from sqlalchemy.exc import IntegrityError

from app.core.errors import Conflict, NotFound
from app.core.time import utcnow
from app.extensions import db
from app.models.models import User
from app.repositories.user_repo import UserRepository
from app.schemas.users import (
    CreateUserRequest,
    UpdateUserRequest,
    UserListQuery,
    serialize_user,
)
from app.services.audit_service import AuditService

_ROLE_RANK = {"citizen": 0, "police": 1, "admin": 2}


class UserService:
    def __init__(
        self,
        user_repo: UserRepository,
        audit_service: AuditService,
    ) -> None:
        self._user_repo = user_repo
        self._audit = audit_service
        self._ph = PasswordHasher()

    def list_users(self, query: UserListQuery) -> tuple[list[dict[str, Any]], int]:
        users, total = self._user_repo.list_paginated(
            role=query.role,
            is_active=query.is_active,
            q=query.q,
            page=query.page,
            limit=query.limit,
        )
        return [serialize_user(u) for u in users], total

    def create_user(self, req: CreateUserRequest, actor: User) -> dict[str, Any]:
        """Create a police or admin user (admin only) and write an audit log."""
        if self._user_repo.get_by_email(req.email) is not None:
            raise Conflict("Email is already registered.")

        now = utcnow().replace(tzinfo=None)
        user = User(
            name=req.name,
            email=req.email,
            password_hash=self._ph.hash(req.password),
            role=req.role,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        try:
            self._user_repo.add(user)
            self._audit.log(
                actor=actor,
                action="USER_CREATED",
                entity_type="user",
                entity_id=user.id,
                data={"email": user.email, "role": user.role},
            )
            db.session.commit()
        except IntegrityError as exc:
            db.session.rollback()
            raise Conflict("Email is already registered.") from exc

        return serialize_user(user)

    def update_user(
        self, user_id: int, req: UpdateUserRequest, actor: User
    ) -> dict[str, Any]:
        """Update user attributes; forbids self-disable or self-demotion."""
        user = self._user_repo.get(user_id)
        if user is None:
            raise NotFound("User not found.")

        if user.id == actor.id:
            if req.is_active is False:
                raise Conflict("Cannot disable your own account.")
            if req.role is not None and _ROLE_RANK[req.role] < _ROLE_RANK[user.role]:
                raise Conflict("Cannot demote your own account.")

        changes: dict[str, Any] = {}
        if req.name is not None and req.name != user.name:
            user.name = req.name
            changes["name"] = req.name
        if req.role is not None and req.role != user.role:
            user.role = req.role
            changes["role"] = req.role
        if req.is_active is not None and req.is_active != user.is_active:
            user.is_active = req.is_active
            changes["is_active"] = req.is_active
        if req.password is not None:
            user.password_hash = self._ph.hash(req.password)
            changes["password_changed"] = True

        if changes:
            user.updated_at = utcnow().replace(tzinfo=None)
            self._audit.log(
                actor=actor,
                action="USER_UPDATED",
                entity_type="user",
                entity_id=user.id,
                data=changes,
            )
            db.session.commit()

        return serialize_user(user)
