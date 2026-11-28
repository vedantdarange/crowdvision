"""app/extensions.py — Flask extension singletons.

Instantiated here (not yet bound to an app); bound inside create_app().
Import from here everywhere else so there is exactly one instance per extension.
"""
from __future__ import annotations

import logging

from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from flask_socketio import SocketIO
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Typed SQLAlchemy 2.0 declarative base for all ORM models."""


db = SQLAlchemy(model_class=Base)
migrate = Migrate()
jwt = JWTManager()
cors = CORS()
socketio = SocketIO()
limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")


@limiter.request_filter
def _exempt_when_app_rate_limit_disabled() -> bool:
    """Honor each Flask app's own RATELIMIT_ENABLED setting on the shared Limiter."""
    from flask import current_app, has_app_context

    if has_app_context():
        return not bool(current_app.config.get("RATELIMIT_ENABLED", True))
    return False


# ---------------------------------------------------------------------------
# SQLite pragmas — applied on every new connection.
# REQUIRED: without WAL and busy_timeout the app gets "database is locked".
# ---------------------------------------------------------------------------
@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_conn: object, _: object) -> None:
    """Apply WAL mode, foreign keys, and busy timeout for SQLite connections."""
    cur = dbapi_conn.cursor()  # type: ignore[attr-defined]
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.close()
    logger.debug("SQLite pragmas applied")
