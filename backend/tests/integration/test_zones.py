"""tests/integration/test_zones.py — Integration tests for Zone CRUD endpoints."""
from __future__ import annotations

import pytest

# Minimal valid polygon: a square near Delhi demo center (~1,900 m²)
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

_PUBLIC_ZONE_KEYS = {
    "zone_id", "name", "geometry", "centroid",
    "level", "trend", "density", "updated_at",
}

_FULL_ZONE_KEYS = {
    "id", "name", "description", "geometry", "centroid",
    "area_m2", "mode", "warning_density", "critical_density",
    "warning_count", "critical_count", "is_active",
    "created_at", "updated_at",
    "level", "trend", "count", "density", "sources",
    "open_alert_id", "live_updated_at",
}


def _make_zone_body(**kwargs):
    base = {
        "name": "Test Zone",
        "description": "A test zone",
        "geometry": _SQUARE,
        "mode": "DENSITY",
        "warning_density": 2.0,
        "critical_density": 4.0,
    }
    base.update(kwargs)
    return base


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def admin(make_user, clean_db):
    return make_user(name="Admin", email="admin_z@test.local", role="admin")


@pytest.fixture()
def police(make_user, clean_db):
    return make_user(name="Police", email="police_z@test.local", role="police")


@pytest.fixture()
def citizen(make_user, clean_db):
    return make_user(name="Citizen", email="citizen_z@test.local", role="citizen")


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
def created_zone(client, admin_tok, clean_db, admin):
    r = client.post("/api/v1/zones", json=_make_zone_body(), headers=_auth(admin_tok))
    assert r.status_code == 201, r.get_json()
    return r.get_json()["data"]


class TestGetZonesLive:
    def test_returns_200_no_auth(self, client, clean_db):
        r = client.get("/api/v1/zones/live")
        assert r.status_code == 200
        assert isinstance(r.get_json()["data"], list)

    def test_active_zones_appear(self, client, clean_db, created_zone):
        r = client.get("/api/v1/zones/live")
        ids = [z["zone_id"] for z in r.get_json()["data"]]
        assert created_zone["id"] in ids

    def test_exact_public_key_set(self, client, clean_db, created_zone):
        r = client.get("/api/v1/zones/live")
        for z in r.get_json()["data"]:
            assert set(z.keys()) == _PUBLIC_ZONE_KEYS
            assert set(z["centroid"].keys()) == {"lat", "lng"}

    def test_all_no_data(self, client, clean_db, created_zone):
        r = client.get("/api/v1/zones/live")
        for z in r.get_json()["data"]:
            assert z["level"] == "NO_DATA"
            assert z["trend"] == "STEADY"
            assert z["density"] is None
            assert z["updated_at"] is None

    def test_soft_deleted_zone_absent(self, client, clean_db, created_zone, admin_tok):
        client.delete(f"/api/v1/zones/{created_zone['id']}", headers=_auth(admin_tok))
        r = client.get("/api/v1/zones/live")
        ids = [z["zone_id"] for z in r.get_json()["data"]]
        assert created_zone["id"] not in ids


class TestGetZonePublic:
    def test_returns_200_public_shape(self, client, clean_db, created_zone):
        r = client.get(f"/api/v1/zones/{created_zone['id']}/public")
        assert r.status_code == 200
        data = r.get_json()["data"]
        assert set(data.keys()) == {"state", "alternatives"}
        assert set(data["state"].keys()) == _PUBLIC_ZONE_KEYS
        assert data["state"]["zone_id"] == created_zone["id"]
        assert data["alternatives"] == []

    def test_404_for_missing_and_deleted(self, client, clean_db, created_zone, admin_tok):
        assert client.get("/api/v1/zones/99999/public").status_code == 404
        client.delete(f"/api/v1/zones/{created_zone['id']}", headers=_auth(admin_tok))
        assert client.get(f"/api/v1/zones/{created_zone['id']}/public").status_code == 404

    def test_alternatives_nearest_safe_helper(self, app, client, clean_db, admin_tok):
        """_find_alternatives picks up to 3 nearest SAFE zones by centroid distance."""
        from app.container import get_container

        zones = []
        for idx in range(5):
            lng_off = idx * 0.001
            geom = {
                "type": "Polygon",
                "coordinates": [[
                    [77.2090 + lng_off, 28.6139],
                    [77.2092 + lng_off, 28.6139],
                    [77.2092 + lng_off, 28.6141],
                    [77.2090 + lng_off, 28.6141],
                    [77.2090 + lng_off, 28.6139],
                ]],
            }
            r = client.post(
                "/api/v1/zones",
                json=_make_zone_body(name=f"AltZone {idx}", geometry=geom),
                headers=_auth(admin_tok),
            )
            assert r.status_code == 201
            zones.append(r.get_json()["data"])

        # zones[0] is target; zones[1..4] are SAFE except zones[1] which is WARNING
        live_states = {
            zones[0]["id"]: {"level": "CRITICAL", "trend": "RISING", "density": 5.0, "count": 50, "live_updated_at": "2026-11-27T05:00:00Z"},
            zones[1]["id"]: {"level": "WARNING", "trend": "STEADY", "density": 3.2, "count": 30, "live_updated_at": "2026-11-27T05:00:00Z"},
            zones[2]["id"]: {"level": "SAFE", "trend": "STEADY", "density": 1.0, "count": 10, "live_updated_at": "2026-11-27T05:00:00Z"},
            zones[3]["id"]: {"level": "SAFE", "trend": "STEADY", "density": 1.2, "count": 12, "live_updated_at": "2026-11-27T05:00:00Z"},
            zones[4]["id"]: {"level": "SAFE", "trend": "STEADY", "density": 0.5, "count": 5, "live_updated_at": "2026-11-27T05:00:00Z"},
        }
        with app.app_context():
            res = get_container().zone_service.get_public(zones[0]["id"], live_states=live_states)
        alts = res["alternatives"]
        assert [a["zone_id"] for a in alts] == [zones[2]["id"], zones[3]["id"], zones[4]["id"]]
        for a in alts:
            assert set(a.keys()) == _PUBLIC_ZONE_KEYS


