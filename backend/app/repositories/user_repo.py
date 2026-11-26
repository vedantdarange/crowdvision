"""app/repositories/user_repo.py — Database queries for User.

Repositories own queries only; no business rules or Flask imports.
"""
from __future__ import annotations

from sqlalchemy import func, or_

from app.extensions import db
from app.models.models import User


class UserRepository:
    def get(self, user_id: int) -> User | None:
        return db.session.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        return (
            db.session.query(User)
            .filter(User.email.ilike(email.strip()))
            .first()
        )

    def add(self, user: User) -> User:
        db.session.add(user)
        db.session.flush()
        return user

    def list_paginated(
        self,
        *,
        role: str | None = None,
        is_active: bool | None = None,
        q: str | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[User], int]:
        query = db.session.query(User)

        if role is not None:
            query = query.filter(User.role == role)
        if is_active is not None:
            query = query.filter(User.is_active.is_(is_active))
        if q:
            pattern = f"%{q}%"
            query = query.filter(
                or_(User.name.ilike(pattern), User.email.ilike(pattern))
            )

        total = query.with_entities(func.count(User.id)).scalar() or 0
        items = (
            query.order_by(User.created_at.desc(), User.id.desc())
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )
        return items, int(total)
