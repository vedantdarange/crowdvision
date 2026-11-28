"""app/container.py — Dependency injection wiring.

Builds repositories, services, pure ZoneEngine, lock, emitter, notifier,
background task state, and DetectionManager, attaching Container to
`flask_app.extensions['container']`.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

from flask import Flask, current_app

from app.config import Settings, settings as default_settings
from app.core.clock import Clock, SystemClock
from app.detection.manager import DetectionManager
from app.engine.zone_engine import ZoneEngine
from app.push.notifier import Notifier, WebPushNotifier
from app.realtime.emitter import RealtimeEmitter
from app.realtime.tasks import BackgroundSchedulerState, SourceStatusTracker
from app.repositories.advisory_repo import AdvisoryRepository
from app.repositories.alert_repo import AlertRepository
from app.repositories.audit_repo import AuditRepository
from app.repositories.push_repo import PushSubscriptionRepository
from app.repositories.report_repo import ReportRepository
from app.repositories.settings_repo import SettingsRepository
from app.repositories.source_repo import SourceRepository
from app.repositories.user_repo import UserRepository
from app.repositories.zone_repo import ZoneRepository
from app.repositories.zone_sample_repo import ZoneSampleRepository
from app.services.advisory_service import AdvisoryService
from app.services.alert_service import AlertService
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService
from app.services.engine_sync import reload_engine_from_db
from app.services.push_service import PushService
from app.services.report_service import ReportService
from app.services.settings_service import SettingsService
from app.services.source_service import SourceService
from app.services.user_service import UserService
from app.services.zone_service import ZoneService


@dataclass(frozen=True)
class Container:
    clock: Clock
    engine_lock: threading.Lock
    user_repo: UserRepository
    audit_repo: AuditRepository
    zone_repo: ZoneRepository
    source_repo: SourceRepository
    settings_repo: SettingsRepository
    alert_repo: AlertRepository
    advisory_repo: AdvisoryRepository
    zone_sample_repo: ZoneSampleRepository
    push_repo: PushSubscriptionRepository
    report_repo: ReportRepository
    audit_service: AuditService
    auth_service: AuthService
    user_service: UserService
    zone_service: ZoneService
    source_service: SourceService
    settings_service: SettingsService
    alert_service: AlertService
    advisory_service: AdvisoryService
    push_service: PushService
    report_service: ReportService
    zone_engine: ZoneEngine
    emitter: RealtimeEmitter
    notifier: Notifier
    source_status_tracker: SourceStatusTracker
    task_state: BackgroundSchedulerState
    detection_manager: DetectionManager
    report_retention_days: int = 30


def wire(flask_app: Flask, *, app_settings: Settings | None = None) -> Container:
    """Instantiate repositories, services, engine, and bind them to *flask_app*."""
    cfg = app_settings or default_settings
    clock = SystemClock()
    engine_lock = threading.Lock()

    user_repo = UserRepository()
    audit_repo = AuditRepository()
    zone_repo = ZoneRepository()
    source_repo = SourceRepository()
    settings_repo = SettingsRepository()
    alert_repo = AlertRepository()
    advisory_repo = AdvisoryRepository()
    zone_sample_repo = ZoneSampleRepository()
    push_repo = PushSubscriptionRepository()
    report_repo = ReportRepository()

    zone_engine = ZoneEngine(auto_commit_alerts=False)
    emitter = RealtimeEmitter(clock=clock)
    notifier = WebPushNotifier(
        push_repo=push_repo,
        zone_repo=zone_repo,
        vapid_private_key=cfg.vapid_private_key,
        vapid_public_key=cfg.vapid_public_key,
        vapid_subject=cfg.vapid_subject,
        clock=clock,
        flask_app=flask_app,
    )
    source_status_tracker = SourceStatusTracker()
    task_state = BackgroundSchedulerState()

    audit_service = AuditService(audit_repo)
    auth_service = AuthService(user_repo)
    user_service = UserService(user_repo, audit_service)
    settings_service = SettingsService(settings_repo, audit_service, app_settings=cfg)
    push_service = PushService(push_repo, notifier, clock=clock)

    def _reload_on_settings_change() -> None:
        with engine_lock:
            reload_engine_from_db(
                zone_engine=zone_engine,
                zone_repo=zone_repo,
                source_repo=source_repo,
                settings_service=settings_service,
            )

    settings_service.set_on_change_callback(_reload_on_settings_change)

    zone_service = ZoneService(
        zone_repo,
        source_repo,
        audit_service,
        settings_service,
        zone_sample_repo=zone_sample_repo,
        zone_engine=zone_engine,
        engine_lock=engine_lock,
        clock=clock,
    )
    source_service = SourceService(
        source_repo,
        zone_repo,
        audit_service,
        settings_service=settings_service,
        zone_engine=zone_engine,
        engine_lock=engine_lock,
        clock=clock,
    )
    alert_service = AlertService(
        alert_repo=alert_repo,
        zone_repo=zone_repo,
        source_repo=source_repo,
        user_repo=user_repo,
        audit_service=audit_service,
        settings_service=settings_service,
        emitter=emitter,
        notifier=notifier,
        clock=clock,
        engine_lock=engine_lock,
        zone_engine=zone_engine,
    )
    advisory_service = AdvisoryService(
        advisory_repo=advisory_repo,
        zone_repo=zone_repo,
        user_repo=user_repo,
        audit_service=audit_service,
        emitter=emitter,
        clock=clock,
    )
    detection_manager = DetectionManager(
        backend=cfg.detector_backend,
        use_tracker=cfg.use_tracker,
        model_path=cfg.model_path,
        zone_engine=zone_engine,
        engine_lock=engine_lock,
        alert_service=alert_service,
        emitter=emitter,
        zone_repo=zone_repo,
        source_repo=source_repo,
        settings_service=settings_service,
        source_status_tracker=source_status_tracker,
        clock=clock,
    )
    report_service = ReportService(
        report_repo=report_repo,
        zone_repo=zone_repo,
        user_repo=user_repo,
        audit_service=audit_service,
        detection_manager=detection_manager,
        emitter=emitter,
        notifier=notifier,
        clock=clock,
    )

    container = Container(
        clock=clock,
        engine_lock=engine_lock,
        user_repo=user_repo,
        audit_repo=audit_repo,
        zone_repo=zone_repo,
        source_repo=source_repo,
        settings_repo=settings_repo,
        alert_repo=alert_repo,
        advisory_repo=advisory_repo,
        zone_sample_repo=zone_sample_repo,
        push_repo=push_repo,
        report_repo=report_repo,
        audit_service=audit_service,
        auth_service=auth_service,
        user_service=user_service,
        zone_service=zone_service,
        source_service=source_service,
        settings_service=settings_service,
        alert_service=alert_service,
        advisory_service=advisory_service,
        push_service=push_service,
        report_service=report_service,
        zone_engine=zone_engine,
        emitter=emitter,
        notifier=notifier,
        source_status_tracker=source_status_tracker,
        task_state=task_state,
        detection_manager=detection_manager,
        report_retention_days=cfg.report_retention_days,
    )
    flask_app.extensions["container"] = container
    return container


def get_container() -> Container:
    """Return the wired Container for the active Flask application."""
    return current_app.extensions["container"]
