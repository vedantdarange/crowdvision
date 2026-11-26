"""app/schemas/users.py — Pydantic v2 schemas for /api/v1/users endpoints & User serialization."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.time import to_iso_z
from app.models.models import User
from app.schemas.auth import _normalize_email

RoleType = Literal["citizen", "police", "admin"]
AdminCreatableRole = Literal["police", "admin"]


def serialize_user(user: User) -> dict[str, Any]:
    """Serialize a User ORM instance to the contract §5 User shape.

    Never includes password_hash.
    """
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "is_active": bool(user.is_active),
        "created_at": to_iso_z(user.created_at),
    }


class CreateUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    role: AdminCreatableRole

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped

    @field_validator("email")
    @classmethod
    def _clean_email(cls, v: str) -> str:
        return _normalize_email(v)


class UpdateUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    role: RoleType | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        stripped = v.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped


class UserListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: RoleType | None = None
    is_active: bool | None = None
    q: str | None = Field(default=None, max_length=255)
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=20, ge=1, le=100)

    @field_validator("is_active", mode="before")
    @classmethod
    def _parse_bool_param(cls, v: Any) -> Any:
        if v is None or v == "":
            return None
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            low = v.strip().lower()
            if low in ("true", "1"):
                return True
            if low in ("false", "0"):
                return False
        raise ValueError("must be 'true' or 'false'")

    @field_validator("role", mode="before")
    @classmethod
    def _empty_role_none(cls, v: Any) -> Any:
        if v == "":
            return None
        return v

    @field_validator("q", mode="before")
    @classmethod
    def _clean_q(cls, v: Any) -> str | None:
        if v is None:
            return None
        s = str(v).strip()
        return s if s else None
