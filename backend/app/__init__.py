"""app/__init__.py — Application factory.

create_app(config_override=None) is the entry point for Flask, Gunicorn,
and pytest fixtures. It wires extensions, registers blueprints, attaches
the global error handler, and applies security middleware.
"""
from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any

import flask
from flask import Flask, Response, g, make_response, request, send_from_directory
from pydantic import ValidationError as PydanticValidationError
from werkzeug.exceptions import (
    BadRequest as WerkzeugBadRequest,
    HTTPException,
    MethodNotAllowed as WerkzeugMethodNotAllowed,
    NotFound as WerkzeugNotFound,
    RequestEntityTooLarge,
)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import safe_join

from app.config import BACKEND_DIR, load_settings, normalize_sqlite_url
from app.container import wire
from app.core.auth import configure_jwt_error_loaders
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.core.responses import error_response
from app.extensions import cors, db, jwt, limiter, migrate, socketio

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# In-memory upload stream factory (plan §6.1 / pitfall #12)
# Werkzeug spools uploaded files > 500 KB to a tmp file by default.
# We override _get_file_stream so images are ALWAYS kept in RAM and
# never written to disk — required by the privacy contract.
# ---------------------------------------------------------------------------
class MemoryRequest(flask.Request):
    def _get_file_stream(
        self,
        total_content_length: int | None,
        content_type: str | None,
        filename: str | None = None,
        content_length: int | None = None,
    ) -> io.BytesIO:
        return io.BytesIO()


def _format_pydantic_details(exc: PydanticValidationError) -> dict[str, list[str]]:
    details: dict[str, list[str]] = {}
    for err in exc.errors():
        loc = ".".join(str(part) for part in err.get("loc", ())) or "_root"
        details.setdefault(loc, []).append(err.get("msg", "Invalid value"))
    return details


_DEFAULT_SEED_PASSWORD = "Demo@1234"


def _enforce_no_default_admin_passwords(flask_app: Flask) -> None:
    """Refuse startup with SERVE_FRONTEND=true if any admin still uses the default password."""
    from argon2 import PasswordHasher
    from argon2.exceptions import InvalidHashError, VerifyMismatchError
    from sqlalchemy import inspect as sa_inspect

    from app.models.models import User

    with flask_app.app_context():
        inspector = sa_inspect(db.engine)
        if not inspector.has_table("users"):
            return
        admins = db.session.query(User).filter(User.role == "admin").all()
        if not admins:
            return
        ph = PasswordHasher()
        insecure_emails: list[str] = []
        for admin in admins:
            try:
                if ph.verify(admin.password_hash, _DEFAULT_SEED_PASSWORD):
                    insecure_emails.append(admin.email)
            except (VerifyMismatchError, InvalidHashError, ValueError):
                continue
        if insecure_emails:
            joined = ", ".join(insecure_emails)
            msg = (
                f"Refusing to start with SERVE_FRONTEND=true: admin account(s) ({joined}) "
                f"still use the default seed password ({_DEFAULT_SEED_PASSWORD}). "
                f"Run 'flask set-password <email>' to change it, or set ALLOW_DEFAULT_PASSWORDS=true."
            )
            logger.error(msg)
            raise RuntimeError(msg)


def _try_serve_spa(flask_app: Flask, path: str) -> Response | None:
    """Serve built frontend/dist file or SPA index.html when SERVE_FRONTEND=true."""
    rel = path.lstrip("/")
    if (
        rel == "api"
        or rel.startswith("api/")
        or rel == "socket.io"
        or rel.startswith("socket.io/")
    ):
        return None

    dist_dir = Path(str(flask_app.config["FRONTEND_DIST_DIR"])).resolve()
    if rel:
        joined = safe_join(str(dist_dir), rel)
        if joined is not None:
            candidate = Path(joined)
            if candidate.is_file():
                resp = make_response(send_from_directory(dist_dir, rel))
                if rel in ("sw.js", "index.html"):
                    resp.headers["Cache-Control"] = "no-cache"
                elif rel.startswith("assets/"):
                    resp.headers["Cache-Control"] = (
                        "public, max-age=31536000, immutable"
                    )
                return resp

    index_path = dist_dir / "index.html"
    if not index_path.is_file():
        return None
    resp = make_response(send_from_directory(dist_dir, "index.html"))
    resp.headers["Cache-Control"] = "no-cache"
    return resp


