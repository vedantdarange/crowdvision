"""app/config.py — the ONLY place that reads os.environ.

All other modules import `settings` (or call `load_settings()`) from here;
they never call os.getenv / os.environ directly.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _bool(key: str, default: bool) -> bool:
    return os.environ.get(key, str(default)).strip().lower() in ("1", "true", "yes")


def _int(key: str, default: int) -> int:
    return int(os.environ.get(key, str(default)).strip())


def _parse_latlong(value: str) -> tuple[float, float]:
    parts = value.split(",")
    if len(parts) != 2:
        raise RuntimeError(f"DEMO_CENTER must be 'lat,lng'; got {value!r}")
    return float(parts[0].strip()), float(parts[1].strip())


def normalize_sqlite_url(url: str) -> str:
    """Resolve relative sqlite:/// paths against BACKEND_DIR.

    Flask-SQLAlchemy 3.x resolves relative sqlite:/// URIs against
    app.instance_path, which turns sqlite:///instance/app.db into
    instance/instance/app.db. Resolving against BACKEND_DIR makes
    sqlite:///instance/app.db map to <backend>/instance/app.db.
    """
    if not url.startswith("sqlite:///") or url == "sqlite:///:memory:":
        return url
    raw_path = url[len("sqlite:///"):]
    # Already absolute on POSIX (/...) or Windows (C:/... or C:\...)
    if raw_path.startswith("/") or (len(raw_path) >= 2 and raw_path[1] == ":"):
        return url
    resolved = (BACKEND_DIR / raw_path).resolve()
    return f"sqlite:///{resolved.as_posix()}"


@dataclass(frozen=True)
class Settings:
    flask_env: str
    secret_key: str
    debug: bool
    jwt_secret_key: str
    database_url: str
    model_path: str
    detector_backend: str
    vapid_private_key: str | None
    vapid_public_key: str | None
    vapid_subject: str
    serve_frontend: bool
    cors_origins: list[str]
    sentry_dsn: str | None
    demo_center: tuple[float, float]
    seed_password: str | None
    allow_default_passwords: bool
    trusted_proxy_count: int
    use_tracker: bool
    report_retention_days: int
    rate_limit_register: str
    rate_limit_login: str
    app_version: str = "0.1.0"
    contract_version: str = "1.1.0"


def load_settings() -> Settings:
    """Read environment variables and return an immutable Settings object."""
    flask_env = os.environ.get("FLASK_ENV", "development")
    return Settings(
        flask_env=flask_env,
        secret_key=os.environ.get("SECRET_KEY", "dev-secret-key"),
        debug=flask_env == "development",
        jwt_secret_key=os.environ.get("JWT_SECRET_KEY", "dev-jwt-secret"),
        database_url=normalize_sqlite_url(
            os.environ.get("DATABASE_URL", "sqlite:///instance/app.db")
        ),
        model_path=os.environ.get("MODEL_PATH", "docs/model/best.pt"),
        detector_backend=os.environ.get("DETECTOR_BACKEND", "fake"),
        vapid_private_key=os.environ.get("VAPID_PRIVATE_KEY") or None,
        vapid_public_key=os.environ.get("VAPID_PUBLIC_KEY") or None,
        vapid_subject=os.environ.get("VAPID_SUBJECT", "mailto:you@example.com"),
        serve_frontend=_bool("SERVE_FRONTEND", False),
        cors_origins=[
            o.strip()
            for o in os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",")
            if o.strip()
        ],
        sentry_dsn=os.environ.get("SENTRY_DSN") or None,
        demo_center=_parse_latlong(os.environ.get("DEMO_CENTER", "28.6139,77.2090")),
        seed_password=os.environ.get("SEED_PASSWORD") or None,
        allow_default_passwords=_bool("ALLOW_DEFAULT_PASSWORDS", False),
        trusted_proxy_count=_int("TRUSTED_PROXY_COUNT", 0),
        use_tracker=_bool("USE_TRACKER", False),
        report_retention_days=_int("REPORT_RETENTION_DAYS", 30),
        rate_limit_register=os.environ.get("RATE_LIMIT_REGISTER", "10/hour"),
        rate_limit_login=os.environ.get("RATE_LIMIT_LOGIN", "20/minute"),
    )


# Singleton — imported everywhere as `from app.config import settings`
settings = load_settings()
