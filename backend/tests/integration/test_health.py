"""tests/integration/test_health.py — /api/v1/health integration tests.

Validates the response shape and checks against contract/examples/health.json
if the frontend side has created fixtures.
"""
from __future__ import annotations

from tests.fixtures.shape import assert_matches_shape, load_fixture

REQUIRED_KEYS = {"status", "db", "detector", "worker_alive", "version"}


class TestHealth:
    def test_returns_200(self, client):
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200

    def test_top_level_shape_has_no_data_envelope(self, client):
        body = client.get("/api/v1/health").get_json()
        assert "data" not in body, f"Contract §6.2 defines top-level health JSON without 'data': {body}"

    def test_required_keys(self, client):
        data = client.get("/api/v1/health").get_json()
        missing = REQUIRED_KEYS - data.keys()
        assert not missing, f"Missing keys in health response: {missing}"

    def test_db_ok(self, client):
        data = client.get("/api/v1/health").get_json()
        assert data["db"] == "ok"

    def test_detector_unavailable(self, client):
        data = client.get("/api/v1/health").get_json()
        assert data["detector"] == "unavailable"

    def test_worker_alive_false(self, client):
        data = client.get("/api/v1/health").get_json()
        assert data["worker_alive"] is False

    def test_version_is_string(self, client):
        data = client.get("/api/v1/health").get_json()
        assert isinstance(data["version"], str)
        assert len(data["version"]) > 0


class TestHealthFixtureShape:
    """Compare response keys and types against the contract fixture shape."""

    _HEALTH_PROPOSAL = {
        "status": "ok",
        "db": "ok",
        "detector": "unavailable",
        "worker_alive": False,
        "version": "0.1.0",
    }

    def test_matches_fixture_shape(self, client):
        body = client.get("/api/v1/health").get_json()
        fixture = load_fixture("health.json") or self._HEALTH_PROPOSAL
        assert_matches_shape(body, fixture)
