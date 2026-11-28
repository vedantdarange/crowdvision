"""tests/integration/test_role_matrix.py — Parametrized RBAC matrix for ALL routes.

Every route in the API is listed in ROUTE_MATRIX with its required role level:
  - 'public'  : no token needed
  - 'refresh' : refresh token required
  - 'citizen' : any active logged-in user (citizen, police, admin)
  - 'police'  : police or admin
  - 'admin'   : admin only

As new routes are added in B5+, append them to ROUTE_MATRIX.
"""
from __future__ import annotations

import io
from typing import Any
from unittest.mock import patch

import pytest

_RM_POLYGON = {
    "type": "Polygon",
    "coordinates": [[
        [77.2090, 28.6139],
        [77.2094, 28.6139],
        [77.2094, 28.6143],
        [77.2090, 28.6143],
        [77.2090, 28.6139],
    ]],
}

_ZONE_BODY = {
    "name": "RM Created Zone",
    "description": "",
    "geometry": _RM_POLYGON,
    "mode": "DENSITY",
    "warning_density": 2.0,
    "critical_density": 4.0,
}

# (method, path_or_template, required_level, json_body_for_allowed)
ROUTE_MATRIX: list[tuple[str, str, str, dict[str, Any] | None]] = [
    # --- B0 ---
    ("GET", "/api/v1/health", "public", None),
    # --- B1 Auth & Users ---
    (
        "POST",
        "/api/v1/auth/register",
        "public",
        {"name": "Matrix User", "email": "matrix_reg@test.local", "password": "Password@123"},
    ),
    (
        "POST",
        "/api/v1/auth/login",
        "public",
        {"email": "citizen@test.local", "password": "Password@123"},
    ),
    ("POST", "/api/v1/auth/refresh", "refresh", None),
    ("GET", "/api/v1/auth/me", "citizen", None),
    ("GET", "/api/v1/users", "admin", None),
    (
        "POST",
        "/api/v1/users",
        "admin",
        {
            "name": "New Police",
            "email": "matrix_cop@test.local",
            "password": "Password@123",
            "role": "police",
        },
    ),
    ("PATCH", "/api/v1/users/{target_id}", "admin", {"name": "Updated Target"}),
    # --- B2 Zones ---
    ("GET", "/api/v1/zones/live", "public", None),
    ("GET", "/api/v1/zones/{zone_id}/public", "public", None),
    ("GET", "/api/v1/zones/{zone_id}/history", "police", None),
    ("GET", "/api/v1/zones", "police", None),
    ("GET", "/api/v1/zones/{zone_id}", "police", None),
    ("POST", "/api/v1/zones", "admin", _ZONE_BODY),
    ("PATCH", "/api/v1/zones/{zone_id}", "admin", {"name": "Updated RM Zone"}),
    ("DELETE", "/api/v1/zones/{zone_id}", "admin", None),
    # --- B2 Sources ---
    ("GET", "/api/v1/sources", "police", None),
    ("POST", "/api/v1/sources", "police", {"zone_id": "{zone_id}", "name": "Cam RM", "kind": "WEBCAM"}),
    ("PATCH", "/api/v1/sources/{source_id}", "admin", {"name": "Cam RM Updated"}),
    ("DELETE", "/api/v1/sources/{source_id}", "admin", None),
    # --- B2 Config & Settings ---
    ("GET", "/api/v1/config", "public", None),
    ("GET", "/api/v1/help-info", "public", None),
    ("GET", "/api/v1/settings", "admin", None),
    ("PATCH", "/api/v1/settings", "admin", {"target_fps": 3}),
    # --- B4b Alerts ---
    ("GET", "/api/v1/alerts", "police", None),
    ("GET", "/api/v1/alerts/{alert_id}", "police", None),
    ("POST", "/api/v1/alerts/{alert_id}/acknowledge", "police", {"note": "ack"}),
    ("POST", "/api/v1/alerts/{alert_id}/respond", "police", {"note": "resp"}),
    ("POST", "/api/v1/alerts/{alert_id}/resolve", "police", {"note": "res"}),
    # --- B4b Advisories ---
    ("GET", "/api/v1/advisories", "public", None),
    ("POST", "/api/v1/advisories", "police", {"title": "Notice", "body": "Clear", "severity": "INFO"}),
    ("DELETE", "/api/v1/advisories/{advisory_id}", "police", None),
    # --- B6 Web Push ---
    (
        "POST",
        "/api/v1/push/subscriptions",
        "police",
        {
            "endpoint": "https://push.example.com/sub/rm",
            "keys": {"p256dh": "test-p256dh-key", "auth": "test-auth-secret"},
        },
    ),
    ("DELETE", "/api/v1/push/subscriptions?endpoint=https%3A%2F%2Fpush.example.com%2Fsub%2Frm", "police", None),
    ("POST", "/api/v1/push/test", "police", None),
    # --- B7 Citizen Reports ---
    ("POST", "/api/v1/reports/crowd", "citizen", None),
    (
        "POST",
        "/api/v1/reports/sos",
        "citizen",
        {"sos_type": "MEDICAL", "lat": 28.6141, "lng": 77.2092, "note": "Need medic"},
    ),
    ("GET", "/api/v1/reports/mine", "citizen", None),
    ("GET", "/api/v1/reports", "police", None),
    ("PATCH", "/api/v1/reports/{report_id}", "police", {"status": "VERIFIED", "review_note": "ok"}),
    # --- B8 Analytics & Audit ---
    ("GET", "/api/v1/analytics/summary", "police", None),
    ("GET", "/api/v1/analytics/export/alerts.csv", "admin", None),
    ("GET", "/api/v1/audit-logs", "admin", None),
]