class TestListAndGetZones:
    def test_police_can_list(self, client, clean_db, created_zone, police_tok):
        r = client.get("/api/v1/zones", headers=_auth(police_tok))
        assert r.status_code == 200
        assert len(r.get_json()["data"]) == 1
        assert set(r.get_json()["data"][0].keys()) == _FULL_ZONE_KEYS

    def test_include_inactive_admin_only(self, client, clean_db, created_zone, admin_tok, police_tok):
        client.delete(f"/api/v1/zones/{created_zone['id']}", headers=_auth(admin_tok))
        # Default excludes inactive
        r_active = client.get("/api/v1/zones", headers=_auth(admin_tok))
        assert r_active.get_json()["data"] == []
        # Admin with include_inactive=true sees it
        r_all = client.get("/api/v1/zones?include_inactive=true", headers=_auth(admin_tok))
        assert r_all.status_code == 200
        assert len(r_all.get_json()["data"]) == 1
        # Police with include_inactive=true gets 403
        r_cop = client.get("/api/v1/zones?include_inactive=true", headers=_auth(police_tok))
        assert r_cop.status_code == 403

    def test_get_zone_police(self, client, clean_db, created_zone, police_tok):
        r = client.get(f"/api/v1/zones/{created_zone['id']}", headers=_auth(police_tok))
        assert r.status_code == 200
        data = r.get_json()["data"]
        assert set(data.keys()) == _FULL_ZONE_KEYS
        assert data["open_alert_id"] is None


