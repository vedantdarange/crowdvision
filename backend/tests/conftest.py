"""tests/conftest.py — Shared pytest fixtures.

The `app` fixture uses an in-memory SQLite DB (never the dev file).
The `client` fixture gives a Flask test client.
The `fake_clock` fixture provides a FakeClock pre-wired to t=0.
"""
from __future__ import annotations

import os

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
    # Import after env vars are set so config reads them.
    from app import create_app
    from app.extensions import db

    flask_app = create_app(
        config_override={
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "RATELIMIT_ENABLED": False,  # disable rate limiting in tests
            "JWT_SECRET_KEY": "test-jwt-secret",
            "SECRET_KEY": "test-secret",
        }
    )

    with flask_app.app_context():
        db.create_all()
        yield flask_app
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
