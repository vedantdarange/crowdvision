"""tests/conftest.py — Shared pytest fixtures.

The `app` fixture uses an in-memory SQLite DB (never the dev file).
The `client` fixture gives a Flask test client.
The `fake_clock` fixture provides a FakeClock pre-wired to t=0.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

# Force test environment before importing anything from the app.
os.environ.setdefault("FLASK_ENV", "testing")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("TRUSTED_PROXY_COUNT", "0")
os.environ.setdefault("DEMO_CENTER", "28.6139,77.2090")
os.environ.setdefault("DETECTOR_BACKEND", "fake")


@pytest.fixture(scope="session")
def app():
    """Application instance backed by in-memory SQLite."""
    from app import create_app
    from app.extensions import db

    flask_app = create_app(
        config_override={
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "RATELIMIT_ENABLED": False,  # disable rate limiting in general tests
            "JWT_SECRET_KEY": "test-jwt-secret",
            "SECRET_KEY": "test-secret",
        }
    )

    with flask_app.app_context():
        db.create_all()
    yield flask_app
    with flask_app.app_context():
        db.drop_all()


@pytest.fixture()
def client(app):
    """Flask test client."""
    with app.test_client() as c:
        yield c


@pytest.fixture()
def fake_clock():
    """A FakeClock starting at t=0."""
    from app.core.clock import FakeClock

    return FakeClock(start=0.0)


@pytest.fixture()
def app_ctx(app):
    """Push an application context for tests that touch the DB directly."""
    with app.app_context():
        yield


@pytest.fixture()
def clean_db(app):
    """Reset all DB tables before and after a test."""
    from app.extensions import db

    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
    yield db
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()


@pytest.fixture()
def make_user(app):
    """Factory fixture to insert a User directly into the DB."""
    from argon2 import PasswordHasher

    from app.extensions import db
    from app.models.models import User

    ph = PasswordHasher()

    def _make(
        *,
        name: str = "Test User",
        email: str = "user@test.local",
        password: str = "Pass@1234",
        role: str = "citizen",
        is_active: bool = True,
    ) -> User:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with app.app_context():
            user = User(
                name=name,
                email=email.strip().lower(),
                password_hash=ph.hash(password),
                role=role,
                is_active=is_active,
                created_at=now,
                updated_at=now,
            )
            db.session.add(user)
            db.session.commit()
            db.session.refresh(user)
            return user

    return _make


@pytest.fixture()
def token_for(app):
    """Issue an access token for a given user id & claim role."""
    from flask_jwt_extended import create_access_token

    def _token(user_id: int, role: str = "citizen") -> str:
        with app.app_context():
            return create_access_token(
                identity=str(user_id), additional_claims={"role": role}
            )

    return _token
