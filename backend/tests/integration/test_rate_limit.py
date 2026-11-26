"""tests/integration/test_rate_limit.py — Per-IP rate limiting + ProxyFix tests."""
from __future__ import annotations

import pytest


@pytest.fixture()
def rate_limited_app(monkeypatch):
    """App instance with rate limiting enabled and TRUSTED_PROXY_COUNT=1."""
    monkeypatch.setenv("TRUSTED_PROXY_COUNT", "1")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")

    from app import create_app
    from app.extensions import db, limiter

    # Reset in-memory limiter storage cleanly between tests
    rl_app = create_app(
        config_override={
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "RATELIMIT_ENABLED": True,
            "RATELIMIT_REGISTER": "2/hour",
            "RATELIMIT_LOGIN": "2/minute",
            "JWT_SECRET_KEY": "test-jwt-secret",
            "SECRET_KEY": "test-secret",
        }
    )

    with rl_app.app_context():
        db.create_all()
        limiter.reset()
        yield rl_app
        db.session.remove()
        db.drop_all()


class TestPerIpRateLimiting:
    def test_login_limit_per_real_client_ip_with_proxyfix(self, rate_limited_app):
        with rate_limited_app.test_client() as client:
            ip_a = {"X-Forwarded-For": "203.0.113.10"}
            ip_b = {"X-Forwarded-For": "203.0.113.11"}

            # IP A uses up its 2/minute login attempts
            for _ in range(2):
                r = client.post(
                    "/api/v1/auth/login",
                    headers=ip_a,
                    json={"email": "nobody@test.local", "password": "wrong"},
                )
                assert r.status_code == 401

            # IP A's 3rd attempt is rate-limited with 429 RATE_LIMITED envelope
            r_limited = client.post(
                "/api/v1/auth/login",
                headers=ip_a,
                json={"email": "nobody@test.local", "password": "wrong"},
            )
            assert r_limited.status_code == 429
            assert r_limited.get_json()["error"]["code"] == "RATE_LIMITED"

            # IP B has an independent bucket and is NOT blocked
            r_b = client.post(
                "/api/v1/auth/login",
                headers=ip_b,
                json={"email": "nobody@test.local", "password": "wrong"},
            )
            assert r_b.status_code == 401

    def test_register_limit_per_real_client_ip_with_proxyfix(self, rate_limited_app):
        with rate_limited_app.test_client() as client:
            ip_a = {"X-Forwarded-For": "198.51.100.5"}
            ip_b = {"X-Forwarded-For": "198.51.100.6"}

            for idx in range(2):
                r = client.post(
                    "/api/v1/auth/register",
                    headers=ip_a,
                    json={
                        "name": f"User {idx}",
                        "email": f"u{idx}@test.local",
                        "password": "Password@123",
                    },
                )
                assert r.status_code == 201

            r_limited = client.post(
                "/api/v1/auth/register",
                headers=ip_a,
                json={
                    "name": "User 3",
                    "email": "u3@test.local",
                    "password": "Password@123",
                },
            )
            assert r_limited.status_code == 429
            assert r_limited.get_json()["error"]["code"] == "RATE_LIMITED"

            # Different client IP still succeeds
            r_b = client.post(
                "/api/v1/auth/register",
                headers=ip_b,
                json={
                    "name": "User B",
                    "email": "ub@test.local",
                    "password": "Password@123",
                },
            )
            assert r_b.status_code == 201
