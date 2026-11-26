"""tests/integration/test_auth.py — Auth endpoints, token freshness, and log hygiene."""
from __future__ import annotations

import logging
from datetime import timedelta


class TestAuthEndpoints:
    def test_register_creates_citizen_and_returns_tokens(self, client, clean_db):
        resp = client.post(
            "/api/v1/auth/register",
            json={
                "name": "Ravi Kumar",
                "email": "Ravi@Example.com",
                "password": "Password@123",
            },
        )
        assert resp.status_code == 201
        data = resp.get_json()["data"]
        assert data["user"]["email"] == "ravi@example.com"
        assert data["user"]["role"] == "citizen"
        assert data["user"]["is_active"] is True
        assert "password_hash" not in data["user"]
        assert data["expires_in"] == 3600
        assert isinstance(data["access_token"], str) and data["access_token"]
        assert isinstance(data["refresh_token"], str) and data["refresh_token"]

    def test_register_duplicate_email_case_insensitive_returns_409(self, client, clean_db):
        payload = {"name": "A", "email": "dup@example.com", "password": "Password@123"}
        assert client.post("/api/v1/auth/register", json=payload).status_code == 201

        dup_resp = client.post(
            "/api/v1/auth/register",
            json={"name": "B", "email": "DUP@example.com", "password": "Password@123"},
        )
        assert dup_resp.status_code == 409
        assert dup_resp.get_json()["error"]["code"] == "CONFLICT"

    def test_register_short_password_returns_422(self, client, clean_db):
        resp = client.post(
            "/api/v1/auth/register",
            json={"name": "A", "email": "a@example.com", "password": "short"},
        )
        assert resp.status_code == 422
        assert resp.get_json()["error"]["code"] == "VALIDATION_ERROR"

    def test_login_unknown_email_and_wrong_password_identical_401(
        self, client, clean_db, make_user
    ):
        make_user(email="alice@example.com", password="Correct@123")

        r_unknown = client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": "Correct@123"},
        )
        r_wrong_pw = client.post(
            "/api/v1/auth/login",
            json={"email": "alice@example.com", "password": "Wrong@123"},
        )

        assert r_unknown.status_code == 401
        assert r_wrong_pw.status_code == 401
        assert r_unknown.get_json() == r_wrong_pw.get_json()
        assert r_unknown.get_json()["error"]["code"] == "UNAUTHENTICATED"

    def test_disabled_user_cannot_login_returns_403(self, client, clean_db, make_user):
        make_user(email="disabled@example.com", password="Correct@123", is_active=False)
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "disabled@example.com", "password": "Correct@123"},
        )
        assert resp.status_code == 403
        assert resp.get_json()["error"]["code"] == "FORBIDDEN"

    def test_all_seed_users_can_login(self, app, client, clean_db):
        from click.testing import CliRunner

        runner = CliRunner()
        res = runner.invoke(
            app.cli,
            ["seed-demo"],
            env={"FLASK_ENV": "testing", "SEED_PASSWORD": "Demo@1234"},
            catch_exceptions=False,
        )
        assert res.exit_code == 0

        for email, role in [
            ("admin@demo.local", "admin"),
            ("police1@demo.local", "police"),
            ("police2@demo.local", "police"),
            ("citizen@demo.local", "citizen"),
        ]:
            resp = client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "Demo@1234"},
            )
            assert resp.status_code == 200
            data = resp.get_json()["data"]
            assert data["user"]["role"] == role

    def test_me_returns_current_user(self, client, clean_db, make_user, token_for):
        user = make_user(email="me@example.com", role="police")
        token = token_for(user.id, role="police")

        resp = client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["id"] == user.id
        assert data["email"] == "me@example.com"
        assert "password_hash" not in data

    def test_refresh_returns_new_access_token(self, client, clean_db, make_user):
        make_user(email="ref@example.com", password="Password@123", role="police")
        login_resp = client.post(
            "/api/v1/auth/login",
            json={"email": "ref@example.com", "password": "Password@123"},
        )
        tokens = login_resp.get_json()["data"]

        ref_resp = client.post(
            "/api/v1/auth/refresh",
            headers={"Authorization": f"Bearer {tokens['refresh_token']}"},
        )
        assert ref_resp.status_code == 200
        ref_data = ref_resp.get_json()["data"]
        assert "access_token" in ref_data
        assert ref_data["expires_in"] == 3600

        me_resp = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {ref_data['access_token']}"},
        )
        assert me_resp.status_code == 200

    def test_refresh_with_access_token_is_rejected(self, client, clean_db, make_user, token_for):
        user = make_user(email="acc@example.com", role="citizen")
        access = token_for(user.id, role="citizen")

        resp = client.post(
            "/api/v1/auth/refresh",
            headers={"Authorization": f"Bearer {access}"},
        )
        assert resp.status_code == 401
        assert resp.get_json()["error"]["code"] == "UNAUTHENTICATED"

    def test_expired_token_returns_401_envelope(self, app, client, clean_db, make_user):
        from flask_jwt_extended import create_access_token

        user = make_user(email="exp@example.com", role="citizen")
        with app.app_context():
            expired = create_access_token(
                identity=str(user.id),
                additional_claims={"role": "citizen"},
                expires_delta=timedelta(seconds=-10),
            )

        resp = client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"}
        )
        assert resp.status_code == 401
        body = resp.get_json()
        assert body["error"]["code"] == "UNAUTHENTICATED"


