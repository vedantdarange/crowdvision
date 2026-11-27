"""tests/integration/test_sources.py — Integration tests for Source CRUD endpoints (contract §6.2)."""
from __future__ import annotations

import pytest

_SQUARE = {
    "type": "Polygon",
    "coordinates": [[
        [77.2090, 28.6139],
        [77.2094, 28.6139],
        [77.2094, 28.6143],
        [77.2090, 28.6143],
        [77.2090, 28.6139],
    ]],
}

_SOURCE_KEYS = {
    "id", "zone_id", "name", "kind", "coverage_area_m2",
    "is_active", "status", "last_frame_at", "created_at",
}


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def admin(make_user, clean_db):
    return make_user(name="Admin", email="admin_src@test.local", role="admin")


@pytest.fixture()
def police(make_user, clean_db):
    return make_user(name="Police", email="police_src@test.local", role="police")


@pytest.fixture()
def citizen(make_user, clean_db):
    return make_user(name="Citizen", email="citizen_src@test.local", role="citizen")


@pytest.fixture()
def admin_tok(token_for, admin):
    return token_for(admin.id, role="admin")


@pytest.fixture()
def police_tok(token_for, police):
    return token_for(police.id, role="police")


@pytest.fixture()
def citizen_tok(token_for, citizen):
    return token_for(citizen.id, role="citizen")


@pytest.fixture()
def zone(client, admin_tok, clean_db):
    r = client.post(
        "/api/v1/zones",
        json={"name": "Source Test Zone", "geometry": _SQUARE},
        headers=_auth(admin_tok),
    )
    assert r.status_code == 201
    return r.get_json()["data"]


@pytest.fixture()
def source(client, police_tok, zone):
    r = client.post(
        "/api/v1/sources",
        json={"zone_id": zone["id"], "name": "Cam 01", "kind": "WEBCAM"},
        headers=_auth(police_tok),
    )
    assert r.status_code == 201
    return r.get_json()["data"]


class TestListSources:
    def test_police_can_list_all_and_filtered(self, client, zone, source, police_tok):
        r_all = client.get("/api/v1/sources", headers=_auth(police_tok))
        assert r_all.status_code == 200
        assert source["id"] in [s["id"] for s in r_all.get_json()["data"]]

        r_filt = client.get(f"/api/v1/sources?zone_id={zone['id']}", headers=_auth(police_tok))
        assert r_filt.status_code == 200
        assert [s["id"] for s in r_filt.get_json()["data"]] == [source["id"]]

    def test_citizen_cannot_list(self, client, zone, citizen_tok):
        r = client.get("/api/v1/sources", headers=_auth(citizen_tok))
        assert r.status_code == 403

    def test_404_for_missing_zone_filter(self, client, police_tok, clean_db):
        r = client.get("/api/v1/sources?zone_id=99999", headers=_auth(police_tok))
        assert r.status_code == 404


class TestCreateSource:
    def test_police_happy_path_uses_default_coverage(self, client, zone, police_tok):
        r = client.post(
            "/api/v1/sources",
            json={"zone_id": zone["id"], "name": "Cam 02", "kind": "VIDEO_FILE"},
            headers=_auth(police_tok),
        )
        assert r.status_code == 201
        data = r.get_json()["data"]
        assert set(data.keys()) == _SOURCE_KEYS
        assert data["kind"] == "VIDEO_FILE"
        assert data["status"] == "OFFLINE"
        assert data["last_frame_at"] is None
        assert data["coverage_area_m2"] == pytest.approx(zone["area_m2"], rel=1e-6)

    def test_admin_can_set_coverage(self, client, zone, admin_tok):
        coverage = zone["area_m2"] * 1.5
        r = client.post(
            "/api/v1/sources",
            json={
                "zone_id": zone["id"],
                "name": "Cam Admin",
                "kind": "WEBCAM",
                "coverage_area_m2": coverage,
            },
            headers=_auth(admin_tok),
        )
        assert r.status_code == 201
        assert r.get_json()["data"]["coverage_area_m2"] == pytest.approx(coverage, rel=1e-6)

    def test_police_sending_coverage_403(self, client, zone, police_tok):
        r = client.post(
            "/api/v1/sources",
            json={
                "zone_id": zone["id"],
                "name": "Cam Cop",
                "kind": "WEBCAM",
                "coverage_area_m2": 10.0,
            },
            headers=_auth(police_tok),
        )
        assert r.status_code == 403
        assert r.get_json()["error"]["code"] == "FORBIDDEN"

    def test_coverage_out_of_range_422(self, client, zone, admin_tok):
        r_big = client.post(
            "/api/v1/sources",
            json={
                "zone_id": zone["id"],
                "name": "Cam Big",
                "kind": "WEBCAM",
                "coverage_area_m2": zone["area_m2"] * 2.5,
            },
            headers=_auth(admin_tok),
        )
        assert r_big.status_code == 422

        r_small = client.post(
            "/api/v1/sources",
            json={
                "zone_id": zone["id"],
                "name": "Cam Small",
                "kind": "WEBCAM",
                "coverage_area_m2": 0.5,
            },
            headers=_auth(admin_tok),
        )
        assert r_small.status_code == 422

    def test_404_for_missing_zone(self, client, police_tok, clean_db):
        r = client.post(
            "/api/v1/sources",
            json={"zone_id": 99999, "name": "Cam X", "kind": "WEBCAM"},
            headers=_auth(police_tok),
        )
        assert r.status_code == 404


class TestUpdateAndDeleteSource:
    def test_admin_can_update_and_delete(self, app, client, zone, source, admin_tok, police_tok):
        from app.extensions import db
        from app.models.models import AuditLog

        new_cov = zone["area_m2"] * 1.2
        r_upd = client.patch(
            f"/api/v1/sources/{source['id']}",
            json={"name": "Cam Renamed", "coverage_area_m2": new_cov},
            headers=_auth(admin_tok),
        )
        assert r_upd.status_code == 200
        assert r_upd.get_json()["data"]["name"] == "Cam Renamed"
        assert r_upd.get_json()["data"]["coverage_area_m2"] == pytest.approx(new_cov, rel=1e-6)

        r_del = client.delete(f"/api/v1/sources/{source['id']}", headers=_auth(admin_tok))
        assert r_del.status_code == 204

        # Excluded from active source list
        r_list = client.get(f"/api/v1/sources?zone_id={zone['id']}", headers=_auth(police_tok))
        assert r_list.get_json()["data"] == []

        with app.app_context():
            actions = [a.action for a in db.session.query(AuditLog).order_by(AuditLog.id).all()]
        assert "SOURCE_CREATED" in actions
        assert "SOURCE_UPDATED" in actions
        assert "SOURCE_DELETED" in actions

    def test_police_cannot_patch_or_delete_source(self, client, source, police_tok):
        assert client.patch(
            f"/api/v1/sources/{source['id']}",
            json={"name": "Cop Rename"},
            headers=_auth(police_tok),
        ).status_code == 403
        assert client.delete(
            f"/api/v1/sources/{source['id']}",
            headers=_auth(police_tok),
        ).status_code == 403

    def test_404_for_missing_source(self, client, admin_tok, clean_db):
        assert client.patch("/api/v1/sources/99999", json={"name": "X"}, headers=_auth(admin_tok)).status_code == 404
        assert client.delete("/api/v1/sources/99999", headers=_auth(admin_tok)).status_code == 404
