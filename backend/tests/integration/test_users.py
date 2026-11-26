"""tests/integration/test_users.py — /api/v1/users CRUD, self-protection, and audit logs."""
from __future__ import annotations

import json


class TestUsersEndpoints:
    def test_list_users_filters_and_pagination(self, client, clean_db, make_user, token_for):
        admin = make_user(name="Admin One", email="admin@test.local", role="admin")
        make_user(name="Police Alpha", email="alpha@test.local", role="police", is_active=True)
        make_user(name="Police Beta", email="beta@test.local", role="police", is_active=False)
        make_user(name="Citizen Jane", email="jane@test.local", role="citizen", is_active=True)
        headers = {"Authorization": f"Bearer {token_for(admin.id, role='admin')}"}

        # Filter by role + is_active
        r1 = client.get("/api/v1/users?role=police&is_active=true", headers=headers)
        assert r1.status_code == 200
        body1 = r1.get_json()
        assert len(body1["data"]) == 1
        assert body1["data"][0]["email"] == "alpha@test.local"
        assert body1["pagination"]["total"] == 1

        # Filter by q substring
        r2 = client.get("/api/v1/users?q=beta", headers=headers)
        assert r2.status_code == 200
        assert len(r2.get_json()["data"]) == 1
        assert r2.get_json()["data"][0]["email"] == "beta@test.local"

        # Pagination limit
        r3 = client.get("/api/v1/users?page=1&limit=2", headers=headers)
        assert r3.status_code == 200
        body3 = r3.get_json()
        assert len(body3["data"]) == 2
        assert body3["pagination"]["total"] == 4
        assert body3["pagination"]["total_pages"] == 2

    def test_create_user_writes_audit_log_without_password(
        self, app, client, clean_db, make_user, token_for
    ):
        from app.extensions import db
        from app.models.models import AuditLog

        admin = make_user(email="admin@test.local", role="admin")
        headers = {"Authorization": f"Bearer {token_for(admin.id, role='admin')}"}

        resp = client.post(
            "/api/v1/users",
            headers=headers,
            json={
                "name": "Officer One",
                "email": "officer1@test.local",
                "password": "OfficerPass@1",
                "role": "police",
            },
        )
        assert resp.status_code == 201
        created_user = resp.get_json()["data"]
        assert created_user["role"] == "police"
        assert "password_hash" not in created_user

        with app.app_context():
            logs = db.session.query(AuditLog).filter_by(action="USER_CREATED").all()
            assert len(logs) == 1
            assert logs[0].actor_id == admin.id
            assert logs[0].entity_type == "user"
            assert logs[0].entity_id == created_user["id"]
            assert "OfficerPass@1" not in logs[0].data_json

    def test_create_user_cannot_create_citizen_or_duplicate(
        self, client, clean_db, make_user, token_for
    ):
        admin = make_user(email="admin@test.local", role="admin")
        headers = {"Authorization": f"Bearer {token_for(admin.id, role='admin')}"}

        r_cit = client.post(
            "/api/v1/users",
            headers=headers,
            json={
                "name": "Cit",
                "email": "cit@test.local",
                "password": "Password@123",
                "role": "citizen",
            },
        )
        assert r_cit.status_code == 422

        r_dup = client.post(
            "/api/v1/users",
            headers=headers,
            json={
                "name": "Dup",
                "email": "ADMIN@test.local",
                "password": "Password@123",
                "role": "admin",
            },
        )
        assert r_dup.status_code == 409

    def test_patch_user_updates_and_audits(
        self, app, client, clean_db, make_user, token_for
    ):
        from app.extensions import db
        from app.models.models import AuditLog

        admin = make_user(email="admin@test.local", role="admin")
        target = make_user(name="Old Name", email="cop@test.local", role="police")
        headers = {"Authorization": f"Bearer {token_for(admin.id, role='admin')}"}

        resp = client.patch(
            f"/api/v1/users/{target.id}",
            headers=headers,
            json={"name": "New Name", "role": "admin", "password": "NewPass@123"},
        )
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["name"] == "New Name"
        assert data["role"] == "admin"

        with app.app_context():
            log = db.session.query(AuditLog).filter_by(action="USER_UPDATED").first()
            assert log is not None
            assert log.entity_id == target.id
            parsed = json.loads(log.data_json)
            assert parsed["name"] == "New Name"
            assert parsed["role"] == "admin"
            assert parsed["password_changed"] is True
            assert "NewPass@123" not in log.data_json

    def test_admin_cannot_disable_or_demote_self_returns_409(
        self, client, clean_db, make_user, token_for
    ):
        admin = make_user(email="admin@test.local", role="admin")
        headers = {"Authorization": f"Bearer {token_for(admin.id, role='admin')}"}

        r_disable = client.patch(
            f"/api/v1/users/{admin.id}",
            headers=headers,
            json={"is_active": False},
        )
        assert r_disable.status_code == 409
        assert r_disable.get_json()["error"]["code"] == "CONFLICT"

        r_demote = client.patch(
            f"/api/v1/users/{admin.id}",
            headers=headers,
            json={"role": "police"},
        )
        assert r_demote.status_code == 409
        assert r_demote.get_json()["error"]["code"] == "CONFLICT"

    def test_patch_unknown_user_returns_404(self, client, clean_db, make_user, token_for):
        admin = make_user(email="admin@test.local", role="admin")
        headers = {"Authorization": f"Bearer {token_for(admin.id, role='admin')}"}

        resp = client.patch("/api/v1/users/999999", headers=headers, json={"name": "X"})
        assert resp.status_code == 404
        assert resp.get_json()["error"]["code"] == "NOT_FOUND"
