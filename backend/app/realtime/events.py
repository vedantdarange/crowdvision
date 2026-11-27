"""app/realtime/events.py — Socket.IO `frame:submit` handler (contract §7.3, §8)."""
from __future__ import annotations

import logging
from typing import Any

from flask import current_app, request

from app.detection.jpeg import validate_jpeg_frame
from app.extensions import socketio
from app.realtime.connect import check_session_freshness

logger = logging.getLogger(__name__)


def _emit_frame_error(
    sid: str,
    source_id: int,
    seq: int,
    error: str,
) -> None:
    container = current_app.extensions["container"]
    container.emitter.emit_frame_result(
        sid,
        {
            "source_id": source_id,
            "seq": seq,
            "ok": False,
            "error": error,
            "count": 0,
            "boxes": [],
            "infer_ms": 0.0,
            "smoothed_count": None,
            "density": None,
            "level": None,
        },
    )


def _coerce_nonneg_int(val: Any) -> int:
    if isinstance(val, int) and not isinstance(val, bool) and val > 0:
        return val
    return 0


@socketio.on("frame:submit")
def on_frame_submit(data: Any = None, image_arg: Any = None) -> None:
    """Validate role, session freshness, source, JPEG size/width, and enqueue frame."""
    sid: str = request.sid  # type: ignore[attr-defined]
    container = current_app.extensions["container"]

    raw_source_id = data.get("source_id") if isinstance(data, dict) else 0
    raw_seq = data.get("seq") if isinstance(data, dict) else 0
    source_id = _coerce_nonneg_int(raw_source_id)
    seq = _coerce_nonneg_int(raw_seq)

    # 1. Session freshness check before accepting any frame (contract §7.1 / §8.3)
    fresh, sess = check_session_freshness(
        sid,
        container.clock.utcnow(),
        emit_forbidden_error=lambda: _emit_frame_error(sid, source_id, seq, "FORBIDDEN"),
    )
    if not fresh:
        return

    # 2. Role guard: police/admin only
    role = sess.get("role") if sess is not None else None
    if role not in ("police", "admin"):
        _emit_frame_error(sid, source_id, seq, "FORBIDDEN")
        return

    if not isinstance(data, dict):
        _emit_frame_error(sid, source_id, seq, "BAD_IMAGE")
        return

    # 3. Source existence & active check (and its zone must be active)
    if source_id <= 0:
        _emit_frame_error(sid, source_id, seq, "UNKNOWN_SOURCE")
        return
    source = container.source_repo.get(source_id)
    if source is None or not source.is_active:
        _emit_frame_error(sid, source_id, seq, "UNKNOWN_SOURCE")
        return
    zone = container.zone_repo.get(source.zone_id)
    if zone is None or not zone.is_active:
        _emit_frame_error(sid, source_id, seq, "UNKNOWN_SOURCE")
        return

    # 4. Validate seq and JPEG payload in memory (no inference or disk I/O in handler)
    if seq <= 0:
        _emit_frame_error(sid, source_id, seq, "BAD_IMAGE")
        return

    raw_image = data.get("image")
    if raw_image is None and image_arg is not None:
        raw_image = image_arg

    # Mandatory width and height — contract §8 requires both as positive integers.
    # Check before validate_jpeg_frame so missing/invalid dimensions return BAD_IMAGE
    # rather than silently treating them as None (Fix 3).
    raw_w = data.get("width")
    raw_h = data.get("height")
    if not (isinstance(raw_w, int) and not isinstance(raw_w, bool) and raw_w > 0):
        _emit_frame_error(sid, source_id, seq, "BAD_IMAGE")
        return
    if not (isinstance(raw_h, int) and not isinstance(raw_h, bool) and raw_h > 0):
        _emit_frame_error(sid, source_id, seq, "BAD_IMAGE")
        return

    try:
        jpeg_bytes, width, height = validate_jpeg_frame(
            raw_image,
            declared_width=raw_w,
            declared_height=raw_h,
        )
    except ValueError:
        _emit_frame_error(sid, source_id, seq, "BAD_IMAGE")
        return

    reset = bool(data.get("reset", False))

    # 5. Lease check + non-blocking enqueue onto spawned worker queue
    err = container.detection_manager.submit_frame(
        sid=sid,
        source_id=source_id,
        seq=seq,
        jpeg_bytes=jpeg_bytes,
        width=width,
        height=height,
        reset=reset,
    )
    if err is not None:
        _emit_frame_error(sid, source_id, seq, err)


def register_frame_handlers() -> None:
    """Import hook so @socketio.on('frame:submit') registers before socketio.init_app()."""
    return None
