"""app/realtime/connect.py — Socket.IO connect/disconnect & session freshness.

Contract §7.1 rooms:
  - Every client joins: `public`
  - Valid active user: also joins `user:{id}`
  - police role: also joins `role:police`
  - admin role: also joins `role:police` AND `role:admin`
  - Invalid / expired / disabled token: stays `public`, emits `auth:expired`

Always emit `hello` {role, server_time, contract_version} to the connecting sid,
where `role` is Role ('citizen'|'police'|'admin') or None (JSON null for anonymous).

Session registry:
  sessions[sid] = {user_id, role, token_exp}
  Guarded by threading.Lock for use across request threads and the 1 Hz engine loop.

enforce_session_freshness(now: datetime) iterates sessions; for any whose
token is expired or whose DB user is disabled/demoted, it leaves the privileged
rooms, emits `auth:expired`, and disconnects the socket.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any

from flask import request
from flask_jwt_extended import decode_token
from flask_socketio import join_room

from app.core.time import to_iso_z, utcnow
from app.extensions import db, socketio
from app.models.models import User
from app.services.settings_service import load_contract_version

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Session registry — shared state protected by a lock
# ---------------------------------------------------------------------------
_lock = threading.Lock()
# sid -> {user_id: int | None, role: str | None, token_exp: float | None}
sessions: dict[str, dict[str, Any]] = {}


def _leave_room_safe(sid: str, room: str) -> None:
    """Remove *sid* from *room* on namespace '/' (safe from background threads)."""
    if socketio.server is not None:
        socketio.server.leave_room(sid, room, namespace="/")


def _disconnect_safe(sid: str) -> None:
    """Disconnect *sid* on namespace '/' (safe from background threads)."""
    if socketio.server is not None:
        socketio.server.disconnect(sid, namespace="/")


# ---------------------------------------------------------------------------
# Connect / disconnect handlers
# ---------------------------------------------------------------------------

@socketio.on("connect")
def on_connect(auth: dict[str, Any] | None = None) -> None:
    sid: str = request.sid  # type: ignore[attr-defined]
    role: str | None = None
    token_exp: float | None = None
    user_id: int | None = None

    token = auth.get("token") if isinstance(auth, dict) else None
    if token:
        try:
            decoded = decode_token(token)
            uid = int(decoded["sub"])
            db.session.expire_all()
            user: User | None = db.session.get(User, uid)
            if user is not None and user.is_active:
                role = user.role
                user_id = user.id
                raw_exp = decoded.get("exp")
                token_exp = float(raw_exp) if raw_exp is not None else None
            else:
                socketio.emit("auth:expired", {}, to=sid)
        except Exception:
            logger.debug("Socket.IO connect: bad/expired token for sid %s", sid)
            socketio.emit("auth:expired", {}, to=sid)

    # Every client joins public
    join_room("public")

    if user_id is not None:
        join_room(f"user:{user_id}")
        if role in ("police", "admin"):
            join_room("role:police")
        if role == "admin":
            join_room("role:admin")

    with _lock:
        sessions[sid] = {
            "user_id": user_id,
            "role": role,
            "token_exp": token_exp,
        }

    socketio.emit(
        "hello",
        {
            "role": role,
            "server_time": to_iso_z(utcnow()),
            "contract_version": load_contract_version(),
        },
        to=sid,
    )
    logger.debug("Socket.IO connect: sid=%s role=%s user_id=%s", sid, role, user_id)


@socketio.on("disconnect")
def on_disconnect() -> None:
    sid: str = request.sid  # type: ignore[attr-defined]
    with _lock:
        sessions.pop(sid, None)
    logger.debug("Socket.IO disconnect: sid=%s", sid)


def register_socketio_handlers() -> None:
    """No-op hook imported before `socketio.init_app()` so `@socketio.on`
    decorators append into `socketio.handlers` before `socketio.server` exists.
    """
    return None


# ---------------------------------------------------------------------------
# Session freshness enforcement
# ---------------------------------------------------------------------------

def enforce_session_freshness(now: datetime) -> None:
    """Remove expired/disabled/demoted sockets from privileged rooms.

    Called by the B4 1 Hz loop and at the start of frame:submit (B5).

    Args:
        now: Current UTC datetime (may be FakeClock.utcnow() in tests).
    """
    now_ts = now.timestamp()

    with _lock:
        snapshot = dict(sessions)

    # Ensure we read committed DB changes made by other threads/requests
    has_auth = any(info.get("user_id") is not None for info in snapshot.values())
    if has_auth:
        db.session.expire_all()

    for sid, info in snapshot.items():
        user_id = info.get("user_id")
        token_exp = info.get("token_exp")
        registered_role = info.get("role")

        if user_id is None:
            continue

        should_expire = False

        # 1. Token expired
        if token_exp is not None and now_ts >= token_exp:
            should_expire = True

        # 2. User disabled or demoted (re-read DB)
        if not should_expire:
            try:
                user: User | None = db.session.get(User, user_id)
                if user is None or not user.is_active:
                    should_expire = True
                elif registered_role != user.role:
                    # Any role change (e.g. police -> citizen, admin -> police)
                    should_expire = True
            except Exception:
                logger.exception(
                    "enforce_session_freshness: DB error for user_id=%s", user_id
                )
                continue

        if should_expire:
            logger.info(
                "enforce_session_freshness: expiring sid=%s user_id=%s", sid, user_id
            )
            try:
                _leave_room_safe(sid, "role:police")
                _leave_room_safe(sid, "role:admin")
                _leave_room_safe(sid, f"user:{user_id}")
                socketio.emit("auth:expired", {}, to=sid, namespace="/")
                _disconnect_safe(sid)
            except Exception:
                logger.exception(
                    "enforce_session_freshness: error disconnecting sid=%s", sid
                )
            with _lock:
                sessions.pop(sid, None)
