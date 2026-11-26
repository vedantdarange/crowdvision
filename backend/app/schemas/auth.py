"""app/schemas/auth.py — Pydantic v2 schemas for /api/v1/auth endpoints."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _normalize_email(v: str) -> str:
    cleaned = v.strip().lower()
    if "@" not in cleaned or "." not in cleaned.split("@", 1)[-1]:
        raise ValueError("must be a valid email address")
    if len(cleaned) > 255:
        raise ValueError("email must be at most 255 characters")
    return cleaned


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=128)

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


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def _clean_email(cls, v: str) -> str:
        return v.strip().lower()