def create_app(config_override: dict[str, Any] | None = None) -> Flask:
    """Create and configure the Flask application."""
    current_settings = load_settings()

    flask_app = Flask(__name__, instance_relative_config=False)
    flask_app.request_class = MemoryRequest

    # -----------------------------------------------------------------------
    # Flask / extension config
    # -----------------------------------------------------------------------
    flask_app.config["SECRET_KEY"] = current_settings.secret_key
    flask_app.config["JWT_SECRET_KEY"] = current_settings.jwt_secret_key
    flask_app.config["JWT_ACCESS_TOKEN_EXPIRES"] = 60 * 60            # 60 min
    flask_app.config["JWT_REFRESH_TOKEN_EXPIRES"] = 7 * 24 * 60 * 60  # 7 days
    flask_app.config["SQLALCHEMY_DATABASE_URI"] = current_settings.database_url
    flask_app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    flask_app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024          # 5 MiB hard total-request limit
    flask_app.config["RATELIMIT_ENABLED"] = True
    flask_app.config["RATELIMIT_STORAGE_URI"] = "memory://"
    flask_app.config["RATELIMIT_REGISTER"] = current_settings.rate_limit_register
    flask_app.config["RATELIMIT_LOGIN"] = current_settings.rate_limit_login
    flask_app.config["RATELIMIT_REPORT_CROWD"] = current_settings.rate_limit_report_crowd
    flask_app.config["RATELIMIT_REPORT_SOS"] = current_settings.rate_limit_report_sos
    flask_app.config["SERVE_FRONTEND"] = current_settings.serve_frontend
    flask_app.config["ALLOW_DEFAULT_PASSWORDS"] = current_settings.allow_default_passwords
    flask_app.config["FRONTEND_DIST_DIR"] = str(BACKEND_DIR.parent / "frontend" / "dist")

    if config_override:
        flask_app.config.update(config_override)

    # Ensure directory exists for file-backed SQLite databases
    db_uri = str(flask_app.config["SQLALCHEMY_DATABASE_URI"])
    normalized_uri = normalize_sqlite_url(db_uri)
    flask_app.config["SQLALCHEMY_DATABASE_URI"] = normalized_uri
    if normalized_uri.startswith("sqlite:///") and normalized_uri != "sqlite:///:memory:":
        db_file = Path(normalized_uri[len("sqlite:///"):])
        db_file.parent.mkdir(parents=True, exist_ok=True)

    # -----------------------------------------------------------------------
    # Proxy fix — must be applied BEFORE any request handling so
    # request.remote_addr reflects the real client IP from X-Forwarded-For.
    # TRUSTED_PROXY_COUNT=0 in tests, 1 behind the cloudflared tunnel.
    # -----------------------------------------------------------------------
    n = current_settings.trusted_proxy_count
    if n > 0:
        flask_app.wsgi_app = ProxyFix(  # type: ignore[method-assign]
            flask_app.wsgi_app,
            x_for=n,
            x_proto=n,
            x_host=n,
        )

    # -----------------------------------------------------------------------
    # Logging (must come early so everything below is logged)
    # -----------------------------------------------------------------------
    configure_logging(flask_app)

    # -----------------------------------------------------------------------
    # Extensions
    # -----------------------------------------------------------------------
    db.init_app(flask_app)
    migrate.init_app(flask_app, db)
    jwt.init_app(flask_app)
    configure_jwt_error_loaders(jwt)
    # Keep the shared Limiter extension active so sibling apps in the same process
    # isolate RATELIMIT_ENABLED via app.config (checked per-request by request_filter)
    # without wiping an already-active storage when another app disables limits.
    app_rl_enabled = bool(flask_app.config.get("RATELIMIT_ENABLED", True))
    if app_rl_enabled or not limiter.initialized:
        flask_app.config["RATELIMIT_ENABLED"] = True
        limiter.enabled = True
        limiter.init_app(flask_app)
        flask_app.config["RATELIMIT_ENABLED"] = app_rl_enabled
    cors.init_app(
        flask_app,
        resources={r"/api/*": {"origins": current_settings.cors_origins}},
    )
    from app.realtime.connect import register_socketio_handlers
    from app.realtime.events import register_frame_handlers

    register_socketio_handlers()
    register_frame_handlers()
    socketio.init_app(
        flask_app,
        async_mode="threading",
        cors_allowed_origins=current_settings.cors_origins,
    )

    # -----------------------------------------------------------------------
    # Import models so Flask-Migrate can detect them
    # -----------------------------------------------------------------------
    import app.models  # noqa: F401

    # -----------------------------------------------------------------------
    # Blueprints
    # -----------------------------------------------------------------------
    from app.api.v1.advisories import advisories_bp
    from app.api.v1.alerts import alerts_bp
    from app.api.v1.analytics import analytics_bp
    from app.api.v1.audit import audit_bp
    from app.api.v1.auth import auth_bp
    from app.api.v1.config import config_bp
    from app.api.v1.health import health_bp
    from app.api.v1.push import push_bp
    from app.api.v1.reports import reports_bp
    from app.api.v1.sources import sources_bp
    from app.api.v1.users import users_bp
    from app.api.v1.zones import zones_bp

    flask_app.register_blueprint(health_bp, url_prefix="/api/v1")
    flask_app.register_blueprint(auth_bp, url_prefix="/api/v1/auth")
    flask_app.register_blueprint(users_bp, url_prefix="/api/v1/users")
    flask_app.register_blueprint(zones_bp, url_prefix="/api/v1")
    flask_app.register_blueprint(sources_bp, url_prefix="/api/v1")
    flask_app.register_blueprint(config_bp, url_prefix="/api/v1")
    flask_app.register_blueprint(alerts_bp, url_prefix="/api/v1")
    flask_app.register_blueprint(advisories_bp, url_prefix="/api/v1")
    flask_app.register_blueprint(push_bp, url_prefix="/api/v1")
    flask_app.register_blueprint(reports_bp, url_prefix="/api/v1")
    flask_app.register_blueprint(analytics_bp, url_prefix="/api/v1")
    flask_app.register_blueprint(audit_bp, url_prefix="/api/v1")

    # -----------------------------------------------------------------------
    # CLI commands
    # -----------------------------------------------------------------------
    from app.cli import register_commands

    register_commands(flask_app)

    # -----------------------------------------------------------------------
    # Dependency injection wiring & engine boot
    # -----------------------------------------------------------------------
    container = wire(flask_app, app_settings=current_settings)

    with flask_app.app_context():
        from sqlalchemy import inspect as sa_inspect

        from app.services.engine_sync import boot_engine_from_db

        inspector = sa_inspect(db.engine)
        tables_ready = inspector.has_table("zones") and inspector.has_table("alerts")
        if tables_ready:
            boot_engine_from_db(
                zone_engine=container.zone_engine,
                zone_repo=container.zone_repo,
                source_repo=container.source_repo,
                alert_repo=container.alert_repo,
                settings_service=container.settings_service,
            )

    import atexit
    import sys

    _one_shot_cmds = {"db", "seed-demo", "set-password", "routes", "shell"}
    _one_shot_cli = any(arg in _one_shot_cmds for arg in sys.argv[1:])
    _fake_feed_no_serve = (
        "fake-feed" in sys.argv[1:] and "--serve" not in sys.argv[1:]
    )
    if (
        bool(flask_app.config.get("SERVE_FRONTEND", False))
        and not bool(flask_app.config.get("ALLOW_DEFAULT_PASSWORDS", False))
        and not _one_shot_cli
        and not _fake_feed_no_serve
    ):
        _enforce_no_default_admin_passwords(flask_app)

    if (
        tables_ready
        and not _one_shot_cli
        and not _fake_feed_no_serve
        and not flask_app.config.get("TESTING")
        and (not flask_app.debug or current_settings.werkzeug_run_main == "true")
    ):
        from app.realtime.tasks import start_background_loop

        start_background_loop(flask_app)
        if hasattr(container.notifier, "start"):
            container.notifier.start(flask_app)
            atexit.register(container.notifier.stop)
        container.detection_manager.start(flask_app)
        atexit.register(container.detection_manager.stop)

    # -----------------------------------------------------------------------
    # Global error handlers
    # -----------------------------------------------------------------------
    @flask_app.errorhandler(AppError)
    def handle_app_error(exc: AppError) -> tuple[Response, int]:
        req_id = getattr(g, "request_id", "")
        logger.warning(
            "AppError",
            extra={"code": exc.code, "status": exc.status, "request_id": req_id},
        )
        return error_response(exc.code, exc.message, exc.details, exc.status)

    @flask_app.errorhandler(PydanticValidationError)
    def handle_pydantic_validation(exc: PydanticValidationError) -> tuple[Response, int]:
        return error_response(
            "VALIDATION_ERROR",
            "Request validation failed.",
            details=_format_pydantic_details(exc),
            status=422,
        )

    @flask_app.errorhandler(WerkzeugBadRequest)
    def handle_400(_: WerkzeugBadRequest) -> tuple[Response, int]:
        return error_response("BAD_REQUEST", "Malformed request.", status=400)

    @flask_app.errorhandler(WerkzeugNotFound)
    def handle_404(_: WerkzeugNotFound) -> Response | tuple[Response, int]:
        if (
            bool(flask_app.config.get("SERVE_FRONTEND", False))
            and request.method in ("GET", "HEAD")
        ):
            spa_resp = _try_serve_spa(flask_app, request.path)
            if spa_resp is not None:
                return spa_resp
        return error_response(
            "NOT_FOUND", "The requested resource was not found.", status=404
        )

    @flask_app.errorhandler(WerkzeugMethodNotAllowed)
    def handle_405(_: WerkzeugMethodNotAllowed) -> tuple[Response, int]:
        return error_response("METHOD_NOT_ALLOWED", "Method not allowed.", status=405)

    @flask_app.errorhandler(RequestEntityTooLarge)
    def handle_413(_: RequestEntityTooLarge) -> tuple[Response, int]:
        return error_response(
            "PAYLOAD_TOO_LARGE", "Request payload exceeds maximum size.", status=413
        )

    @flask_app.errorhandler(429)
    def handle_429(_: HTTPException) -> tuple[Response, int]:
        return error_response(
            "RATE_LIMITED", "Too many requests. Please try again later.", status=429
        )

    @flask_app.errorhandler(HTTPException)
    def handle_http_exception(exc: HTTPException) -> tuple[Response, int]:
        code_map = {
            401: "UNAUTHENTICATED",
            403: "FORBIDDEN",
            409: "CONFLICT",
            429: "RATE_LIMITED",
            503: "DETECTOR_UNAVAILABLE",
        }
        status = exc.code or 500
        code = code_map.get(status, "INTERNAL")
        return error_response(code, exc.description or "Request error.", status=status)

    @flask_app.errorhandler(Exception)
    def handle_unexpected(exc: Exception) -> tuple[Response, int]:
        req_id = getattr(g, "request_id", "")
        logger.exception(
            "Unhandled exception",
            extra={"request_id": req_id},
        )
        return error_response("INTERNAL", "An unexpected error occurred.", status=500)

    return flask_app
