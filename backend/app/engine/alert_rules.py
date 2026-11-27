"""app/engine/alert_rules.py — Pure Python alert decision rules (contract §4.3).

State in, plain action dataclasses out. No Flask, SQLAlchemy, sockets, or threading.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Union

_LEVEL_RANK: dict[str, int] = {"WARNING": 1, "CRITICAL": 2}


# ---------------------------------------------------------------------------
# Caller-supplied snapshots (plain data, no ORM imports)
# ---------------------------------------------------------------------------
@dataclass
class OpenAlertSnapshot:
    id: int
    zone_id: int
    status: str  # 'NEW' | 'ACKNOWLEDGED' | 'RESPONDING'
    level: str   # 'WARNING' | 'CRITICAL'
    peak_level: str
    condition_active: bool
    peak_density: float
    peak_count: float
    created_at: datetime
    last_escalated_at: datetime | None = None
    last_push_at: datetime | None = None
    feed_lost_emitted: bool = False


@dataclass
class ResolvedReraiseSnapshot:
    id: int
    zone_id: int
    status: str  # 'RESOLVED'
    resolved_at: datetime
    reraise_check_at: datetime


def coerce_open_alert(raw: OpenAlertSnapshot | dict[str, Any] | None) -> OpenAlertSnapshot | None:
    """Accept either an OpenAlertSnapshot or a plain dict from a repository."""
    if raw is None or isinstance(raw, OpenAlertSnapshot):
        return raw
    return OpenAlertSnapshot(
        id=int(raw["id"]),
        zone_id=int(raw["zone_id"]),
        status=str(raw["status"]),
        level=str(raw["level"]),
        peak_level=str(raw["peak_level"]),
        condition_active=bool(raw["condition_active"]),
        peak_density=float(raw.get("peak_density", 0.0)),
        peak_count=float(raw.get("peak_count", 0.0)),
        created_at=raw["created_at"],
        last_escalated_at=raw.get("last_escalated_at"),
        last_push_at=raw.get("last_push_at"),
        feed_lost_emitted=bool(raw.get("feed_lost_emitted", False)),
    )


def coerce_resolved_reraise(
    raw: ResolvedReraiseSnapshot | dict[str, Any],
) -> ResolvedReraiseSnapshot:
    if isinstance(raw, ResolvedReraiseSnapshot):
        return raw
    return ResolvedReraiseSnapshot(
        id=int(raw["id"]),
        zone_id=int(raw["zone_id"]),
        status=str(raw.get("status", "RESOLVED")),
        resolved_at=raw["resolved_at"],
        reraise_check_at=raw["reraise_check_at"],
    )


# ---------------------------------------------------------------------------
# Engine output actions (plain dataclasses)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CreateAlert:
    zone_id: int
    level: str
    peak_level: str
    peak_density: float
    peak_count: float
    created_at: datetime
    reason: str | None = None
    previous_alert_id: int | None = None


@dataclass(frozen=True)
class ReopenAlert:
    alert_id: int
    zone_id: int
    level: str
    peak_level: str
    peak_density: float
    peak_count: float
    reopened_at: datetime


@dataclass(frozen=True)
class EscalateAlert:
    alert_id: int
    zone_id: int
    new_level: str
    peak_level: str
    peak_density: float
    peak_count: float
    escalated_at: datetime


@dataclass(frozen=True)
class UpdatePeak:
    alert_id: int
    zone_id: int
    peak_density: float
    peak_count: float
    level: str | None = None


@dataclass(frozen=True)
class ClearCondition:
    alert_id: int
    zone_id: int
    cleared_at: datetime


@dataclass(frozen=True)
class AutoClearAlert:
    alert_id: int
    zone_id: int
    cleared_at: datetime


@dataclass(frozen=True)
class RecordFeedEvent:
    alert_id: int
    zone_id: int
    event_type: str  # 'FEED_LOST' | 'FEED_RESTORED'
    occurred_at: datetime


@dataclass(frozen=True)
class Remind:
    alert_id: int
    zone_id: int
    level: str
    peak_density: float
    peak_count: float
    reminded_at: datetime


@dataclass(frozen=True)
class MarkReraiseChecked:
    alert_id: int
    zone_id: int


@dataclass(frozen=True)
class EmitZoneUpdate:
    zone_id: int
    level: str
    trend: str
    density: float | None
    count: float | None
    updated_at: datetime | None


@dataclass(frozen=True)
class SendPush:
    zone_id: int
    alert_id: int | None
    level: str
    reason: str  # 'CREATED' | 'REOPENED' | 'ESCALATED' | 'REMINDER' | 'STILL_ACTIVE_AFTER_RESOLVE'


EngineAction = Union[
    CreateAlert,
    ReopenAlert,
    EscalateAlert,
    UpdatePeak,
    ClearCondition,
    AutoClearAlert,
    RecordFeedEvent,
    Remind,
    MarkReraiseChecked,
    EmitZoneUpdate,
    SendPush,
]


def _cooldown_elapsed(
    last_warning_push_at: datetime | None,
    now: datetime,
    cooldown_s: float,
) -> bool:
    if last_warning_push_at is None:
        return True
    return (now - last_warning_push_at).total_seconds() >= cooldown_s


def evaluate_alert_transition(
    *,
    zone_id: int,
    old_level: str | None,
    current_level: str,
    density: float | None,
    count: float | None,
    now: datetime,
    open_alert: OpenAlertSnapshot | None,
    last_warning_push_at: datetime | None,
    cooldown_s: float,
) -> list[EngineAction]:
    """Compute alert actions for a zone's level transition or metric update."""
    actions: list[EngineAction] = []
    d = float(density) if density is not None else 0.0
    c = float(count) if count is not None else 0.0

    # 1. Entering NO_DATA -> never clears alert; emit FEED_LOST once
    if current_level == "NO_DATA":
        if old_level == "NO_DATA":
            return actions
        if open_alert is not None and not open_alert.feed_lost_emitted:
            actions.append(
                RecordFeedEvent(
                    alert_id=open_alert.id,
                    zone_id=zone_id,
                    event_type="FEED_LOST",
                    occurred_at=now,
                )
            )
        return actions

    # 2. Returning from NO_DATA -> FEED_RESTORED if an open alert exists
    if old_level == "NO_DATA" and open_alert is not None:
        actions.append(
            RecordFeedEvent(
                alert_id=open_alert.id,
                zone_id=zone_id,
                event_type="FEED_RESTORED",
                occurred_at=now,
            )
        )

    # 3. SAFE -> clear condition; auto-clear only if NEW and peak_level == WARNING
    if current_level == "SAFE":
        if open_alert is not None and open_alert.condition_active:
            actions.append(
                ClearCondition(
                    alert_id=open_alert.id,
                    zone_id=zone_id,
                    cleared_at=now,
                )
            )
            if open_alert.status == "NEW" and open_alert.peak_level == "WARNING":
                actions.append(
                    AutoClearAlert(
                        alert_id=open_alert.id,
                        zone_id=zone_id,
                        cleared_at=now,
                    )
                )
        return actions

    # 4. WARNING / CRITICAL
    if open_alert is None:
        # Create only when entering WARNING/CRITICAL (i.e. level changed into WARNING/CRITICAL)
        if old_level is not None and old_level != current_level:
            actions.append(
                CreateAlert(
                    zone_id=zone_id,
                    level=current_level,
                    peak_level=current_level,
                    peak_density=d,
                    peak_count=c,
                    created_at=now,
                )
            )
            if current_level == "CRITICAL" or _cooldown_elapsed(
                last_warning_push_at, now, cooldown_s
            ):
                actions.append(
                    SendPush(
                        zone_id=zone_id,
                        alert_id=None,
                        level=current_level,
                        reason="CREATED",
                    )
                )
        return actions

    # Open alert exists: either reopen (condition_active=False) or update/escalate
    new_peak_d = max(open_alert.peak_density, d)
    new_peak_c = max(open_alert.peak_count, c)
    new_peak_lvl = (
        "CRITICAL"
        if ("CRITICAL" in (open_alert.peak_level, current_level))
        else "WARNING"
    )

    if not open_alert.condition_active:
        actions.append(
            ReopenAlert(
                alert_id=open_alert.id,
                zone_id=zone_id,
                level=current_level,
                peak_level=new_peak_lvl,
                peak_density=new_peak_d,
                peak_count=new_peak_c,
                reopened_at=now,
            )
        )
        if current_level == "CRITICAL" or _cooldown_elapsed(
            last_warning_push_at, now, cooldown_s
        ):
            actions.append(
                SendPush(
                    zone_id=zone_id,
                    alert_id=open_alert.id,
                    level=current_level,
                    reason="REOPENED",
                )
            )
        return actions

    # open_alert.condition_active is True -> no duplicate alert
    if _LEVEL_RANK[current_level] > _LEVEL_RANK[open_alert.level]:
        actions.append(
            EscalateAlert(
                alert_id=open_alert.id,
                zone_id=zone_id,
                new_level=current_level,
                peak_level=new_peak_lvl,
                peak_density=new_peak_d,
                peak_count=new_peak_c,
                escalated_at=now,
            )
        )
        actions.append(
            SendPush(
                zone_id=zone_id,
                alert_id=open_alert.id,
                level=current_level,
                reason="ESCALATED",
            )
        )
    else:
        level_changed = current_level if current_level != open_alert.level else None
        peaks_rose = new_peak_d > open_alert.peak_density or new_peak_c > open_alert.peak_count
        if level_changed is not None or peaks_rose:
            actions.append(
                UpdatePeak(
                    alert_id=open_alert.id,
                    zone_id=zone_id,
                    peak_density=new_peak_d,
                    peak_count=new_peak_c,
                    level=level_changed,
                )
            )
    return actions