class TestCreateZone:
    def test_happy_path_and_defaults_from_settings(self, client, clean_db, admin_tok):
        # Omit thresholds -> defaults 3.0 / 4.0 from settings
        body = {"name": "Defaulted Zone", "geometry": _SQUARE}
        r = client.post("/api/v1/zones", json=body, headers=_auth(admin_tok))
        assert r.status_code == 201
        data = r.get_json()["data"]
        assert data["warning_density"] == 3.0
        assert data["critical_density"] == 4.0
        assert data["area_m2"] > 0

    def test_server_recomputes_area_within_tolerance(self, client, clean_db, admin_tok):
        from app.core.geometry import polygon_area_m2

        server_area = polygon_area_m2(_SQUARE)
        hint = server_area * 1.05  # within 10%
        r = client.post(
            "/api/v1/zones",
            json=_make_zone_body(area_m2=hint),
            headers=_auth(admin_tok),
        )
        assert r.status_code == 201
        assert r.get_json()["data"]["area_m2"] == pytest.approx(server_area, rel=1e-6)

    def test_area_hint_too_far_off_422(self, client, clean_db, admin_tok):
        r = client.post(
            "/api/v1/zones",
            json=_make_zone_body(area_m2=1_000_000.0),
            headers=_auth(admin_tok),
        )
        assert r.status_code == 422
        assert r.get_json()["error"]["code"] == "VALIDATION_ERROR"

    def test_bad_geometry_cases_422(self, client, clean_db, admin_tok):
        # 1. Not closed
        unclosed = {
            "type": "Polygon",
            "coordinates": [[
                [77.2090, 28.6139],
                [77.2094, 28.6139],
                [77.2094, 28.6143],
                [77.2090, 28.6143],
            ]],
        }
        assert client.post("/api/v1/zones", json=_make_zone_body(geometry=unclosed), headers=_auth(admin_tok)).status_code == 422

        # 2. < 3 distinct vertices
        degenerate = {
            "type": "Polygon",
            "coordinates": [[
                [77.2090, 28.6139],
                [77.2094, 28.6139],
                [77.2090, 28.6139],
                [77.2090, 28.6139],
            ]],
        }
        assert client.post("/api/v1/zones", json=_make_zone_body(geometry=degenerate), headers=_auth(admin_tok)).status_code == 422

        # 3. Self-intersecting bowtie (shapely invalid)
        bowtie = {
            "type": "Polygon",
            "coordinates": [[
                [77.2090, 28.6139],
                [77.2094, 28.6143],
                [77.2094, 28.6139],
                [77.2090, 28.6143],
                [77.2090, 28.6139],
            ]],
        }
        assert client.post("/api/v1/zones", json=_make_zone_body(geometry=bowtie), headers=_auth(admin_tok)).status_code == 422

    def test_warning_gte_critical_422(self, client, clean_db, admin_tok):
        r = client.post(
            "/api/v1/zones",
            json=_make_zone_body(warning_density=5.0, critical_density=3.0),
            headers=_auth(admin_tok),
        )
        assert r.status_code == 422

    def test_count_mode_validation(self, client, clean_db, admin_tok):
        # Missing counts -> 422
        r_missing = client.post(
            "/api/v1/zones",
            json=_make_zone_body(mode="COUNT"),
            headers=_auth(admin_tok),
        )
        assert r_missing.status_code == 422

        # warning_count >= critical_count -> 422
        r_bad = client.post(
            "/api/v1/zones",
            json=_make_zone_body(mode="COUNT", warning_count=10, critical_count=5),
            headers=_auth(admin_tok),
        )
        assert r_bad.status_code == 422

        # Valid COUNT zone -> 201
        r_ok = client.post(
            "/api/v1/zones",
            json=_make_zone_body(mode="COUNT", warning_count=8, critical_count=10),
            headers=_auth(admin_tok),
        )
        assert r_ok.status_code == 201

    def test_duplicate_active_name_conflict_and_reuse(self, client, clean_db, created_zone, admin_tok):
        name = created_zone["name"]
        r_dup = client.post("/api/v1/zones", json=_make_zone_body(name=name), headers=_auth(admin_tok))
        assert r_dup.status_code == 409
        assert r_dup.get_json()["error"]["code"] == "CONFLICT"

        client.delete(f"/api/v1/zones/{created_zone['id']}", headers=_auth(admin_tok))
        r_reused = client.post("/api/v1/zones", json=_make_zone_body(name=name), headers=_auth(admin_tok))
        assert r_reused.status_code == 201

    def test_audit_logged(self, app, client, clean_db, created_zone, admin_tok):
        from app.extensions import db
        from app.models.models import AuditLog

        client.patch(f"/api/v1/zones/{created_zone['id']}", json={"name": "Renamed"}, headers=_auth(admin_tok))
        client.delete(f"/api/v1/zones/{created_zone['id']}", headers=_auth(admin_tok))
        with app.app_context():
            actions = [a.action for a in db.session.query(AuditLog).order_by(AuditLog.id).all()]
        assert "ZONE_CREATED" in actions
        assert "ZONE_UPDATED" in actions
        assert "ZONE_DELETED" in actions


class TestUpdateAndDeleteZone:
    def test_patch_happy_and_conflict(self, client, clean_db, admin_tok):
        r1 = client.post("/api/v1/zones", json=_make_zone_body(name="Zone A"), headers=_auth(admin_tok))
        r2 = client.post("/api/v1/zones", json=_make_zone_body(name="Zone B"), headers=_auth(admin_tok))
        z2 = r2.get_json()["data"]
        assert client.patch(f"/api/v1/zones/{z2['id']}", json={"name": "Zone A"}, headers=_auth(admin_tok)).status_code == 409
        r_ok = client.patch(f"/api/v1/zones/{z2['id']}", json={"name": "Zone B2"}, headers=_auth(admin_tok))
        assert r_ok.status_code == 200
        assert r_ok.get_json()["data"]["name"] == "Zone B2"

    def test_conflict_with_open_alert_on_delete(self, app, client, clean_db, created_zone, admin_tok):
        from app.core.time import utcnow
        from app.extensions import db
        from app.models.models import AlertModel

        zone_id = created_zone["id"]
        with app.app_context():
            alert = AlertModel(  # pyrefly: ignore[unexpected-keyword]
                zone_id=zone_id,
                level="WARNING",
                peak_level="WARNING",
                status="NEW",
                condition_active=True,
                peak_density=3.5,
                peak_count=0.0,
                created_at=utcnow(),
            )
            db.session.add(alert)
            db.session.commit()

        r = client.delete(f"/api/v1/zones/{zone_id}", headers=_auth(admin_tok))
        assert r.status_code == 409
        assert r.get_json()["error"]["code"] == "CONFLICT"
