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
from flask import Flask, Response, g
from pydantic import ValidationError as PydanticValidationError
from werkzeug.exceptions import (
    BadRequest as WerkzeugBadRequest,
    HTTPException,
    MethodNotAllowed as WerkzeugMethodNotAllowed,
    NotFound as WerkzeugNotFound,
    RequestEntityTooLarge,
)
from werkzeug.middleware.proxy_fix import ProxyFix

from app.config import load_settings, normalize_sqlite_url
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
    flask_app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024          # 5 MB hard limit
    flask_app.config["RATELIMIT_STORAGE_URI"] = "memory://"
    flask_app.config["RATELIMIT_REGISTER"] = current_settings.rate_limit_register
    flask_app.config["RATELIMIT_LOGIN"] = current_settings.rate_limit_login

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
    limiter.init_app(flask_app)
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
    from app.api.v1.auth import auth_bp
    from app.api.v1.config import config_bp
    from app.api.v1.health import health_bp
    from app.api.v1.push import push_bp
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

    _one_shot_cli = len(sys.argv) >= 2 and sys.argv[1] in (
        "db",
        "seed-demo",
        "set-password",
        "routes",
        "shell",
    )
    _fake_feed_no_serve = (
        len(sys.argv) >= 2 and sys.argv[1] == "fake-feed" and "--serve" not in sys.argv
    )
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
    def handle_404(_: WerkzeugNotFound) -> tuple[Response, int]:
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
