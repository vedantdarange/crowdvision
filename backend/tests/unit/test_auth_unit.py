"""tests/unit/test_auth_unit.py — Unit tests for RBAC hierarchy and auth/user schemas."""
from __future__ import annotations

import pytest

from app.core.auth import _role_satisfies
from app.core.errors import ValidationAppError
from app.core.validation import validate
from app.schemas.auth import RegisterRequest
from app.schemas.users import CreateUserRequest


class TestRoleHierarchy:
    def test_exact_match(self):
        assert _role_satisfies("citizen", ("citizen",)) is True
        assert _role_satisfies("police", ("police",)) is True
        assert _role_satisfies("admin", ("admin",)) is True

    def test_admin_satisfies_police(self):
        assert _role_satisfies("admin", ("police",)) is True

    def test_police_does_not_satisfy_admin(self):
        assert _role_satisfies("police", ("admin",)) is False

    def test_citizen_does_not_satisfy_police_or_admin(self):
        assert _role_satisfies("citizen", ("police",)) is False
        assert _role_satisfies("citizen", ("admin",)) is False


class TestAuthSchemas:
    def test_register_normalizes_email_and_strips_name(self):
        req = validate(
            RegisterRequest,
            {"name": "  Alice  ", "email": "  Alice@Example.COM ", "password": "Password123"},
        )
        assert req.name == "Alice"
        assert req.email == "alice@example.com"

    def test_register_rejects_short_password(self):
        with pytest.raises(ValidationAppError) as exc_info:
            validate(
                RegisterRequest,
                {"name": "Alice", "email": "alice@example.com", "password": "short"},
            )
        assert "password" in exc_info.value.details

    def test_create_user_rejects_citizen_role(self):
        with pytest.raises(ValidationAppError) as exc_info:
            validate(
                CreateUserRequest,
                {
                    "name": "Bob",
                    "email": "bob@example.com",
                    "password": "Password123",
                    "role": "citizen",
                },
            )
        assert "role" in exc_info.value.details
