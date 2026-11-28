"""app/services/report_service.py — Citizen reports business logic (contract §4.4 / §6.2 / §8.5)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from shapely.geometry import Point, shape

from app.core.clock import Clock, SystemClock
from app.core.errors import InvalidTransition, NotFound
from app.extensions import db
from app.models.models import Report, User, Zone
from app.push.notifier import PUSH_SOS_TYPES, Notifier
from app.realtime.emitter import RealtimeEmitter
from app.repositories.report_repo import ReportRepository
from app.repositories.user_repo import UserRepository
from app.repositories.zone_repo import ZoneRepository
from app.schemas.reports import ReportReviewRequest, SosReportCreateRequest
from app.schemas.serializers import serialize_report
from app.services.audit_service import AuditService

if TYPE_CHECKING:
    from app.detection.manager import DetectionManager


def _naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


class ReportService:
    def __init__(
        self,
        *,
        report_repo: ReportRepository,
        zone_repo: ZoneRepository,
        user_repo: UserRepository,
        audit_service: AuditService,
        detection_manager: "DetectionManager",
        emitter: RealtimeEmitter,
        notifier: Notifier,
        clock: Clock | None = None,
    ) -> None:
        self._repo = report_repo
        self._zone_repo = zone_repo
        self._user_repo = user_repo
        self._audit = audit_service
        self._detection_manager = detection_manager
        self._emitter = emitter
        self._notifier = notifier
        self._clock: Clock = clock or SystemClock()

    def match_zone_for_point(self, lat: float, lng: float) -> Zone | None:
        """Return the first active Zone polygon containing (lng, lat), else None."""
        pt = Point(float(lng), float(lat))
        for zone in self._zone_repo.list_active():
            try:
                geom = json.loads(zone.geometry_json)
                if shape(geom).contains(pt):
                    return zone
            except Exception:
                continue
        return None

    def _serialize_list(self, reports: list[Report]) -> list[dict[str, Any]]:
        users_cache: dict[int, User] = {}
        zones_cache: dict[int, Zone | None] = {}

        def _get_user(uid: int) -> User:
            u = users_cache.get(uid)
            if u is None:
                fetched = self._user_repo.get(uid)
                assert fetched is not None
                users_cache[uid] = fetched
                return fetched
            return u

        result: list[dict[str, Any]] = []
        for rep in reports:
            creator = _get_user(rep.created_by)
            reviewer = _get_user(rep.reviewed_by) if rep.reviewed_by is not None else None
            zone: Zone | None = None
            if rep.zone_id is not None:
                if rep.zone_id not in zones_cache:
                    zones_cache[rep.zone_id] = self._zone_repo.get(rep.zone_id)
                zone = zones_cache[rep.zone_id]
            result.append(
                serialize_report(rep, creator=creator, reviewer=reviewer, zone=zone)
            )
        return result

    def submit_crowd(
        self,
        actor: User,
        *,
        image_bytes: bytes,
        lat: float,
        lng: float,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Run one synchronous detection in RAM, discard bytes, match zone, and persist."""
        try:
            detect_res = self._detection_manager.detect_once(image_bytes, timeout=5.0)
        finally:
            # Never retain upload bytes beyond synchronous detection call.
            image_bytes = b""

        count = int(detect_res.count)
        zone = self.match_zone_for_point(lat, lng)
        density_hint: float | None = None
        if zone is not None and zone.area_m2 > 0:
            density_hint = round(float(count) / float(zone.area_m2), 4)

        now_naive = _naive_utc(self._clock.utcnow())
        report = Report(  # pyrefly: ignore[unexpected-keyword]
            kind="CROWD",
            status="PENDING",
            zone_id=zone.id if zone is not None else None,
            lat=float(lat),
            lng=float(lng),
            count=float(count),
            density_hint=density_hint,
            note=note,
            sos_type=None,
            created_by=actor.id,
            created_at=now_naive,
        )
        self._repo.add(report)
        db.session.commit()
        db.session.refresh(report)

        payload = serialize_report(report, creator=actor, zone=zone)
        self._emitter.emit_report_new(payload)
        return payload

    def submit_sos(
        self,
        actor: User,
        req: SosReportCreateRequest,
    ) -> dict[str, Any]:
        """Persist an SOS report, emit realtime report:new, and trigger push if urgent."""
        zone = self.match_zone_for_point(req.lat, req.lng)
        now_naive = _naive_utc(self._clock.utcnow())
        report = Report(  # pyrefly: ignore[unexpected-keyword]
            kind="SOS",
            status="PENDING",
            zone_id=zone.id if zone is not None else None,
            lat=float(req.lat),
            lng=float(req.lng),
            count=None,
            density_hint=None,
            note=req.note,
            sos_type=req.sos_type,
            created_by=actor.id,
            created_at=now_naive,
        )
        self._repo.add(report)
        db.session.commit()
        db.session.refresh(report)

        payload = serialize_report(report, creator=actor, zone=zone)
        self._emitter.emit_report_new(payload)
        if req.sos_type in PUSH_SOS_TYPES:
            self._notifier.notify_sos(payload)
        return payload

    def list_mine(
        self,
        actor: User,
        *,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        items, total = self._repo.list_mine(actor.id, page=page, limit=limit)
        return self._serialize_list(items), total

    def list_reports(
        self,
        *,
        kind: str | None = None,
        status: str | None = None,
        zone_id: int | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        items, total = self._repo.list_filtered(
            kind=kind,
            status=status,
            zone_id=zone_id,
            page=page,
            limit=limit,
        )
        return self._serialize_list(items), total

    def review(
        self,
        report_id: int,
        req: ReportReviewRequest,
        actor: User,
    ) -> dict[str, Any]:
        """Atomically transition a PENDING report to VERIFIED or DISMISSED."""
        now_naive = _naive_utc(self._clock.utcnow())
        updated = self._repo.claim_review(
            report_id,
            status=req.status,
            reviewed_by=actor.id,
            reviewed_at=now_naive,
            review_note=req.review_note,
        )
        if updated == 0:
            existing = self._repo.get(report_id)
            db.session.rollback()
            if existing is None:
                raise NotFound(f"Report {report_id} not found.")
            raise InvalidTransition(
                f"Cannot review report with status {existing.status}; only PENDING reports can be reviewed."
            )

        audit_data: dict[str, Any] = {"status": req.status}
        if req.review_note:
            audit_data["review_note"] = req.review_note
        self._audit.log(actor, "REPORT_REVIEWED", "report", report_id, audit_data)

        db.session.commit()
        db.session.expire_all()
        report = self._repo.get(report_id)
        assert report is not None

        creator = self._user_repo.get(report.created_by)
        assert creator is not None
        zone = self._zone_repo.get(report.zone_id) if report.zone_id is not None else None
        payload = serialize_report(report, creator=creator, reviewer=actor, zone=zone)
        self._emitter.emit_report_updated(payload, report.created_by)
        return payload
