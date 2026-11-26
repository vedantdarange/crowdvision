"""app/models/__init__.py — Import all models so Flask-Migrate can see them."""
from app.models.models import (  # noqa: F401
    AlertEvent,
    AlertModel,
    Advisory,
    AuditLog,
    PushSubscription,
    Report,
    Settings,
    Source,
    User,
    Zone,
    ZoneSample,
)
