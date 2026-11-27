"""tests/integration/test_config.py — Integration tests for Config/Settings/Help endpoints."""
from __future__ import annotations

import pytest


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def admin(make_user, clean_db):
    return make_user(name="Admin", email="admin_cfg@test.local", role="admin")


@pytest.fixture()
def police(make_user, clean_db):
    return make_user(name="Police", email="police_cfg@test.local", role="police")


@pytest.fixture()
def admin_tok(token_for, admin):
    return token_for(admin.id, role="admin")


@pytest.fixture()
def police_tok(token_for, police):
    return token_for(police.id, role="police")


class TestGetConfig:
    def test_public_runtime_config_shape(self, client, clean_db):
        r = client.get("/api/v1/config")
        assert r.status_code == 200
        data = r.get_json()["data"]
        expected = {
            "target_fps", "frame_width", "jpeg_quality",
            "stale_after_s", "vapid_public_key",
            "app_version", "contract_version",
        }
        assert set(data.keys()) == expected
        assert data["vapid_public_key"] is None
        assert data["contract_version"] == "1.1.0"


class TestGetHelpInfo:
    def test_public_help_info_shape(self, client, clean_db):
        r = client.get("/api/v1/help-info")
        assert r.status_code == 200
        data = r.get_json()["data"]
        assert set(data.keys()) == {"emergency_numbers", "medical_points", "exits"}
        assert isinstance(data["emergency_numbers"], list)
        assert len(data["emergency_numbers"]) > 0
        assert {"label", "number"} == set(data["emergency_numbers"][0].keys())


class TestGetSettings:
    def test_admin_can_get_all_settings(self, client, clean_db, admin_tok):
        r = client.get("/api/v1/settings", headers=_auth(admin_tok))
        assert r.status_code == 200
        data = r.get_json()["data"]
        expected = {
            "detect_conf", "smoothing_window", "debounce_s", "clear_s",
            "hysteresis_ratio", "cooldown_s", "escalation_s", "stale_after_s",
            "reraise_after_s", "target_fps", "frame_width", "jpeg_quality",
            "default_warning_density", "default_critical_density", "help_info",
        }
        assert set(data.keys()) == expected
        assert data["reraise_after_s"] == 60

    def test_police_cannot_get(self, client, clean_db, police_tok):
        assert client.get("/api/v1/settings", headers=_auth(police_tok)).status_code == 403

    def test_no_token_401(self, client, clean_db):
        assert client.get("/api/v1/settings").status_code == 401


class TestPatchSettings:
    def test_valid_partial_update_and_audit(self, app, client, clean_db, admin_tok):
        from app.extensions import db
        from app.models.models import AuditLog

        r = client.patch(
            "/api/v1/settings",
            json={"target_fps": 5, "detect_conf": 0.45},
            headers=_auth(admin_tok),
        )
        assert r.status_code == 200
        data = r.get_json()["data"]
        assert data["target_fps"] == 5
        assert data["detect_conf"] == pytest.approx(0.45)

        # Persisted in DB and reflected in /config
        r_cfg = client.get("/api/v1/config")
        assert r_cfg.get_json()["data"]["target_fps"] == 5

        with app.app_context():
            logs = db.session.query(AuditLog).filter_by(action="SETTINGS_UPDATED").all()
            assert len(logs) == 1

    def test_out_of_range_and_cross_threshold_422(self, client, clean_db, admin_tok):
        assert client.patch("/api/v1/settings", json={"target_fps": 50}, headers=_auth(admin_tok)).status_code == 422
        assert client.patch("/api/v1/settings", json={"reraise_after_s": 5}, headers=_auth(admin_tok)).status_code == 422
        assert client.patch("/api/v1/settings", json={"default_warning_density": 5.0}, headers=_auth(admin_tok)).status_code == 422

    def test_police_cannot_patch(self, client, clean_db, police_tok):
        assert client.patch("/api/v1/settings", json={"target_fps": 3}, headers=_auth(police_tok)).status_code == 403
