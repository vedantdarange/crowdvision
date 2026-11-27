"""app/services/engine_sync.py — Boot & reload bridge between DB repositories and ZoneEngine."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from app.core.time import to_iso_z
from app.engine.alert_rules import OpenAlertSnapshot, ResolvedReraiseSnapshot
from app.engine.zone_engine import EngineSettings, SourceConfig, ZoneConfig, ZoneEngine
from app.models.models import AlertModel
from app.schemas.serializers import LIVE_STATE_PLACEHOLDER

if TYPE_CHECKING:
    from app.repositories.alert_repo import AlertRepository
    from app.repositories.source_repo import SourceRepository
    from app.repositories.zone_repo import ZoneRepository
    from app.services.settings_service import SettingsService


def _utc_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def alert_model_to_open_snapshot(
    alert: AlertModel, *, feed_lost_emitted: bool = False
) -> OpenAlertSnapshot:
    return OpenAlertSnapshot(
        id=alert.id,
        zone_id=alert.zone_id,
        status=alert.status,
        level=alert.level,
        peak_level=alert.peak_level,
        condition_active=alert.condition_active,
        peak_density=alert.peak_density,
        peak_count=alert.peak_count,
        created_at=_utc_aware(alert.created_at),
        last_escalated_at=(
            _utc_aware(alert.last_escalated_at)
            if alert.last_escalated_at is not None
            else None
        ),
        last_push_at=(
            _utc_aware(alert.last_push_at) if alert.last_push_at is not None else None
        ),
        feed_lost_emitted=feed_lost_emitted,
    )


def alert_model_to_reraise_snapshot(alert: AlertModel) -> ResolvedReraiseSnapshot | None:
    if alert.resolved_at is None or alert.reraise_check_at is None:
        return None
    return ResolvedReraiseSnapshot(
        id=alert.id,
        zone_id=alert.zone_id,
        status=alert.status,
        resolved_at=_utc_aware(alert.resolved_at),
        reraise_check_at=_utc_aware(alert.reraise_check_at),
    )


def build_engine_inputs(
    zone_repo: "ZoneRepository",
    source_repo: "SourceRepository",
    settings_service: "SettingsService",
) -> tuple[list[ZoneConfig], list[SourceConfig], EngineSettings]:
    zones = [
        ZoneConfig(
            id=z.id,
            mode=z.mode,
            warning_density=z.warning_density,
            critical_density=z.critical_density,
            warning_count=z.warning_count,
            critical_count=z.critical_count,
        )
        for z in zone_repo.list_active()
    ]
    active_zone_ids = {z.id for z in zones}
    sources = [
        SourceConfig(
            id=s.id,
            zone_id=s.zone_id,
            coverage_area_m2=s.coverage_area_m2,
        )
        for s in source_repo.list_all(include_inactive=False)
        if s.zone_id in active_zone_ids
    ]
    s_dict = settings_service.get_settings()
    eng_settings = EngineSettings(
        smoothing_window=int(s_dict.get("smoothing_window", 5)),
        debounce_s=float(s_dict.get("debounce_s", 3.0)),
        clear_s=float(s_dict.get("clear_s", 8.0)),
        hysteresis_ratio=float(s_dict.get("hysteresis_ratio", 0.85)),
        stale_after_s=float(s_dict.get("stale_after_s", 10.0)),
        cooldown_s=float(s_dict.get("cooldown_s", 60.0)),
        escalation_s=float(s_dict.get("escalation_s", 60.0)),
        reraise_after_s=float(s_dict.get("reraise_after_s", 60.0)),
    )
    return zones, sources, eng_settings


def boot_engine_from_db(
    *,
    zone_engine: ZoneEngine,
    zone_repo: "ZoneRepository",
    source_repo: "SourceRepository",
    alert_repo: "AlertRepository",
    settings_service: "SettingsService",
) -> None:
    """Hydrate *zone_engine* from DB zones, sources, settings, and open alerts."""
    zones, sources, eng_settings = build_engine_inputs(
        zone_repo, source_repo, settings_service
    )
    open_snaps = [
        alert_model_to_open_snapshot(
            a, feed_lost_emitted=alert_repo.has_feed_lost_since_open(a.id)
        )
        for a in alert_repo.list_open()
    ]
    reraise_snaps = []
    for a in alert_repo.list_pending_reraises():
        rs = alert_model_to_reraise_snapshot(a)
        if rs is not None:
            reraise_snaps.append(rs)

    zone_engine.boot(
        zones,
        sources,
        eng_settings,
        open_alerts=open_snaps,
        pending_reraises=reraise_snaps,
    )


def reload_engine_from_db(
    *,
    zone_engine: ZoneEngine,
    zone_repo: "ZoneRepository",
    source_repo: "SourceRepository",
    settings_service: "SettingsService",
) -> None:
    """Reload *zone_engine* configs & settings while preserving buffers/levels."""
    zones, sources, eng_settings = build_engine_inputs(
        zone_repo, source_repo, settings_service
    )
    zone_engine.reload(zones, sources, eng_settings)


def format_zone_live_state(
    engine_state: dict[str, Any] | None,
) -> dict[str, Any]:
    """Convert ZoneEngine.get_zone_state() dict to serializer-compatible LiveState."""
    if engine_state is None:
        return LIVE_STATE_PLACEHOLDER
    live_dt = engine_state.get("live_updated_at")
    return {
        "level": engine_state["level"],
        "trend": engine_state["trend"],
        "density": (
            round(float(engine_state["density"]), 2)
            if engine_state.get("density") is not None
            else None
        ),
        "count": (
            round(float(engine_state["count"]), 2)
            if engine_state.get("count") is not None
            else None
        ),
        "live_updated_at": to_iso_z(live_dt) if isinstance(live_dt, datetime) else live_dt,
    }
