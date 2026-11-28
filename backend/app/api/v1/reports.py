"""app/api/v1/reports.py — Citizen Reports REST endpoints (contract §6.2 / plan §8.5).

Privacy & retention:
  - Crowd photos uploaded to POST /reports/crowd are read strictly in RAM via
    MemoryRequest (never written to disk or temp files), passed synchronously to
    the detection worker, and discarded immediately after inference.
  - Report rows retain only derived counts/coordinates/notes and are deleted
    automatically by the hourly retention task after REPORT_RETENTION_DAYS (default 30).

Route table (all under /api/v1):
  POST  /reports/crowd   — citizen+ (multipart image JPEG/PNG; 5 MiB max total multipart request via MAX_CONTENT_LENGTH, lat, lng, note?)
  POST  /reports/sos     — citizen+ ({sos_type, lat, lng, note?})
  GET   /reports/mine    — citizen+ (?page&limit)
  GET   /reports         — police+ (?kind=&status=&zone_id=&page&limit)
  PATCH /reports/{id}    — police+ ({status: VERIFIED|DISMISSED, review_note?})
"""
from __future__ import annotations

from flask import Blueprint, current_app, request
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request
from flask_limiter.util import get_remote_address

from app.container import get_container
from app.core.auth import current_user, roles_required
from app.core.errors import PayloadTooLarge, ValidationAppError
from app.core.responses import created, ok, paginated
from app.core.validation import parse_json_body, validate
from app.extensions import limiter
from app.schemas.reports import (
    CrowdReportFormSchema,
    ReportReviewRequest,
    SosReportCreateRequest,
)

reports_bp = Blueprint("reports", __name__)

_MAX_IMAGE_BYTES = 5 * 1024 * 1024
_ALLOWED_MIME_TYPES = frozenset({"image/jpeg", "image/jpg", "image/png"})
_ALLOWED_KINDS = frozenset({"CROWD", "SOS"})
_ALLOWED_STATUSES = frozenset({"PENDING", "VERIFIED", "DISMISSED"})


def _user_rate_limit_key() -> str:
    """Rate-limit citizen reports per authenticated user ID (falling back to IP)."""
    try:
        verify_jwt_in_request(optional=True)
        identity = get_jwt_identity()
        if identity is not None:
            return f"user:{identity}"
    except Exception:
        pass
    return f"ip:{get_remote_address()}"


def _is_jpeg_or_png(raw: bytes, mimetype: str) -> bool:
    if mimetype not in _ALLOWED_MIME_TYPES:
        return False
    if mimetype in ("image/jpeg", "image/jpg"):
        return raw.startswith(b"\xff\xd8\xff")
    return raw.startswith(b"\x89PNG\r\n\x1a\n")


@reports_bp.post("/reports/crowd")
@limiter.limit(
    lambda: current_app.config["RATELIMIT_REPORT_CROWD"],
    key_func=_user_rate_limit_key,
)
@roles_required("citizen", "police", "admin")
def submit_crowd_report():
    actor = current_user()

    ctype = (request.content_type or "").lower()
    if "multipart/form-data" not in ctype:
        raise ValidationAppError(
            "Request must be multipart/form-data.",
            details={"image": ["Expected multipart/form-data with an 'image' file part."]},
        )

    raw_lat = request.form.get("lat")
    raw_lng = request.form.get("lng")
    if raw_lat is None or raw_lng is None or raw_lat == "" or raw_lng == "":
        missing: dict[str, list[str]] = {}
        if not raw_lat:
            missing["lat"] = ["lat is required."]
        if not raw_lng:
            missing["lng"] = ["lng is required."]
        raise ValidationAppError("Validation failed.", details=missing)

    form_req = validate(
        CrowdReportFormSchema,
        {
            "lat": raw_lat,
            "lng": raw_lng,
            "note": request.form.get("note"),
        },
    )

    upload = request.files.get("image")
    if upload is None:
        raise ValidationAppError(
            "Validation failed.",
            details={"image": ["An 'image' file (JPEG or PNG) is required."]},
        )

    mimetype = (upload.mimetype or "").strip().lower()
    image_bytes = upload.read()
    if len(image_bytes) > _MAX_IMAGE_BYTES:
        raise PayloadTooLarge("Uploaded image exceeds 5 MB limit.")
    if not image_bytes or not _is_jpeg_or_png(image_bytes, mimetype):
        raise ValidationAppError(
            "Invalid image file.",
            details={"image": ["Image must be a valid JPEG or PNG file up to 5 MB."]},
        )

    container = get_container()
    result = container.report_service.submit_crowd(
        actor,
        image_bytes=image_bytes,
        lat=form_req.lat,
        lng=form_req.lng,
        note=form_req.note,
    )
    return created(result)


@reports_bp.post("/reports/sos")
@limiter.limit(
    lambda: current_app.config["RATELIMIT_REPORT_SOS"],
    key_func=_user_rate_limit_key,
)
@roles_required("citizen", "police", "admin")
def submit_sos_report():
    actor = current_user()
    req = validate(SosReportCreateRequest, parse_json_body())
    container = get_container()
    return created(container.report_service.submit_sos(actor, req))


@reports_bp.get("/reports/mine")
@roles_required("citizen", "police", "admin")
def list_my_reports():
    actor = current_user()
    try:
        page = max(1, int(request.args.get("page", 1)))
        limit = max(1, min(100, int(request.args.get("limit", 20))))
    except ValueError as exc:
        raise ValidationAppError("page and limit must be integers.") from exc

    container = get_container()
    items, total = container.report_service.list_mine(actor, page=page, limit=limit)
    return paginated(items, total, page, limit)


@reports_bp.get("/reports")
@roles_required("police")
def list_reports():
    current_user()
    kind = request.args.get("kind") or None
    if kind is not None and kind not in _ALLOWED_KINDS:
        raise ValidationAppError(
            "Invalid kind filter.",
            details={"kind": ["Allowed values: CROWD, SOS"]},
        )

    status = request.args.get("status") or None
    if status is not None and status not in _ALLOWED_STATUSES:
        raise ValidationAppError(
            "Invalid status filter.",
            details={"status": ["Allowed values: PENDING, VERIFIED, DISMISSED"]},
        )

    raw_zone = request.args.get("zone_id")
    zone_id: int | None = None
    if raw_zone is not None and raw_zone != "":
        try:
            zone_id = int(raw_zone)
        except ValueError as exc:
            raise ValidationAppError(
                "zone_id must be an integer.",
                details={"zone_id": ["Must be an integer"]},
            ) from exc

    try:
        page = max(1, int(request.args.get("page", 1)))
        limit = max(1, min(100, int(request.args.get("limit", 20))))
    except ValueError as exc:
        raise ValidationAppError("page and limit must be integers.") from exc

    container = get_container()
    items, total = container.report_service.list_reports(
        kind=kind,
        status=status,
        zone_id=zone_id,
        page=page,
        limit=limit,
    )
    return paginated(items, total, page, limit)


@reports_bp.patch("/reports/<int:report_id>")
@roles_required("police")
def review_report(report_id: int):
    actor = current_user()
    req = validate(ReportReviewRequest, parse_json_body())
    container = get_container()
    return ok(container.report_service.review(report_id, req, actor))
