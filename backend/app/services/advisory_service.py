"""app/services/advisory_service.py — Business logic for Advisories (contract §6.2 / §7.2)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core.clock import Clock, SystemClock
from app.core.errors import NotFound
from app.extensions import db
from app.models.models import Advisory, User, Zone
from app.realtime.emitter import RealtimeEmitter
from app.repositories.advisory_repo import AdvisoryRepository
from app.repositories.user_repo import UserRepository
from app.repositories.zone_repo import ZoneRepository
from app.schemas.advisories import AdvisoryCreateRequest
from app.schemas.serializers import serialize_advisory
from app.services.audit_service import AuditService


def _naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


class AdvisoryService:
    def __init__(
        self,
        *,
        advisory_repo: AdvisoryRepository,
        zone_repo: ZoneRepository,
        user_repo: UserRepository,
        audit_service: AuditService,
        emitter: RealtimeEmitter,
        clock: Clock | None = None,
    ) -> None:
        self._repo = advisory_repo
        self._zone_repo = zone_repo
        self._user_repo = user_repo
        self._audit = audit_service
        self._emitter = emitter
        self._clock: Clock = clock or SystemClock()

    def _serialize_one(self, adv: Advisory) -> dict[str, Any]:
        creator = self._user_repo.get(adv.created_by)
        assert creator is not None
        zone = self._zone_repo.get(adv.zone_id) if adv.zone_id is not None else None
        return serialize_advisory(adv, creator=creator, zone=zone)

    def list_public(self, zone_id: int | None = None) -> list[dict[str, Any]]:
        now_naive = _naive_utc(self._clock.utcnow())
        items = self._repo.list_public(zone_id=zone_id, now_naive=now_naive)
        zones_cache: dict[int, Zone | None] = {}
        users_cache: dict[int, User] = {}
        result: list[dict[str, Any]] = []
        for adv in items:
            if adv.created_by not in users_cache:
                u = self._user_repo.get(adv.created_by)
                assert u is not None
                users_cache[adv.created_by] = u
            zone: Zone | None = None
            if adv.zone_id is not None:
                if adv.zone_id not in zones_cache:
                    zones_cache[adv.zone_id] = self._zone_repo.get(adv.zone_id)
                zone = zones_cache[adv.zone_id]
            result.append(serialize_advisory(adv, creator=users_cache[adv.created_by], zone=zone))
        return result

    def create(self, req: AdvisoryCreateRequest, actor: User) -> dict[str, Any]:
        zone: Zone | None = None
        if req.zone_id is not None:
            zone = self._zone_repo.get(req.zone_id)
            if zone is None or not zone.is_active:
                raise NotFound(f"Zone {req.zone_id} not found.")

        now_naive = _naive_utc(self._clock.utcnow())
        expires_naive = _naive_utc(req.expires_at) if req.expires_at is not None else None

        adv = Advisory(  # pyrefly: ignore[unexpected-keyword]
            title=req.title,
            body=req.body,
            severity=req.severity,
            zone_id=req.zone_id,
            created_by=actor.id,
            created_at=now_naive,
            expires_at=expires_naive,
            is_active=True,
        )
        self._repo.add(adv)
        self._audit.log(
            actor,
            "ADVISORY_CREATED",
            "advisory",
            adv.id,
            {"severity": adv.severity, "zone_id": adv.zone_id},
        )
        db.session.commit()
        db.session.refresh(adv)

        payload = serialize_advisory(adv, creator=actor, zone=zone)
        self._emitter.emit_advisory_new(payload)
        return payload

    def retract(self, advisory_id: int, actor: User) -> None:
        adv = self._repo.get(advisory_id)
        if adv is None or not adv.is_active:
            raise NotFound(f"Advisory {advisory_id} not found.")

        adv.is_active = False
        self._audit.log(actor, "ADVISORY_RETRACTED", "advisory", adv.id, {})
        db.session.commit()
        self._emitter.emit_advisory_retracted(advisory_id)

    def expire_due_advisories(self, now: datetime | None = None) -> list[int]:
        """Deactivate advisories whose expires_at <= now and emit advisory:retracted."""
        now_naive = _naive_utc(now or self._clock.utcnow())
        due = self._repo.list_expired_active(now_naive)
        if not due:
            return []
        expired_ids = []
        for adv in due:
            adv.is_active = False
            expired_ids.append(adv.id)
        db.session.commit()

        for aid in expired_ids:
            self._emitter.emit_advisory_retracted(aid)
        return expired_ids
