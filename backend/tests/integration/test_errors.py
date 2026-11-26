"""tests/integration/test_errors.py — Global error handler & middleware tests.

Covers:
- 404 returns contract error envelope
- 405 returns contract error envelope
- Deliberately raised AppError returns correct code/status
- Pydantic ValidationError returns 422 VALIDATION_ERROR with field details
- Unexpected exception returns 500 INTERNAL (no stack trace in body)
- MemoryRequest always keeps uploads in RAM (io.BytesIO, never temp files)
- ProxyFix honours X-Forwarded-For when TRUSTED_PROXY_COUNT=1
"""
from __future__ import annotations

import io

import pytest
from pydantic import BaseModel, Field

from app.core.errors import Conflict


class _SamplePayload(BaseModel):
    count: int = Field(ge=1)


def _register_test_routes(app):
    """Add ephemeral routes for error testing (called once from fixture)."""
    from flask import Blueprint, request

    bp = Blueprint("test_errors_bp", __name__)

    @bp.get("/test/raise-app-error")
    def raise_app_error():
        raise Conflict("Zone name already taken")

    @bp.get("/test/raise-unexpected")
    def raise_unexpected():
        raise RuntimeError("boom — unexpected")

    @bp.post("/test/validate")
    def validate_payload():
        _SamplePayload.model_validate(request.get_json(force=True))
        return {"data": "ok"}, 200

    @bp.post("/test/upload")
    def upload_file():
        f = request.files["image"]
        is_bytes_io = isinstance(f.stream, io.BytesIO)
        return {"data": {"is_bytes_io": is_bytes_io, "size": len(f.read())}}, 200

    @bp.get("/test/client-ip")
    def client_ip():
        return {"data": {"ip": request.remote_addr}}, 200

    app.register_blueprint(bp, url_prefix="/api/v1")


class TestErrorEnvelopes:
    @pytest.fixture(autouse=True, scope="class")
    def _routes(self, app):
        _register_test_routes(app)

    def test_404_envelope(self, client):
        resp = client.get("/api/v1/does-not-exist-xyz")
        assert resp.status_code == 404
        body = resp.get_json()
        assert "error" in body
        assert body["error"]["code"] == "NOT_FOUND"
        assert "message" in body["error"]

    def test_405_envelope(self, client):
        resp = client.post("/api/v1/health")
        assert resp.status_code == 405
        body = resp.get_json()
        assert "error" in body
        assert body["error"]["code"] == "METHOD_NOT_ALLOWED"

    def test_app_error_envelope(self, client):
        resp = client.get("/api/v1/test/raise-app-error")
        assert resp.status_code == 409
        body = resp.get_json()
        assert body["error"]["code"] == "CONFLICT"
        assert "Zone name already taken" in body["error"]["message"]

    def test_pydantic_validation_error_envelope(self, client):
        resp = client.post("/api/v1/test/validate", json={"count": -1})
        assert resp.status_code == 422
        body = resp.get_json()
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert "count" in body["error"]["details"]

    def test_unexpected_exception_returns_500(self, client):
        resp = client.get("/api/v1/test/raise-unexpected")
        assert resp.status_code == 500
        body = resp.get_json()
        assert body["error"]["code"] == "INTERNAL"
        assert "boom" not in body["error"]["message"].lower()

    def test_no_stack_trace_in_error_body(self, client):
        resp = client.get("/api/v1/test/raise-unexpected")
        text = resp.get_data(as_text=True)
        assert "Traceback" not in text
        assert "RuntimeError" not in text

    def test_large_upload_stays_in_memory(self, client):
        """Uploads > 500 KB must use io.BytesIO and never spool to disk."""
        payload = b"x" * (600 * 1024)  # 600 KB (> Werkzeug's 500 KB spool threshold)
        resp = client.post(
            "/api/v1/test/upload",
            data={"image": (io.BytesIO(payload), "test.jpg")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["is_bytes_io"] is True
        assert data["size"] == len(payload)


class TestProxyFix:
    def test_trusted_proxy_count_1_uses_x_forwarded_for(self, monkeypatch):
        monkeypatch.setenv("TRUSTED_PROXY_COUNT", "1")
        monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
        from app import create_app

        proxy_app = create_app({"TESTING": True, "RATELIMIT_ENABLED": False})

        @proxy_app.get("/api/v1/test-ip")
        def _ip():
            from flask import request
            return {"data": {"ip": request.remote_addr}}, 200

        with proxy_app.test_client() as c:
            resp = c.get("/api/v1/test-ip", headers={"X-Forwarded-For": "203.0.113.42"})
            assert resp.status_code == 200
            assert resp.get_json()["data"]["ip"] == "203.0.113.42"
