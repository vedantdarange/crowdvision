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


@pytest.mark.parametrize("creation_order", ["disabled_first", "default_first"])
def test_create_app_rate_limit_isolation_across_both_orders(tmp_path, monkeypatch, creation_order):
    """Creating a limits-disabled app and a default app in one process isolates both."""
    from argon2 import PasswordHasher
    from flask_jwt_extended import create_access_token

    from app import create_app
    from app.core.time import utcnow
    from app.extensions import db, limiter
    from app.models.models import User

    monkeypatch.setenv("TRUSTED_PROXY_COUNT", "1")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.delenv("RATE_LIMIT_REPORT_CROWD", raising=False)
    monkeypatch.delenv("RATE_LIMIT_REPORT_SOS", raising=False)

    disabled_db = tmp_path / f"{creation_order}_disabled.db"
    default_db = tmp_path / f"{creation_order}_default.db"

    def _make_disabled():
        return create_app(
            config_override={
                "TESTING": True,
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{disabled_db.as_posix()}",
                "RATELIMIT_ENABLED": False,
                "JWT_SECRET_KEY": "rl-iso-jwt-secret-key-at-least-32-bytes!",
                "SECRET_KEY": "rl-iso-secret",
            }
        )

    def _make_default():
        # Intentionally omit RATELIMIT_ENABLED and RATELIMIT_REPORT_* to verify true defaults.
        return create_app(
            config_override={
                "TESTING": True,
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{default_db.as_posix()}",
                "JWT_SECRET_KEY": "rl-iso-jwt-secret-key-at-least-32-bytes!",
                "SECRET_KEY": "rl-iso-secret",
            }
        )

    if creation_order == "disabled_first":
        disabled_app = _make_disabled()
        default_app = _make_default()
    else:
        default_app = _make_default()
        disabled_app = _make_disabled()

    def _seed_citizen(flask_app, email: str) -> str:
        ph = PasswordHasher()
        now_naive = utcnow().replace(tzinfo=None)
        with flask_app.app_context():
            db.create_all()
            u = User(
                name="RLCitizen",
                email=email,
                password_hash=ph.hash("Pass@1234"),
                role="citizen",
                is_active=True,
                created_at=now_naive,
                updated_at=now_naive,
            )
            db.session.add(u)
            db.session.commit()
            return create_access_token(identity=str(u.id), additional_claims={"role": "citizen"})

    try:
        tok_disabled = _seed_citizen(disabled_app, f"dis_{creation_order}@test.local")
        tok_default = _seed_citizen(default_app, f"def_{creation_order}@test.local")

        def _hit_sos_sequence(flask_app, tok: str, count: int) -> list[int]:
            codes: list[int] = []
            with flask_app.test_client() as tc:
                for i in range(count):
                    resp = tc.post(
                        "/api/v1/reports/sos",
                        headers={
                            "Authorization": f"Bearer {tok}",
                            "X-Forwarded-For": "203.0.113.99",
                        },
                        json={"sos_type": "MEDICAL", "lat": 28.6141, "lng": 77.2092, "note": f"n{i}"},
                    )
                    codes.append(resp.status_code)
            return codes

        if creation_order == "default_first":
            # Interleave default -> disabled -> default to prove disabled app does not
            # reset or disable the default app's counters.
            pre_codes = _hit_sos_sequence(default_app, tok_default, 2)
            assert pre_codes == [201, 201]

            disabled_codes = _hit_sos_sequence(disabled_app, tok_disabled, 5)
            assert disabled_codes == [201, 201, 201, 201, 201]

            post_codes = _hit_sos_sequence(default_app, tok_default, 2)
            assert post_codes == [201, 429]
        else:
            # disabled_first: hit default app past its 3/10m limit -> 429, while disabled app
            # continues allowing unlimited requests afterward.
            default_codes = _hit_sos_sequence(default_app, tok_default, 4)
            assert default_codes == [201, 201, 201, 429]

            disabled_codes = _hit_sos_sequence(disabled_app, tok_disabled, 5)
            assert disabled_codes == [201, 201, 201, 201, 201]
    finally:
        if getattr(limiter, "_storage", None) is not None:
            limiter.reset()
        for app_inst in (disabled_app, default_app):
            with app_inst.app_context():
                db.session.remove()
                db.engine.dispose()