_ALLOWED_ROLES = {
    "citizen": {"citizen", "police", "admin"},
    "police": {"police", "admin"},
    "admin": {"admin"},
}


@pytest.mark.parametrize("method,path_tpl,level,body", ROUTE_MATRIX)
def test_route_role_matrix(
    app, client, clean_db, make_user, token_for, method, path_tpl, level, body
):
    from flask_jwt_extended import create_refresh_token

    from app.core.time import utcnow
    from app.detection.protocol import DetectResult
    from app.extensions import db
    from app.models.models import Advisory, AlertModel, Report

    citizen = make_user(
        name="Cit", email="citizen@test.local", password="Password@123", role="citizen"
    )
    police = make_user(name="Pol", email="police@test.local", role="police")
    admin = make_user(name="Adm", email="admin@test.local", role="admin")
    target = make_user(name="Target", email="target@test.local", role="police")

    tokens_by_role = {
        "citizen": token_for(citizen.id, role="citizen"),
        "police": token_for(police.id, role="police"),
        "admin": token_for(admin.id, role="admin"),
    }

    zone_id = 1
    source_id = 1
    alert_id = 1
    advisory_id = 1
    report_id = 1

    needs_zone = (
        "{zone_id}" in path_tpl
        or (body and body.get("zone_id") == "{zone_id}")
        or "{source_id}" in path_tpl
        or "{alert_id}" in path_tpl
    )
    needs_source = "{source_id}" in path_tpl
    needs_alert = "{alert_id}" in path_tpl
    needs_advisory = "{advisory_id}" in path_tpl
    needs_report = "{report_id}" in path_tpl

    if needs_zone:
        r_z = client.post(
            "/api/v1/zones",
            json={**_ZONE_BODY, "name": "RM Seed Zone"},
            headers={"Authorization": f"Bearer {tokens_by_role['admin']}"},
        )
        assert r_z.status_code == 201
        zone_id = r_z.get_json()["data"]["id"]

    if needs_source:
        r_s = client.post(
            "/api/v1/sources",
            json={"zone_id": zone_id, "name": "RM Seed Source", "kind": "WEBCAM"},
            headers={"Authorization": f"Bearer {tokens_by_role['admin']}"},
        )
        assert r_s.status_code == 201
        source_id = r_s.get_json()["data"]["id"]

    if needs_alert:
        with app.app_context():
            now_naive = utcnow().replace(tzinfo=None)
            a = AlertModel(  # pyrefly: ignore[unexpected-keyword]
                zone_id=zone_id,
                level="WARNING",
                peak_level="WARNING",
                status="NEW",
                condition_active=True,
                peak_density=3.2,
                peak_count=4.0,
                created_at=now_naive,
            )
            db.session.add(a)
            db.session.commit()
            alert_id = a.id

    if needs_advisory:
        with app.app_context():
            now_naive = utcnow().replace(tzinfo=None)
            adv = Advisory(  # pyrefly: ignore[unexpected-keyword]
                title="RM Adv",
                body="Seed adv",
                severity="INFO",
                zone_id=None,
                created_by=police.id,
                created_at=now_naive,
                is_active=True,
            )
            db.session.add(adv)
            db.session.commit()
            advisory_id = adv.id

    if needs_report:
        with app.app_context():
            now_naive = utcnow().replace(tzinfo=None)
            rep = Report(  # pyrefly: ignore[unexpected-keyword]
                kind="SOS",
                status="PENDING",
                zone_id=None,
                lat=28.6141,
                lng=77.2092,
                sos_type="MEDICAL",
                note="RM report",
                created_by=citizen.id,
                created_at=now_naive,
            )
            db.session.add(rep)
            db.session.commit()
            report_id = rep.id

    path = path_tpl.format(
        target_id=target.id,
        zone_id=zone_id,
        source_id=source_id,
        alert_id=alert_id,
        advisory_id=advisory_id,
        report_id=report_id,
    )
    resolved_body = dict(body) if body is not None else None
    if resolved_body and resolved_body.get("zone_id") == "{zone_id}":
        resolved_body["zone_id"] = zone_id

    if level == "public":
        resp = client.open(path, method=method, json=resolved_body)
        assert resp.status_code in (200, 201), f"{method} {path}: got {resp.status_code}"
        return

    if level == "refresh":
        r_no_tok = client.open(path, method=method)
        assert r_no_tok.status_code == 401
        assert r_no_tok.get_json()["error"]["code"] == "UNAUTHENTICATED"

        r_acc = client.open(
            path, method=method, headers={"Authorization": f"Bearer {tokens_by_role['citizen']}"}
        )
        assert r_acc.status_code == 401

        with app.app_context():
            ref = create_refresh_token(identity=str(citizen.id))
        r_ok = client.open(path, method=method, headers={"Authorization": f"Bearer {ref}"})
        assert r_ok.status_code == 200
        return

    is_crowd_multipart = method == "POST" and path == "/api/v1/reports/crowd"
    _jpeg_stub = b"\xff\xd8\xff\xe0" + b"\x00" * 32

    if is_crowd_multipart:
        r_unauth = client.post(
            path,
            data={"lat": "28.6141", "lng": "77.2092", "image": (io.BytesIO(_jpeg_stub), "c.jpg")},
            content_type="multipart/form-data",
        )
    else:
        r_unauth = client.open(path, method=method, json=resolved_body)
    assert r_unauth.status_code == 401, f"{method} {path} no token: {r_unauth.status_code}"
    assert r_unauth.get_json()["error"]["code"] == "UNAUTHENTICATED"

    allowed = _ALLOWED_ROLES[level]
    ordered_roles = [r for r in tokens_by_role if r not in allowed] + [
        r for r in tokens_by_role if r in allowed
    ]
    for role_name in ordered_roles:
        tok = tokens_by_role[role_name]
        req_body = dict(resolved_body) if resolved_body is not None else None
        if method == "POST" and path == "/api/v1/sources" and req_body is not None:
            req_body["name"] = f"Cam RM {role_name}"
        # Re-create active advisory between police & admin DELETE calls so both 204
        if method == "DELETE" and "/advisories/" in path and role_name == "admin":
            with app.app_context():
                adv_row = db.session.get(Advisory, advisory_id)
                if adv_row is not None:
                    adv_row.is_active = True
                    db.session.commit()
        # Reset report back to PENDING between police & admin PATCH calls so both 200
        if method == "PATCH" and "/reports/" in path and role_name == "admin":
            with app.app_context():
                rep_row = db.session.get(Report, report_id)
                if rep_row is not None:
                    rep_row.status = "PENDING"
                    rep_row.reviewed_by = None
                    rep_row.reviewed_at = None
                    db.session.commit()
        if is_crowd_multipart:
            fake_res = DetectResult(
                source_id=-1, seq=1, ok=True, error=None, count=2, boxes=[], infer_ms=1.0, request_id=1
            )
            with patch.object(
                app.extensions["container"].detection_manager,
                "detect_once",
                return_value=fake_res,
            ):
                resp = client.post(
                    path,
                    headers={"Authorization": f"Bearer {tok}"},
                    data={
                        "lat": "28.6141",
                        "lng": "77.2092",
                        "image": (io.BytesIO(_jpeg_stub), "c.jpg"),
                    },
                    content_type="multipart/form-data",
                )
        else:
            resp = client.open(
                path,
                method=method,
                headers={"Authorization": f"Bearer {tok}"},
                json=req_body,
            )
        if role_name in allowed:
            assert resp.status_code in (200, 201, 204), (
                f"{method} {path} as {role_name}: expected success, got {resp.status_code} {resp.get_json()}"
            )
        else:
            assert resp.status_code == 403, (
                f"{method} {path} as {role_name}: expected 403, got {resp.status_code}"
            )
            assert resp.get_json()["error"]["code"] == "FORBIDDEN"
