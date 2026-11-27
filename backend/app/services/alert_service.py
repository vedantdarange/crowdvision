"""app/services/alert_service.py — Alert persistence, transitions, and post-commit dispatch."""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.clock import Clock, SystemClock
from app.core.errors import InvalidTransition, NotFound
from app.core.time import to_iso_z, utcnow
from app.engine.alert_rules import (
    AutoClearAlert,
    ClearCondition,
    CreateAlert,
    EmitZoneUpdate,
    EngineAction,
    EscalateAlert,
    MarkReraiseChecked,
    RecordFeedEvent,
    Remind,
    ReopenAlert,
    SendPush,
    UpdatePeak,
)
from app.engine.zone_engine import ZoneEngine
from app.extensions import db
from app.models.models import AlertEvent, AlertModel, User, Zone
from app.push.notifier import Notifier
from app.realtime.emitter import RealtimeEmitter
from app.repositories.alert_repo import AlertRepository
from app.repositories.source_repo import SourceRepository
from app.repositories.user_repo import UserRepository
from app.repositories.zone_repo import ZoneRepository
from app.schemas.serializers import (
    serialize_alert,
    serialize_alert_detail,
    serialize_source,
)
from app.services.audit_service import AuditService
from app.services.engine_sync import (
    alert_model_to_open_snapshot,
    alert_model_to_reraise_snapshot,
    format_zone_live_state,
)
from app.services.settings_service import SettingsService


def _naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


@dataclass
class CommittedSideEffects:
    """Post-commit events & push calls collected during persist_actions()."""

    zone_updates: list[tuple[Zone, dict[str, Any], list[dict[str, Any]], int | None]] = field(
        default_factory=list
    )
    alert_news: list[dict[str, Any]] = field(default_factory=list)
    alert_updateds: list[dict[str, Any]] = field(default_factory=list)
    alert_escalateds: list[tuple[dict[str, Any], str]] = field(default_factory=list)
    push_calls: list[tuple[dict[str, Any], str]] = field(default_factory=list)


