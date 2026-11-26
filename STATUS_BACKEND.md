# Backend status — updated 2026-11-27 01:43 IST
## Phase: B1 (done)
## Done since last update
- Implemented strict layered B1 stack (`blueprint -> service -> repository -> model`) on branch `be/b1-auth`:
  - Validation & schemas: `app/core/validation.py` (`parse_json_body`, `validate`), `app/schemas/auth.py`, `app/schemas/users.py` (`serialize_user`, never exposes `password_hash`).
  - Repositories: `app/repositories/user_repo.py`, `app/repositories/audit_repo.py`.
  - Services: `app/services/audit_service.py`, `app/services/auth_service.py` (argon2 hashing, generic 401 on login mismatch, disabled user -> 403, refresh re-checks `is_active` and DB role), `app/services/user_service.py` (admin user creation, self-disable/self-demote -> 409 CONFLICT, `USER_CREATED` and `USER_UPDATED` audit logs without passwords).
  - RBAC & JWT: `app/core/auth.py` (`roles_required` with single hierarchy rule `admin` satisfies `police`, re-reads DB user/role/`is_active` on every request, exposes `g.current_user`; `configure_jwt_error_loaders` routes missing/invalid/expired/wrong-type JWT errors through our `401 UNAUTHENTICATED` contract envelope).
  - DI & Routes: `app/container.py` (`Container`, `wire(flask_app)`), `app/api/v1/auth.py` (`/register`, `/login`, `/refresh`, `/me`), `app/api/v1/users.py` (`GET /users`, `POST /users`, `PATCH /users/{id}`).
  - Rate limiting: `Flask-Limiter` on `/auth/register` (`10/hour`, configurable via `RATELIMIT_REGISTER`) and `/auth/login` (`20/minute`, configurable via `RATELIMIT_LOGIN`), returning `429 RATE_LIMITED` in our envelope and keyed on `request.remote_addr` (real client IP after `ProxyFix`). Removed global default limit so non-auth endpoints are unaffected.
- Added and ran B1 tests: `tests/unit/test_auth_unit.py`, `tests/integration/test_auth.py`, `tests/integration/test_users.py`, `tests/integration/test_role_matrix.py`, `tests/integration/test_rate_limit.py`.
- Fixed `tests/conftest.py` `app` fixture so `app_context` is closed after `db.create_all()`, ensuring per-request session teardown (`db.session.remove()`) runs cleanly between requests.

## In progress
- None (Phase B1 complete on `be/b1-auth`, awaiting Phase B2).

## Blocked / questions for Person A
- `contract/examples/` still does not contain fixtures from AI-B (`health`, `user`, `auth`, `error_*`).

## Requests for AI-B (frontend)
- Please create `contract/examples/` fixtures (`health.json`, `user.json`, `error_*.json`) and `contract/CONTRACT_VERSION` (`1.1.0`) when ready; backend can now serve real `/auth/*` and `/users/*` endpoints.

## Untested / known issues
- `flask set-password` failure cases (unknown email, password < 8 chars) and `413 PAYLOAD_TOO_LARGE` (>5 MB upload) remain untested (carried from B0).
- `TestSQLitePragmas.test_journal_mode_wal` skips on `:memory:` SQLite (WAL mode is verified separately in `test_journal_mode_wal_on_file_db`).
- Run all `flask` CLI commands from `backend/` so Flask discovers `wsgi.py`.

## Next 3 steps
1. Review and merge `be/b1-auth` into `main`.
2. Begin Phase B2 (M2): Zones, sources, settings, config, help-info CRUD + Socket.IO connect/`hello`/`auth:expired`/session registry.
3. Extend `tests/integration/test_role_matrix.py` (`ROUTE_MATRIX`) with all B2 endpoints.

## Numbers (latency, MAE, coverage) once available
- Not yet measured (B5 / B9).
