"""app/engine/zone_engine.py — Pure Python ZoneEngine orchestrator (contract §4, plan §8.1).

Coordinates:
  sources (RollingMedian + freshness) -> zone metric (max over fresh sources)
  -> ZoneMachine (hysteresis, debounce, clear hold, NO_DATA, trend)
  -> alert_rules (actions out).

No Flask, SQLAlchemy, sockets, or threading imports in ZoneEngine.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from app.engine.alert_rules import (
    AutoClearAlert,
    ClearCondition,
    CreateAlert,
    EmitZoneUpdate,
    EngineAction,
    EscalateAlert,
    MarkReraiseChecked,
    OpenAlertSnapshot,
    RecordFeedEvent,
    Remind,
    ReopenAlert,
    ResolvedReraiseSnapshot,
    SendPush,
    UpdatePeak,
    coerce_open_alert,
    coerce_resolved_reraise,
    evaluate_alert_transition,
    evaluate_tick_alerts,
)
from app.engine.smoothing import RollingMedian
from app.engine.zone_machine import LevelTransition, ZoneMachine

__all__ = [
    "EngineSettings",
    "ZoneConfig",
    "SourceConfig",
    "ZoneEngine",
]

_UNSET: Any = object()


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Engine configuration dataclasses (pure Python)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class EngineSettings:
    smoothing_window: int = 5
    debounce_s: float = 3.0
    clear_s: float = 8.0
    hysteresis_ratio: float = 0.85
    stale_after_s: float = 10.0
    cooldown_s: float = 60.0
    escalation_s: float = 60.0
    reraise_after_s: float = 60.0


@dataclass(frozen=True)
class ZoneConfig:
    id: int
    mode: str = "DENSITY"  # 'DENSITY' | 'COUNT'
    warning_density: float = 3.0
    critical_density: float = 4.0
    warning_count: int | None = None
    critical_count: int | None = None


@dataclass(frozen=True)
class SourceConfig:
    id: int
    zone_id: int
    coverage_area_m2: float


def _coerce_settings(raw: EngineSettings | dict[str, Any] | None) -> EngineSettings:
    if raw is None:
        return EngineSettings()
    if isinstance(raw, EngineSettings):
        return raw
    return EngineSettings(
        smoothing_window=int(raw.get("smoothing_window", 5)),
        debounce_s=float(raw.get("debounce_s", 3.0)),
        clear_s=float(raw.get("clear_s", 8.0)),
        hysteresis_ratio=float(raw.get("hysteresis_ratio", 0.85)),
        stale_after_s=float(raw.get("stale_after_s", 10.0)),
        cooldown_s=float(raw.get("cooldown_s", 60.0)),
        escalation_s=float(raw.get("escalation_s", 60.0)),
        reraise_after_s=float(raw.get("reraise_after_s", 60.0)),
    )


def _coerce_zone_cfg(raw: ZoneConfig | dict[str, Any]) -> ZoneConfig:
    if isinstance(raw, ZoneConfig):
        return raw
    w_cnt = raw.get("warning_count")
    c_cnt = raw.get("critical_count")
    return ZoneConfig(
        id=int(raw["id"]),
        mode=str(raw.get("mode", "DENSITY")),
        warning_density=float(raw.get("warning_density", 3.0)),
        critical_density=float(raw.get("critical_density", 4.0)),
        warning_count=int(w_cnt) if w_cnt is not None else None,
        critical_count=int(c_cnt) if c_cnt is not None else None,
    )


def _coerce_source_cfg(raw: SourceConfig | dict[str, Any]) -> SourceConfig:
    if isinstance(raw, SourceConfig):
        return raw
    return SourceConfig(
        id=int(raw["id"]),
        zone_id=int(raw["zone_id"]),
        coverage_area_m2=float(raw["coverage_area_m2"]),
    )


# ---------------------------------------------------------------------------
# Internal mutable runtime state per source / zone
# ---------------------------------------------------------------------------
@dataclass
class _SourceRuntime:
    config: SourceConfig
    smoother: RollingMedian
    last_frame_at: datetime | None = None
    smoothed_count: float | None = None
    density: float | None = None


@dataclass
class _ZoneRuntime:
    config: ZoneConfig
    machine: ZoneMachine = field(default_factory=ZoneMachine)
    last_density: float | None = None
    last_count: float | None = None
    live_updated_at: datetime | None = None
    last_warning_push_at: datetime | None = None


class ZoneEngine:
    """Pure Python zone & alert rules engine (state in, actions out)."""

    def __init__(self, *, auto_commit_alerts: bool = True) -> None:
        self._settings = EngineSettings()
        self._zones: dict[int, _ZoneRuntime] = {}
        self._sources: dict[int, _SourceRuntime] = {}
        self._open_alerts: dict[int, OpenAlertSnapshot] = {}
        self._pending_reraises: dict[int, list[ResolvedReraiseSnapshot]] = {}
        self._auto_commit_alerts = auto_commit_alerts
        self._next_alert_id = 1

    @property
    def settings(self) -> EngineSettings:
        return self._settings

    def reset(self) -> None:
        """Clear all runtime zones, sources, and alert snapshots."""
        self._zones.clear()
        self._sources.clear()
        self._open_alerts.clear()
        self._pending_reraises.clear()
        self._next_alert_id = 1

    # ------------------------------------------------------------------
    # Boot & reload lifecycle
    # ------------------------------------------------------------------
    def boot(
        self,
        zones: list[ZoneConfig | dict[str, Any]],
        sources: list[SourceConfig | dict[str, Any]],
        settings: EngineSettings | dict[str, Any] | None = None,
        *,
        open_alerts: list[OpenAlertSnapshot | dict[str, Any]] | dict[int, OpenAlertSnapshot | dict[str, Any]] | None = None,
        pending_reraises: list[ResolvedReraiseSnapshot | dict[str, Any]] | None = None,
    ) -> None:
        """Initialise engine state at startup, loading existing open alerts."""
        self._settings = _coerce_settings(settings)
        self._zones = {}
        self._sources = {}
        self._open_alerts = {}
        self._pending_reraises = {}

        for raw_z in zones:
            zc = _coerce_zone_cfg(raw_z)
            self._zones[zc.id] = _ZoneRuntime(config=zc)

        for raw_s in sources:
            sc = _coerce_source_cfg(raw_s)
            self._sources[sc.id] = _SourceRuntime(
                config=sc,
                smoother=RollingMedian(window=self._settings.smoothing_window),
            )

        max_id = 0
        if open_alerts is not None:
            items = open_alerts.values() if isinstance(open_alerts, dict) else open_alerts
            for raw_a in items:
                snap = coerce_open_alert(raw_a)
                if snap is not None and snap.zone_id in self._zones:
                    self._open_alerts[snap.zone_id] = snap
                    max_id = max(max_id, snap.id)

        if pending_reraises is not None:
            for raw_r in pending_reraises:
                rs = coerce_resolved_reraise(raw_r)
                if rs.zone_id in self._zones:
                    self._pending_reraises.setdefault(rs.zone_id, []).append(rs)
                    max_id = max(max_id, rs.id)

        self._next_alert_id = max(self._next_alert_id, max_id + 1)

    def reload(
        self,
        zones: list[ZoneConfig | dict[str, Any]],
        sources: list[SourceConfig | dict[str, Any]],
        settings: EngineSettings | dict[str, Any] | None = None,
    ) -> None:
        """Reload configs & settings while PRESERVING buffers, levels, and timers."""
        new_settings = _coerce_settings(settings)
        self._settings = new_settings

        new_zones: dict[int, _ZoneRuntime] = {}
        for raw_z in zones:
            zc = _coerce_zone_cfg(raw_z)
            existing_z = self._zones.get(zc.id)
            if existing_z is not None:
                existing_z.config = zc
                new_zones[zc.id] = existing_z
            else:
                new_zones[zc.id] = _ZoneRuntime(config=zc)
        self._zones = new_zones

        new_sources: dict[int, _SourceRuntime] = {}
        for raw_s in sources:
            sc = _coerce_source_cfg(raw_s)
            existing_s = self._sources.get(sc.id)
            if existing_s is not None:
                existing_s.config = sc
                existing_s.smoother.resize(new_settings.smoothing_window)
                if existing_s.smoothed_count is not None:
                    existing_s.density = existing_s.smoothed_count / max(sc.coverage_area_m2, 1e-6)
                new_sources[sc.id] = existing_s
            else:
                new_sources[sc.id] = _SourceRuntime(
                    config=sc,
                    smoother=RollingMedian(window=new_settings.smoothing_window),
                )
        self._sources = new_sources

    # ------------------------------------------------------------------
    # External alert sync helpers (for DB AlertService in B4b & pure tests)
    # ------------------------------------------------------------------
    def set_open_alert(self, zone_id: int, snapshot: OpenAlertSnapshot | dict[str, Any] | None) -> None:
        snap = coerce_open_alert(snapshot)
        if snap is None:
            self._open_alerts.pop(zone_id, None)
        else:
            self._open_alerts[zone_id] = snap
            self._next_alert_id = max(self._next_alert_id, snap.id + 1)

    def get_open_alert(self, zone_id: int) -> OpenAlertSnapshot | None:
        return self._open_alerts.get(zone_id)

    def acknowledge_alert(self, zone_id: int) -> None:
        snap = self._open_alerts.get(zone_id)
        if snap is not None and snap.status == "NEW":
            snap.status = "ACKNOWLEDGED"

    def respond_alert(self, zone_id: int) -> None:
        snap = self._open_alerts.get(zone_id)
        if snap is not None and snap.status in ("NEW", "ACKNOWLEDGED"):
            snap.status = "RESPONDING"

    def resolve_alert(self, zone_id: int, now: datetime) -> ResolvedReraiseSnapshot | None:
        """Resolve a zone's open alert; schedule reraise check if condition_active."""
        now_utc = _ensure_utc(now)
        snap = self._open_alerts.pop(zone_id, None)
        if snap is None:
            return None
        if snap.condition_active:
            reraise_dt = now_utc + timedelta(seconds=self._settings.reraise_after_s)
            rs = ResolvedReraiseSnapshot(
                id=snap.id,
                zone_id=zone_id,
                status="RESOLVED",
                resolved_at=now_utc,
                reraise_check_at=reraise_dt,
            )
            self._pending_reraises.setdefault(zone_id, []).append(rs)
            return rs
        return None

    # ------------------------------------------------------------------
    # Inspection helpers
    # ------------------------------------------------------------------
    def get_zone_state(self, zone_id: int, now: datetime | None = None) -> dict[str, Any] | None:
        z_state = self._zones.get(zone_id)
        if z_state is None:
            return None
        now_s = _ensure_utc(now).timestamp() if now is not None else (
            z_state.live_updated_at.timestamp() if z_state.live_updated_at is not None else 0.0
        )
        return {
            "level": z_state.machine.level,
            "trend": z_state.machine.trend(now_s, z_state.config.mode),
            "density": z_state.last_density,
            "count": z_state.last_count,
            "live_updated_at": z_state.live_updated_at,
        }

    def get_source_state(
        self, source_id: int, now: datetime
    ) -> dict[str, Any] | None:
        src = self._sources.get(source_id)
        if src is None:
            return None
        now_utc = _ensure_utc(now)
        online = (
            src.last_frame_at is not None
            and (now_utc - src.last_frame_at).total_seconds() <= self._settings.stale_after_s
        )
        return {
            "status": "ONLINE" if online else "OFFLINE",
            "last_frame_at": src.last_frame_at,
            "smoothed_count": src.smoothed_count,
            "density": src.density,
        }

    # ------------------------------------------------------------------
    # Core pipeline: ingest & tick
    # ------------------------------------------------------------------
    def _compute_zone_metric(
        self, zone_cfg: ZoneConfig, now: datetime
    ) -> tuple[float | None, float | None, float | None]:
        """Compute (metric, zone_density, zone_count) as max over fresh sources."""
        best_metric: float | None = None
        best_density: float | None = None
        best_count: float | None = None

        use_count = (
            zone_cfg.mode == "COUNT"
            and zone_cfg.warning_count is not None
            and zone_cfg.critical_count is not None
        )

        for src in self._sources.values():
            if src.config.zone_id != zone_cfg.id:
                continue
            if src.last_frame_at is None or src.smoothed_count is None or src.density is None:
                continue
            if (now - src.last_frame_at).total_seconds() > self._settings.stale_after_s:
                continue

            val = src.smoothed_count if use_count else src.density
            if best_metric is None or val > best_metric:
                best_metric = val
                best_density = src.density
                best_count = src.smoothed_count

        return best_metric, best_density, best_count

    def _thresholds_for(self, zone_cfg: ZoneConfig) -> tuple[float, float]:
        if (
            zone_cfg.mode == "COUNT"
            and zone_cfg.warning_count is not None
            and zone_cfg.critical_count is not None
        ):
            return float(zone_cfg.warning_count), float(zone_cfg.critical_count)
        return float(zone_cfg.warning_density), float(zone_cfg.critical_density)

    def _apply_actions_in_memory(self, actions: list[EngineAction], now: datetime) -> None:
        """Apply emitted alert actions to in-memory snapshots."""
        for act in actions:
            if isinstance(act, CreateAlert):
                aid = self._next_alert_id
                self._next_alert_id += 1
                self._open_alerts[act.zone_id] = OpenAlertSnapshot(
                    id=aid,
                    zone_id=act.zone_id,
                    status="NEW",
                    level=act.level,
                    peak_level=act.peak_level,
                    condition_active=True,
                    peak_density=act.peak_density,
                    peak_count=act.peak_count,
                    created_at=act.created_at,
                )
            elif isinstance(act, ReopenAlert):
                snap = self._open_alerts.get(act.zone_id)
                if snap is not None:
                    snap.level = act.level
                    snap.peak_level = act.peak_level
                    snap.peak_density = act.peak_density
                    snap.peak_count = act.peak_count
                    snap.condition_active = True
                    snap.feed_lost_emitted = False
                    if act.level == "CRITICAL":
                        snap.last_escalated_at = act.reopened_at
            elif isinstance(act, EscalateAlert):
                snap = self._open_alerts.get(act.zone_id)
                if snap is not None:
                    snap.level = act.new_level
                    snap.peak_level = act.peak_level
                    snap.peak_density = act.peak_density
                    snap.peak_count = act.peak_count
                    snap.last_escalated_at = act.escalated_at
            elif isinstance(act, UpdatePeak):
                snap = self._open_alerts.get(act.zone_id)
                if snap is not None:
                    snap.peak_density = act.peak_density
                    snap.peak_count = act.peak_count
                    if act.level is not None:
                        snap.level = act.level
            elif isinstance(act, ClearCondition):
                snap = self._open_alerts.get(act.zone_id)
                if snap is not None:
                    snap.condition_active = False
            elif isinstance(act, AutoClearAlert):
                self._open_alerts.pop(act.zone_id, None)
            elif isinstance(act, RecordFeedEvent):
                snap = self._open_alerts.get(act.zone_id)
                if snap is not None:
                    snap.feed_lost_emitted = act.event_type == "FEED_LOST"
            elif isinstance(act, Remind):
                snap = self._open_alerts.get(act.zone_id)
                if snap is not None:
                    snap.last_escalated_at = act.reminded_at
            elif isinstance(act, MarkReraiseChecked):
                lst = self._pending_reraises.get(act.zone_id, [])
                remaining = [r for r in lst if r.id != act.alert_id]
                if remaining:
                    self._pending_reraises[act.zone_id] = remaining
                else:
                    self._pending_reraises.pop(act.zone_id, None)
            elif isinstance(act, SendPush):
                if act.level == "WARNING":
                    z_rt = self._zones.get(act.zone_id)
                    if z_rt is not None:
                        z_rt.last_warning_push_at = now

    def _step_zone(
        self,
        zone_id: int,
        now: datetime,
        *,
        is_new_sample: bool,
        open_alert_override: Any = _UNSET,
    ) -> list[EngineAction]:
        z_rt = self._zones[zone_id]
        now_s = now.timestamp()
        old_level = z_rt.machine.level

        metric, zone_density, zone_count = self._compute_zone_metric(z_rt.config, now)
        warn_t, crit_t = self._thresholds_for(z_rt.config)

        transition: LevelTransition | None = z_rt.machine.step(
            metric,
            now_s,
            warning=warn_t,
            critical=crit_t,
            hysteresis_ratio=self._settings.hysteresis_ratio,
            debounce_s=self._settings.debounce_s,
            clear_s=self._settings.clear_s,
            is_new_sample=is_new_sample,
        )

        metric_changed = (zone_density != z_rt.last_density) or (zone_count != z_rt.last_count)
        z_rt.last_density = zone_density
        z_rt.last_count = zone_count
        if is_new_sample or transition is not None or metric_changed:
            if z_rt.machine.level == "NO_DATA":
                z_rt.live_updated_at = None if z_rt.live_updated_at is None else now
            else:
                z_rt.live_updated_at = now

        open_alert = (
            coerce_open_alert(open_alert_override)
            if open_alert_override is not _UNSET
            else self._open_alerts.get(zone_id)
        )

        alert_actions = evaluate_alert_transition(
            zone_id=zone_id,
            old_level=transition.old_level if transition is not None else old_level,
            current_level=z_rt.machine.level,
            density=zone_density,
            count=zone_count,
            now=now,
            open_alert=open_alert,
            last_warning_push_at=z_rt.last_warning_push_at,
            cooldown_s=self._settings.cooldown_s,
        )

        actions: list[EngineAction] = list(alert_actions)
        if is_new_sample or transition is not None or metric_changed:
            actions.append(
                EmitZoneUpdate(
                    zone_id=zone_id,
                    level=z_rt.machine.level,
                    trend=z_rt.machine.trend(now_s, z_rt.config.mode),
                    density=zone_density,
                    count=zone_count,
                    updated_at=z_rt.live_updated_at,
                )
            )

        if self._auto_commit_alerts:
            self._apply_actions_in_memory(actions, now)
        else:
            for act in actions:
                if isinstance(act, SendPush) and act.level == "WARNING":
                    z_rt.last_warning_push_at = now

        return actions

    def ingest(
        self,
        source_id: int,
        raw_count: float,
        now: datetime,
        *,
        reset: bool = False,
        open_alert: OpenAlertSnapshot | dict[str, Any] | None = _UNSET,
    ) -> list[EngineAction]:
        """Ingest one raw count for *source_id* at *now* and return EngineActions."""
        src = self._sources.get(source_id)
        if src is None:
            raise KeyError(f"Unknown source_id {source_id}")
        if src.config.zone_id not in self._zones:
            raise KeyError(f"Unknown zone_id {src.config.zone_id}")

        now_utc = _ensure_utc(now)
        if reset:
            src.smoother.clear()

        src.last_frame_at = now_utc
        smoothed = src.smoother.push(raw_count)
        src.smoothed_count = smoothed
        src.density = smoothed / max(src.config.coverage_area_m2, 1e-6)

        return self._step_zone(
            src.config.zone_id,
            now_utc,
            is_new_sample=True,
            open_alert_override=open_alert,
        )

    def tick(
        self,
        now: datetime,
        *,
        open_alerts: dict[int, OpenAlertSnapshot | dict[str, Any]] | None = None,
        pending_reraises: dict[int, list[ResolvedReraiseSnapshot | dict[str, Any]]] | None = None,
    ) -> list[EngineAction]:
        """Advance timers, staleness checks, reminders, and reraise checks at *now*."""
        now_utc = _ensure_utc(now)
        all_actions: list[EngineAction] = []

        for zone_id in sorted(self._zones):
            z_rt = self._zones[zone_id]
            oa_override = (
                open_alerts.get(zone_id) if open_alerts is not None else _UNSET
            )
            step_actions = self._step_zone(
                zone_id,
                now_utc,
                is_new_sample=False,
                open_alert_override=oa_override,
            )
            all_actions.extend(step_actions)

            open_alert = (
                coerce_open_alert(oa_override)
                if oa_override is not _UNSET
                else self._open_alerts.get(zone_id)
            )
            reraises = (
                [coerce_resolved_reraise(r) for r in pending_reraises.get(zone_id, [])]
                if pending_reraises is not None
                else list(self._pending_reraises.get(zone_id, []))
            )

            tick_alert_actions = evaluate_tick_alerts(
                zone_id=zone_id,
                zone_level=z_rt.machine.level,
                density=z_rt.last_density,
                count=z_rt.last_count,
                now=now_utc,
                open_alert=open_alert,
                pending_reraises=reraises,
                escalation_s=self._settings.escalation_s,
            )
            if tick_alert_actions:
                all_actions.extend(tick_alert_actions)
                if self._auto_commit_alerts:
                    self._apply_actions_in_memory(tick_alert_actions, now_utc)

        return all_actions
