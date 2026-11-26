"""app/models/models.py — SQLAlchemy ORM models for every table in plan §7.

Conventions:
- All timestamps are stored as naive UTC DATETIME; serialised with to_iso_z().
- IDs are integer PKs.
- Enum columns use TEXT with CHECK constraints matching contract §3 exactly.
- Partial unique indexes (SQLite-compatible) are declared inline.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import Base, db

# ---------------------------------------------------------------------------
# Enum value sets (must match contract §3 exactly)
# ---------------------------------------------------------------------------
_ROLES = ("citizen", "police", "admin")
_LEVELS = ("SAFE", "WARNING", "CRITICAL", "NO_DATA")
_ALERT_STATUSES = ("NEW", "ACKNOWLEDGED", "RESPONDING", "RESOLVED", "AUTO_CLEARED")
_ALERT_EVENT_TYPES = (
    "CREATED",
    "ESCALATED",
    "REMINDER",
    "ACKNOWLEDGED",
    "RESPONDING",
    "RESOLVED",
    "AUTO_CLEARED",
    "REOPENED",
    "FEED_LOST",
    "FEED_RESTORED",
    "NOTE",
)
_SOURCE_KINDS = ("WEBCAM", "VIDEO_FILE")
_SOURCE_STATUSES = ("ONLINE", "OFFLINE")
_REPORT_KINDS = ("CROWD", "SOS")
_REPORT_STATUSES = ("PENDING", "VERIFIED", "DISMISSED")
_SOS_TYPES = ("MEDICAL", "CRUSH_RISK", "FIRE", "LOST_CHILD", "OTHER")
_ADVISORY_SEVERITIES = ("INFO", "WARNING", "URGENT")
_METRIC_MODES = ("DENSITY", "COUNT")


def _in_check(col: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"{col} IN ({quoted})"


# ---------------------------------------------------------------------------
# users
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # NOCASE collation so email lookups and uniqueness are case-insensitive
    email: Mapped[str] = mapped_column(
        String(255, collation="NOCASE"), nullable=False, unique=True
    )
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="citizen",
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(_in_check("role", _ROLES), name="ck_users_role"),
    )


# ---------------------------------------------------------------------------
# zones
# ---------------------------------------------------------------------------
class Zone(Base):
    __tablename__ = "zones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # GeoJSON Polygon stored as TEXT
    geometry_json: Mapped[str] = mapped_column(Text, nullable=False)
    centroid_lat: Mapped[float] = mapped_column(Float, nullable=False)
    centroid_lng: Mapped[float] = mapped_column(Float, nullable=False)
    # area_m2 is always the server-computed value
    area_m2: Mapped[float] = mapped_column(Float, nullable=False)
    mode: Mapped[str] = mapped_column(String(10), nullable=False, default="DENSITY")
    warning_density: Mapped[float] = mapped_column(Float, nullable=False, default=3.0)
    critical_density: Mapped[float] = mapped_column(Float, nullable=False, default=4.0)
    warning_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    critical_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    sources: Mapped[list[Source]] = relationship(
        "Source", back_populates="zone", lazy="select"
    )

    __table_args__ = (
        CheckConstraint(_in_check("mode", _METRIC_MODES), name="ck_zones_mode"),
        # Partial unique index: name must be unique among ACTIVE zones.
        # SQLite supports WHERE in CREATE INDEX, which SQLAlchemy handles via
        # the Index(..., sqlite_where=…) form.
        Index(
            "uq_zones_name_active",
            "name",
            unique=True,
            sqlite_where=db.text("is_active = 1"),
        ),
    )


# ---------------------------------------------------------------------------
# sources
# ---------------------------------------------------------------------------
class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    zone_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("zones.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    coverage_area_m2: Mapped[float] = mapped_column(Float, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    zone: Mapped[Zone] = relationship("Zone", back_populates="sources")

    __table_args__ = (
        CheckConstraint(_in_check("kind", _SOURCE_KINDS), name="ck_sources_kind"),
        Index("ix_sources_zone_id", "zone_id"),
    )


# ---------------------------------------------------------------------------
# zone_samples  (time-series; kept 7 days)
# ---------------------------------------------------------------------------
class ZoneSample(Base):
    __tablename__ = "zone_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    zone_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("zones.id", ondelete="CASCADE"), nullable=False
    )
    ts: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    count: Mapped[float | None] = mapped_column(Float, nullable=True)
    density: Mapped[float | None] = mapped_column(Float, nullable=True)
    level: Mapped[str] = mapped_column(String(10), nullable=False)

    __table_args__ = (
        CheckConstraint(_in_check("level", _LEVELS), name="ck_zone_samples_level"),
        Index("ix_zone_samples_zone_ts", "zone_id", "ts"),
    )


# ---------------------------------------------------------------------------
# alerts
# ---------------------------------------------------------------------------
class AlertModel(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    zone_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("zones.id", ondelete="RESTRICT"), nullable=False
    )
    level: Mapped[str] = mapped_column(String(10), nullable=False)
    peak_level: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="NEW")
    condition_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    peak_density: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    peak_count: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    acknowledged_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    responding_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    responding_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    condition_cleared_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_escalated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_push_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # re-raise support (§4.3 / §8.1)
    reraise_check_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    previous_alert_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("alerts.id", ondelete="SET NULL"), nullable=True
    )

    events: Mapped[list[AlertEvent]] = relationship(
        "AlertEvent", back_populates="alert", lazy="select"
    )

    __table_args__ = (
        CheckConstraint(
            _in_check("level", ("WARNING", "CRITICAL")), name="ck_alerts_level"
        ),
        CheckConstraint(
            _in_check("peak_level", ("WARNING", "CRITICAL")), name="ck_alerts_peak_level"
        ),
        CheckConstraint(
            _in_check("status", _ALERT_STATUSES), name="ck_alerts_status"
        ),
        Index("ix_alerts_zone_created", "zone_id", "created_at"),
        Index("ix_alerts_status", "status"),
        # Partial unique index: at most one open alert per zone.
        # "Open" = status IN ('NEW', 'ACKNOWLEDGED', 'RESPONDING').
        Index(
            "uq_alerts_zone_open",
            "zone_id",
            unique=True,
            sqlite_where=db.text(
                "status IN ('NEW', 'ACKNOWLEDGED', 'RESPONDING')"
            ),
        ),
    )


# ---------------------------------------------------------------------------
# alert_events
# ---------------------------------------------------------------------------
class AlertEvent(Base):
    __tablename__ = "alert_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    actor_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Stored as JSON text
    data_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    alert: Mapped[AlertModel] = relationship("AlertModel", back_populates="events")

    __table_args__ = (
        CheckConstraint(
            _in_check("type", _ALERT_EVENT_TYPES), name="ck_alert_events_type"
        ),
        Index("ix_alert_events_alert_created", "alert_id", "created_at"),
    )


# ---------------------------------------------------------------------------
# advisories
# ---------------------------------------------------------------------------
class Advisory(Base):
    __tablename__ = "advisories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    zone_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("zones.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        CheckConstraint(
            _in_check("severity", _ADVISORY_SEVERITIES), name="ck_advisories_severity"
        ),
        Index("ix_advisories_active_created", "is_active", "created_at"),
    )


# ---------------------------------------------------------------------------
# reports
# ---------------------------------------------------------------------------
class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="PENDING")
    zone_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("zones.id", ondelete="SET NULL"), nullable=True
    )
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    count: Mapped[float | None] = mapped_column(Float, nullable=True)
    density_hint: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    sos_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    reviewed_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(_in_check("kind", _REPORT_KINDS), name="ck_reports_kind"),
        CheckConstraint(
            _in_check("status", _REPORT_STATUSES), name="ck_reports_status"
        ),
        CheckConstraint(
            "sos_type IS NULL OR " + _in_check("sos_type", _SOS_TYPES),
            name="ck_reports_sos_type",
        ),
        Index("ix_reports_status_created", "status", "created_at"),
        Index("ix_reports_created_by", "created_by"),
    )


# ---------------------------------------------------------------------------
# push_subscriptions
# ---------------------------------------------------------------------------
class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    endpoint: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    p256dh: Mapped[str] = mapped_column(Text, nullable=False)
    auth: Mapped[str] = mapped_column(String(255), nullable=False)
    user_agent: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


# ---------------------------------------------------------------------------
# audit_logs
# ---------------------------------------------------------------------------
class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    data_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (Index("ix_audit_logs_created", "created_at"),)


# ---------------------------------------------------------------------------
# settings  (key-value store; defaults in code, DB overrides)
# ---------------------------------------------------------------------------
class Settings(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