def evaluate_tick_alerts(
    *,
    zone_id: int,
    zone_level: str,
    density: float | None,
    count: float | None,
    now: datetime,
    open_alert: OpenAlertSnapshot | None,
    pending_reraises: list[ResolvedReraiseSnapshot],
    escalation_s: float,
) -> list[EngineAction]:
    """Compute time-driven alert actions (CRITICAL reminders + resolve re-raise checks)."""
    actions: list[EngineAction] = []

    # 1. CRITICAL unacknowledged reminders while condition_active=True
    if (
        open_alert is not None
        and open_alert.status == "NEW"
        and open_alert.level == "CRITICAL"
        and open_alert.condition_active
    ):
        ref_dt = (
            max(open_alert.created_at, open_alert.last_escalated_at)
            if open_alert.last_escalated_at is not None
            else open_alert.created_at
        )
        if (now - ref_dt).total_seconds() >= escalation_s:
            actions.append(
                Remind(
                    alert_id=open_alert.id,
                    zone_id=zone_id,
                    level="CRITICAL",
                    peak_density=open_alert.peak_density,
                    peak_count=open_alert.peak_count,
                    reminded_at=now,
                )
            )
            actions.append(
                SendPush(
                    zone_id=zone_id,
                    alert_id=open_alert.id,
                    level="CRITICAL",
                    reason="REMINDER",
                )
            )

    # 2. Re-raise checks for alerts resolved while condition was active
    d = float(density) if density is not None else 0.0
    c = float(count) if count is not None else 0.0

    for resolved in pending_reraises:
        if now < resolved.reraise_check_at:
            continue
        actions.append(MarkReraiseChecked(alert_id=resolved.id, zone_id=zone_id))
        if open_alert is None and zone_level in ("WARNING", "CRITICAL"):
            actions.append(
                CreateAlert(
                    zone_id=zone_id,
                    level=zone_level,
                    peak_level=zone_level,
                    peak_density=d,
                    peak_count=c,
                    created_at=now,
                    reason="STILL_ACTIVE_AFTER_RESOLVE",
                    previous_alert_id=resolved.id,
                )
            )
            actions.append(
                SendPush(
                    zone_id=zone_id,
                    alert_id=None,
                    level="CRITICAL",
                    reason="STILL_ACTIVE_AFTER_RESOLVE",
                )
            )
            # Only create at most one new open alert for this zone
            break

    return actions