class AlertService:
    def __init__(
        self,
        *,
        alert_repo: AlertRepository,
        zone_repo: ZoneRepository,
        source_repo: SourceRepository,
        user_repo: UserRepository,
        audit_service: AuditService,
        settings_service: SettingsService,
        emitter: RealtimeEmitter,
        notifier: Notifier,
        clock: Clock | None = None,
        engine_lock: threading.Lock | None = None,
        zone_engine: ZoneEngine | None = None,
    ) -> None:
        self._repo = alert_repo
        self._zone_repo = zone_repo
        self._source_repo = source_repo
        self._user_repo = user_repo
        self._audit = audit_service
        self._settings = settings_service
        self._emitter = emitter
        self._notifier = notifier
        self._clock: Clock = clock or SystemClock()
        self._engine_lock = engine_lock or threading.Lock()
        self._zone_engine = zone_engine

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _users_map_for_alerts(self, alerts: list[AlertModel]) -> dict[int, User]:
        uids: set[int] = set()
        for a in alerts:
            for uid in (a.acknowledged_by, a.responding_by, a.resolved_by):
                if uid is not None:
                    uids.add(uid)
        result: dict[int, User] = {}
        for uid in uids:
            u = self._user_repo.get(uid)
            if u is not None:
                result[uid] = u
        return result

    def _serialize_one(self, alert: AlertModel) -> dict[str, Any]:
        zone = self._zone_repo.get(alert.zone_id)
        assert zone is not None
        umap = self._users_map_for_alerts([alert])
        return serialize_alert(alert, zone, umap)

    # ------------------------------------------------------------------
    # Engine Action Persistence & Post-Commit Dispatch
    # ------------------------------------------------------------------
    def persist_actions(
        self,
        actions: list[EngineAction],
        *,
        zone_engine: ZoneEngine | None = None,
    ) -> CommittedSideEffects:
        """Apply *actions* in ONE DB transaction, then sync snapshots after commit.

        NEVER emits Socket.IO events or sends push inside this method.
        """
        effects = CommittedSideEffects()
        if not actions:
            return effects

        eng = zone_engine or self._zone_engine
        touched_alerts: dict[int, AlertModel] = {}
        created_by_zone: dict[int, AlertModel] = {}
        new_alert_ids: set[int] = set()
        updated_alert_ids: set[int] = set()
        escalated_reasons: list[tuple[int, str]] = []
        pending_pushes: list[tuple[int | None, int, str]] = []
        emit_zone_actions: list[EmitZoneUpdate] = []
        cleared_open_zones: set[int] = set()
        cleared_reraise_ids: list[tuple[int, int]] = []
        feed_lost_flags: dict[int, bool] = {}

        def _get_alert(aid: int) -> AlertModel | None:
            if aid in touched_alerts:
                return touched_alerts[aid]
            obj = self._repo.get(aid)
            if obj is not None:
                touched_alerts[aid] = obj
            return obj

        try:
            for act in actions:
                if isinstance(act, CreateAlert):
                    data: dict[str, Any] = {}
                    if act.reason:
                        data["reason"] = act.reason
                    if act.previous_alert_id is not None:
                        data["previous_alert_id"] = act.previous_alert_id
                    alert = AlertModel(  # pyrefly: ignore[unexpected-keyword]
                        zone_id=act.zone_id,
                        level=act.level,
                        peak_level=act.peak_level,
                        status="NEW",
                        condition_active=True,
                        peak_density=act.peak_density,
                        peak_count=act.peak_count,
                        created_at=_naive_utc(act.created_at),
                        previous_alert_id=act.previous_alert_id,
                    )
                    self._repo.add(alert)
                    self._repo.add_event(
                        AlertEvent(  # pyrefly: ignore[unexpected-keyword]
                            alert_id=alert.id,
                            type="CREATED",
                            actor_id=None,
                            data_json=json.dumps(data),
                            created_at=_naive_utc(act.created_at),
                        )
                    )
                    touched_alerts[alert.id] = alert
                    created_by_zone[act.zone_id] = alert
                    new_alert_ids.add(alert.id)
                    cleared_open_zones.discard(act.zone_id)

                elif isinstance(act, ReopenAlert):
                    alert = _get_alert(act.alert_id)
                    if alert is not None:
                        alert.level = act.level
                        alert.peak_level = act.peak_level
                        alert.peak_density = act.peak_density
                        alert.peak_count = act.peak_count
                        alert.condition_active = True
                        alert.condition_cleared_at = None
                        if act.level == "CRITICAL":
                            alert.last_escalated_at = _naive_utc(act.reopened_at)
                        self._repo.add_event(
                            AlertEvent(  # pyrefly: ignore[unexpected-keyword]
                                alert_id=alert.id,
                                type="REOPENED",
                                actor_id=None,
                                data_json=json.dumps({"level": act.level}),
                                created_at=_naive_utc(act.reopened_at),
                            )
                        )
                        updated_alert_ids.add(alert.id)
                        feed_lost_flags[alert.id] = False

                elif isinstance(act, EscalateAlert):
                    alert = _get_alert(act.alert_id)
                    if alert is not None:
                        alert.level = act.new_level
                        alert.peak_level = act.peak_level
                        alert.peak_density = act.peak_density
                        alert.peak_count = act.peak_count
                        alert.last_escalated_at = _naive_utc(act.escalated_at)
                        self._repo.add_event(
                            AlertEvent(  # pyrefly: ignore[unexpected-keyword]
                                alert_id=alert.id,
                                type="ESCALATED",
                                actor_id=None,
                                data_json=json.dumps(
                                    {"level": act.new_level, "peak_density": act.peak_density}
                                ),
                                created_at=_naive_utc(act.escalated_at),
                            )
                        )
                        updated_alert_ids.add(alert.id)
                        escalated_reasons.append((alert.id, "LEVEL_UP"))

                elif isinstance(act, UpdatePeak):
                    alert = _get_alert(act.alert_id)
                    if alert is not None:
                        changed = False
                        if act.peak_density > alert.peak_density:
                            alert.peak_density = act.peak_density
                            changed = True
                        if act.peak_count > alert.peak_count:
                            alert.peak_count = act.peak_count
                            changed = True
                        if act.level is not None and act.level != alert.level:
                            alert.level = act.level
                            changed = True
                        if changed:
                            updated_alert_ids.add(alert.id)

                elif isinstance(act, ClearCondition):
                    alert = _get_alert(act.alert_id)
                    if alert is not None:
                        alert.condition_active = False
                        alert.condition_cleared_at = _naive_utc(act.cleared_at)
                        updated_alert_ids.add(alert.id)

                elif isinstance(act, AutoClearAlert):
                    alert = _get_alert(act.alert_id)
                    if alert is not None:
                        alert.status = "AUTO_CLEARED"
                        self._repo.add_event(
                            AlertEvent(  # pyrefly: ignore[unexpected-keyword]
                                alert_id=alert.id,
                                type="AUTO_CLEARED",
                                actor_id=None,
                                data_json="{}",
                                created_at=_naive_utc(act.cleared_at),
                            )
                        )
                        updated_alert_ids.add(alert.id)
                        cleared_open_zones.add(act.zone_id)

                elif isinstance(act, RecordFeedEvent):
                    alert = _get_alert(act.alert_id)
                    if alert is not None:
                        self._repo.add_event(
                            AlertEvent(  # pyrefly: ignore[unexpected-keyword]
                                alert_id=alert.id,
                                type=act.event_type,
                                actor_id=None,
                                data_json="{}",
                                created_at=_naive_utc(act.occurred_at),
                            )
                        )
                        feed_lost_flags[alert.id] = act.event_type == "FEED_LOST"
                        updated_alert_ids.add(alert.id)

                elif isinstance(act, Remind):
                    alert = _get_alert(act.alert_id)
                    if alert is not None:
                        alert.last_escalated_at = _naive_utc(act.reminded_at)
                        self._repo.add_event(
                            AlertEvent(  # pyrefly: ignore[unexpected-keyword]
                                alert_id=alert.id,
                                type="REMINDER",
                                actor_id=None,
                                data_json="{}",
                                created_at=_naive_utc(act.reminded_at),
                            )
                        )
                        updated_alert_ids.add(alert.id)
                        escalated_reasons.append((alert.id, "CRITICAL_UNACKNOWLEDGED"))

                elif isinstance(act, MarkReraiseChecked):
                    alert = _get_alert(act.alert_id)
                    if alert is not None:
                        alert.reraise_check_at = None
                    cleared_reraise_ids.append((act.zone_id, act.alert_id))

                elif isinstance(act, SendPush):
                    aid = act.alert_id
                    if aid is None and act.zone_id in created_by_zone:
                        aid = created_by_zone[act.zone_id].id
                    if aid is not None:
                        alert_obj = _get_alert(aid)
                        if alert_obj is not None:
                            alert_obj.last_push_at = _naive_utc(self._clock.utcnow())
                    pending_pushes.append((aid, act.zone_id, act.reason))

                elif isinstance(act, EmitZoneUpdate):
                    emit_zone_actions.append(act)

            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

        # ------------------------------------------------------------------
        # POST-COMMIT ONLY: sync engine snapshots & build side-effect payloads
        # ------------------------------------------------------------------
        if eng is not None:
            for zid in cleared_open_zones:
                eng.set_open_alert(zid, None)
            for zid, aid in cleared_reraise_ids:
                eng._pending_reraises[zid] = [
                    r for r in eng._pending_reraises.get(zid, []) if r.id != aid
                ]
            for alert in touched_alerts.values():
                if alert.status in ("NEW", "ACKNOWLEDGED", "RESPONDING"):
                    lost = feed_lost_flags.get(
                        alert.id, self._repo.has_feed_lost_since_open(alert.id)
                    )
                    eng.set_open_alert(
                        alert.zone_id,
                        alert_model_to_open_snapshot(alert, feed_lost_emitted=lost),
                    )

        serialized_cache: dict[int, dict[str, Any]] = {}
        for aid, alert in touched_alerts.items():
            serialized_cache[aid] = self._serialize_one(alert)

        for aid in sorted(new_alert_ids):
            effects.alert_news.append(serialized_cache[aid])
        for aid in sorted(updated_alert_ids - new_alert_ids):
            effects.alert_updateds.append(serialized_cache[aid])
        for aid, reason in escalated_reasons:
            if aid in serialized_cache:
                effects.alert_escalateds.append((serialized_cache[aid], reason))
        for aid, zid, reason in pending_pushes:
            if aid is not None and aid in serialized_cache:
                effects.push_calls.append((serialized_cache[aid], reason))

        # Zone updates (public + police detail)
        for zu in emit_zone_actions:
            zone = self._zone_repo.get(zu.zone_id)
            if zone is None or not zone.is_active:
                continue
            ref_now = zu.updated_at or self._clock.utcnow()
            live_state = {
                "level": zu.level,
                "trend": zu.trend,
                "density": round(zu.density, 2) if zu.density is not None else None,
                "count": round(zu.count, 2) if zu.count is not None else None,
                "live_updated_at": to_iso_z(zu.updated_at),
            }
            sources_info: list[dict[str, Any]] = []
            for src in self._source_repo.list_by_zone(zone.id, include_inactive=False):
                st_info = eng.get_source_state(src.id, ref_now) if eng is not None else None
                if st_info is not None:
                    sources_info.append(
                        serialize_source(
                            src,
                            status=st_info["status"],
                            last_frame_at=to_iso_z(st_info["last_frame_at"]),
                        )
                    )
                else:
                    sources_info.append(serialize_source(src))
            open_alert_id = self._zone_repo.get_open_alert_id(zone.id)
            effects.zone_updates.append((zone, live_state, sources_info, open_alert_id))

        return effects

    def dispatch_side_effects(self, effects: CommittedSideEffects) -> None:
        """Emit realtime Socket.IO events and invoke Notifier (ALWAYS post-commit)."""
        for zone, live_state, sources_info, open_alert_id in effects.zone_updates:
            self._emitter.emit_zone_update(zone, live_state)
            self._emitter.emit_zone_detail(
                zone, live_state, sources=sources_info, open_alert_id=open_alert_id
            )
        for alert_payload in effects.alert_news:
            self._emitter.emit_alert_new(alert_payload)
        for alert_payload in effects.alert_updateds:
            self._emitter.emit_alert_updated(alert_payload)
        for alert_payload, reason in effects.alert_escalateds:
            self._emitter.emit_alert_escalated(alert_payload, reason)
        for alert_payload, reason in effects.push_calls:
            self._notifier.notify_alert(alert_payload, reason)

    def apply(
        self,
        actions: list[EngineAction],
        *,
        zone_engine: ZoneEngine | None = None,
    ) -> CommittedSideEffects:
        """Persist *actions* in one transaction, then emit & notify after commit."""
        effects = self.persist_actions(actions, zone_engine=zone_engine)
        self.dispatch_side_effects(effects)
        return effects

    # ------------------------------------------------------------------
    # REST Read endpoints
    # ------------------------------------------------------------------
    def list_alerts(
        self,
        *,
        statuses: list[str] | None = None,
        level: str | None = None,
        zone_id: int | None = None,
        dt_from: datetime | None = None,
        dt_to: datetime | None = None,
        active: bool | None = None,
        page: int = 1,
        limit: int = 20,
        sort: str = "-created_at",
    ) -> tuple[list[dict[str, Any]], int]:
        alerts, total = self._repo.list_paginated(
            statuses=statuses,
            level=level,
            zone_id=zone_id,
            dt_from=dt_from,
            dt_to=dt_to,
            active=active,
            page=page,
            limit=limit,
            sort=sort,
        )
        umap = self._users_map_for_alerts(alerts)
        zones_cache: dict[int, Zone] = {}
        serialized: list[dict[str, Any]] = []
        for a in alerts:
            z = zones_cache.get(a.zone_id)
            if z is None:
                z = self._zone_repo.get(a.zone_id)
                assert z is not None
                zones_cache[a.zone_id] = z
            serialized.append(serialize_alert(a, z, umap))
        return serialized, total

    def get_alert_detail(self, alert_id: int) -> dict[str, Any]:
        alert = self._repo.get(alert_id)
        if alert is None:
            raise NotFound(f"Alert {alert_id} not found.")
        zone = self._zone_repo.get(alert.zone_id)
        assert zone is not None
        events = self._repo.list_events(alert.id)
        umap = self._users_map_for_alerts([alert])
        for ev in events:
            if ev.actor_id is not None and ev.actor_id not in umap:
                u = self._user_repo.get(ev.actor_id)
                if u is not None:
                    umap[ev.actor_id] = u
        return serialize_alert_detail(alert, zone, events, umap)

    # ------------------------------------------------------------------
    # REST Manual Transitions (contract §4.3)
    # ------------------------------------------------------------------
    def _transition_alert(
        self,
        alert_id: int,
        target_status: str,
        actor: User,
        note: str | None = None,
    ) -> dict[str, Any]:
        should_emit = False
        with self._engine_lock:
            alert = self._repo.get(alert_id)
            if alert is None:
                raise NotFound(f"Alert {alert_id} not found.")

            # Idempotent repeat of same status -> 200 no-op
            if alert.status == target_status:
                return self._serialize_one(alert)

            # Enforce legal transitions per contract §4.3
            allowed = False
            if target_status == "ACKNOWLEDGED" and alert.status == "NEW":
                allowed = True
            elif target_status == "RESPONDING" and alert.status in ("NEW", "ACKNOWLEDGED"):
                allowed = True
            elif target_status == "RESOLVED" and alert.status in (
                "NEW",
                "ACKNOWLEDGED",
                "RESPONDING",
            ):
                allowed = True

            if not allowed:
                raise InvalidTransition(
                    f"Cannot transition alert from {alert.status} to {target_status}."
                )

            now_aware = self._clock.utcnow()
            now_naive = _naive_utc(now_aware)
            event_data: dict[str, Any] = {}
            if note:
                event_data["note"] = note

            if target_status == "ACKNOWLEDGED":
                alert.status = "ACKNOWLEDGED"
                alert.acknowledged_at = now_naive
                alert.acknowledged_by = actor.id
                audit_action = "ALERT_ACKNOWLEDGED"
            elif target_status == "RESPONDING":
                alert.status = "RESPONDING"
                alert.responding_at = now_naive
                alert.responding_by = actor.id
                audit_action = "ALERT_RESPONDING"
            else:  # RESOLVED
                alert.status = "RESOLVED"
                alert.resolved_at = now_naive
                alert.resolved_by = actor.id
                alert.resolution_note = note
                audit_action = "ALERT_RESOLVED"
                if alert.condition_active:
                    reraise_s = float(
                        self._settings.get_settings().get("reraise_after_s", 60.0)
                    )
                    alert.reraise_check_at = now_naive + timedelta(seconds=reraise_s)

            self._repo.add_event(
                AlertEvent(  # pyrefly: ignore[unexpected-keyword]
                    alert_id=alert.id,
                    type=target_status,
                    actor_id=actor.id,
                    data_json=json.dumps(event_data),
                    created_at=now_naive,
                )
            )
            self._audit.log(actor, audit_action, "alert", alert.id, event_data)
            db.session.commit()
            db.session.refresh(alert)

            # Keep ZoneEngine synchronized after DB commit
            if self._zone_engine is not None:
                if target_status == "RESOLVED":
                    self._zone_engine.set_open_alert(alert.zone_id, None)
                    rs = alert_model_to_reraise_snapshot(alert)
                    if rs is not None:
                        self._zone_engine._pending_reraises.setdefault(
                            alert.zone_id, []
                        ).append(rs)
                else:
                    lost = self._repo.has_feed_lost_since_open(alert.id)
                    self._zone_engine.set_open_alert(
                        alert.zone_id,
                        alert_model_to_open_snapshot(alert, feed_lost_emitted=lost),
                    )

            payload = self._serialize_one(alert)
            should_emit = True

        if should_emit:
            self._emitter.emit_alert_updated(payload)
        return payload

    def acknowledge(self, alert_id: int, actor: User, note: str | None = None) -> dict[str, Any]:
        return self._transition_alert(alert_id, "ACKNOWLEDGED", actor, note=note)

    def respond(self, alert_id: int, actor: User, note: str | None = None) -> dict[str, Any]:
        return self._transition_alert(alert_id, "RESPONDING", actor, note=note)

    def resolve(self, alert_id: int, actor: User, note: str | None = None) -> dict[str, Any]:
        return self._transition_alert(alert_id, "RESOLVED", actor, note=note)