class TestTokenDbFreshness:
    def test_disabled_user_token_stops_working_on_next_request(
        self, app, client, clean_db, make_user, token_for
    ):
        from app.extensions import db
        from app.models.models import User

        user = make_user(email="toggle@example.com", role="admin", is_active=True)
        token = token_for(user.id, role="admin")

        # Works initially
        assert (
            client.get(
                "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
            ).status_code
            == 200
        )

        # Disable in DB directly (simulate admin action)
        with app.app_context():
            u = db.session.get(User, user.id)
            u.is_active = False
            db.session.commit()

        # Previously issued token now gets 403 FORBIDDEN
        resp = client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 403
        assert resp.get_json()["error"]["code"] == "FORBIDDEN"

    def test_disabled_user_cannot_refresh(self, app, client, clean_db, make_user):
        from app.extensions import db
        from app.models.models import User

        user = make_user(email="refdis@example.com", password="Password@123", role="citizen")
        login_data = client.post(
            "/api/v1/auth/login",
            json={"email": "refdis@example.com", "password": "Password@123"},
        ).get_json()["data"]

        with app.app_context():
            u = db.session.get(User, user.id)
            u.is_active = False
            db.session.commit()

        resp = client.post(
            "/api/v1/auth/refresh",
            headers={"Authorization": f"Bearer {login_data['refresh_token']}"},
        )
        assert resp.status_code == 403
        assert resp.get_json()["error"]["code"] == "FORBIDDEN"

    def test_demoted_user_token_loses_privileged_routes_immediately(self):
        from datetime import datetime, timezone

        from argon2 import PasswordHasher
        from flask import Blueprint
        from flask_jwt_extended import create_access_token

        from app import create_app
        from app.core.auth import current_user, roles_required
        from app.core.responses import ok
        from app.extensions import db
        from app.models.models import User

        probe_app = create_app(
            config_override={
                "TESTING": True,
                "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                "RATELIMIT_ENABLED": False,
                "JWT_SECRET_KEY": "test-jwt-secret",
                "SECRET_KEY": "test-secret",
            }
        )

        bp = Blueprint("test_police_probe", __name__)

        @bp.get("/test/police-only")
        @roles_required("police")
        def police_only():
            return ok({"role": current_user().role})

        probe_app.register_blueprint(bp, url_prefix="/api/v1")

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with probe_app.app_context():
            db.create_all()
            user = User(
                name="Demote Target",
                email="demote@example.com",
                password_hash=PasswordHasher().hash("Pass@1234"),
                role="admin",
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            db.session.add(user)
            db.session.commit()
            user_id = user.id
            stale_admin_token = create_access_token(
                identity=str(user_id), additional_claims={"role": "admin"}
            )

        with probe_app.test_client() as c:
            assert (
                c.get(
                    "/api/v1/users",
                    headers={"Authorization": f"Bearer {stale_admin_token}"},
                ).status_code
                == 200
            )
            assert (
                c.get(
                    "/api/v1/test/police-only",
                    headers={"Authorization": f"Bearer {stale_admin_token}"},
                ).status_code
                == 200
            )

            # Demote admin -> police: loses admin route, keeps police route
            with probe_app.app_context():
                u = db.session.get(User, user_id)
                u.role = "police"
                db.session.commit()

            assert (
                c.get(
                    "/api/v1/users",
                    headers={"Authorization": f"Bearer {stale_admin_token}"},
                ).status_code
                == 403
            )
            assert (
                c.get(
                    "/api/v1/test/police-only",
                    headers={"Authorization": f"Bearer {stale_admin_token}"},
                ).status_code
                == 200
            )

            # Demote police -> citizen: loses police route too
            with probe_app.app_context():
                u = db.session.get(User, user_id)
                u.role = "citizen"
                db.session.commit()

            assert (
                c.get(
                    "/api/v1/test/police-only",
                    headers={"Authorization": f"Bearer {stale_admin_token}"},
                ).status_code
                == 403
            )

        with probe_app.app_context():
            db.drop_all()


class TestSecretHygiene:
    def test_passwords_and_hashes_never_in_responses_or_logs(
        self, client, clean_db, make_user, token_for, caplog
    ):
        secret_pw = "SuperSecretPwd!987"
        admin = make_user(email="secadmin@example.com", role="admin")
        admin_token = token_for(admin.id, role="admin")

        with caplog.at_level(logging.DEBUG):
            r_reg = client.post(
                "/api/v1/auth/register",
                json={"name": "Sec", "email": "sec@example.com", "password": secret_pw},
            )
            r_login = client.post(
                "/api/v1/auth/login",
                json={"email": "sec@example.com", "password": secret_pw},
            )
            r_bad = client.post(
                "/api/v1/auth/login",
                json={"email": "sec@example.com", "password": secret_pw + "bad"},
            )
            r_create = client.post(
                "/api/v1/users",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={
                    "name": "Cop",
                    "email": "cop@example.com",
                    "password": secret_pw,
                    "role": "police",
                },
            )
            created_id = r_create.get_json()["data"]["id"]
            r_patch = client.patch(
                f"/api/v1/users/{created_id}",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"password": secret_pw},
            )

        for resp in (r_reg, r_login, r_bad, r_create, r_patch):
            body_text = resp.get_data(as_text=True)
            assert secret_pw not in body_text
            assert "$argon2" not in body_text
            assert "password_hash" not in body_text

        all_logs = "\n".join(rec.getMessage() for rec in caplog.records)
        assert secret_pw not in all_logs
        assert "$argon2" not in all_logs
