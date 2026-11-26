"""tests/integration/test_role_matrix.py — Parametrized RBAC matrix for ALL routes.

Every route in the API is listed in ROUTE_MATRIX with its required role level:
  - 'public'  : no token needed
  - 'refresh' : refresh token required
  - 'citizen' : any active logged-in user (citizen, police, admin)
  - 'police'  : police or admin
  - 'admin'   : admin only

As new routes are added in B2+, append them to ROUTE_MATRIX.
"""
from __future__ import annotations

from typing import Any

import pytest

# (method, path_or_template, required_level, json_body_for_allowed)
ROUTE_MATRIX: list[tuple[str, str, str, dict[str, Any] | None]] = [
    ("GET", "/api/v1/health", "public", None),
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

    citizen = make_user(
        name="Cit", email="citizen@test.local", password="Password@123", role="citizen"
    )
    police = make_user(name="Pol", email="police@test.local", role="police")
    admin = make_user(name="Adm", email="admin@test.local", role="admin")
    target = make_user(name="Target", email="target@test.local", role="police")

    path = path_tpl.format(target_id=target.id)

    tokens_by_role = {
        "citizen": token_for(citizen.id, role="citizen"),
        "police": token_for(police.id, role="police"),
        "admin": token_for(admin.id, role="admin"),
    }

    if level == "public":
        resp = client.open(path, method=method, json=body)
        assert resp.status_code in (200, 201), f"{method} {path}: got {resp.status_code}"
        return

    if level == "refresh":
        # No token -> 401
        r_no_tok = client.open(path, method=method)
        assert r_no_tok.status_code == 401
        assert r_no_tok.get_json()["error"]["code"] == "UNAUTHENTICATED"

        # Access token -> 401
        r_acc = client.open(
            path, method=method, headers={"Authorization": f"Bearer {tokens_by_role['citizen']}"}
        )
        assert r_acc.status_code == 401

        # Refresh token -> 200
        with app.app_context():
            ref = create_refresh_token(identity=str(citizen.id))
        r_ok = client.open(path, method=method, headers={"Authorization": f"Bearer {ref}"})
        assert r_ok.status_code == 200
        return

    # Protected access-token route
    # 1. Missing token -> 401 UNAUTHENTICATED
    r_unauth = client.open(path, method=method, json=body)
    assert r_unauth.status_code == 401, f"{method} {path} no token: {r_unauth.status_code}"
    assert r_unauth.get_json()["error"]["code"] == "UNAUTHENTICATED"

    # 2. Check every role
    allowed = _ALLOWED_ROLES[level]
    for role_name, tok in tokens_by_role.items():
        resp = client.open(
            path,
            method=method,
            headers={"Authorization": f"Bearer {tok}"},
            json=body,
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
