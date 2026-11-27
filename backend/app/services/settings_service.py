"""app/services/settings_service.py — Business logic for settings, config, help-info.

Settings are stored as key-value rows in the settings table (JSON text values).
Code defaults match cli._DEFAULT_SETTINGS and contract §4.2 / §5; DB overrides win.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import settings as app_config
from app.core.errors import ValidationAppError
from app.extensions import db
from app.models.models import User
from app.repositories.settings_repo import SettingsRepository
from app.services.audit_service import AuditService

# ---------------------------------------------------------------------------
# Code-level defaults (used when no DB override exists; matches cli.py & §5)
# ---------------------------------------------------------------------------
_DEFAULTS: dict[str, Any] = {
    "detect_conf": 0.35,
    "smoothing_window": 5,
    "debounce_s": 3,
    "clear_s": 8,
    "hysteresis_ratio": 0.85,
    "cooldown_s": 60,
    "escalation_s": 60,
    "stale_after_s": 10,
    "reraise_after_s": 60,
    "target_fps": 3,
    "frame_width": 640,
    "jpeg_quality": 0.7,
    "default_warning_density": 3.0,
    "default_critical_density": 4.0,
    "help_info": {
        "emergency_numbers": [
            {"label": "Emergency (Unified)", "number": "112"},
            {"label": "Police", "number": "100"},
            {"label": "Ambulance", "number": "102"},
            {"label": "Fire", "number": "101"},
        ],
        "medical_points": [],
        "exits": [],
    },
}

# Allowed numeric ranges for validation (min, max)
_RANGES: dict[str, tuple[float, float]] = {
    "detect_conf": (0.1, 0.9),
    "smoothing_window": (1, 15),
    "debounce_s": (0, 30),
    "clear_s": (0, 60),
    "reraise_after_s": (10, 600),
    "cooldown_s": (0, 600),
    "escalation_s": (10, 600),
    "hysteresis_ratio": (0.5, 0.99),
    "stale_after_s": (3, 60),
    "target_fps": (1, 10),
    "frame_width": (320, 1280),
    "jpeg_quality": (0.3, 0.95),
    "default_warning_density": (0.1, 10.0),
    "default_critical_density": (0.1, 10.0),
}


def load_contract_version() -> str:
    """Read CONTRACT_VERSION from <repo>/contract/CONTRACT_VERSION if it exists."""
    # File is <repo>/backend/app/services/settings_service.py -> parents[3] == <repo>
    candidate = Path(__file__).resolve().parents[3] / "contract" / "CONTRACT_VERSION"
    if candidate.exists():
        return candidate.read_text(encoding="utf-8").strip() or "1.1.0"
    return "1.1.0"


CONTRACT_VERSION = load_contract_version()


class SettingsService:
    def __init__(self, settings_repo: SettingsRepository, audit_service: AuditService) -> None:
        self._repo = settings_repo
        self._audit = audit_service
        self._on_change: Any = None

    def set_on_change_callback(self, callback: Any) -> None:
        """Register an optional hook invoked after settings are committed (e.g. engine reload)."""
        self._on_change = callback

    def get_settings(self) -> dict[str, Any]:
        """Return merged Settings dict per contract §5 (code defaults + DB overrides)."""
        db_vals = self._repo.get_all()
        result: dict[str, Any] = {}
        for key, default in _DEFAULTS.items():
            result[key] = db_vals.get(key, default)
        return result

    def update_settings(self, updates: dict[str, Any], actor: User) -> dict[str, Any]:
        """Validate and upsert multiple settings. Returns full Settings dict."""
        current = self.get_settings()
        errors: dict[str, list[str]] = {}
        validated: dict[str, Any] = {}

        for key, value in updates.items():
            if key not in _DEFAULTS:
                errors.setdefault(key, []).append(f"Unknown setting: '{key}'")
                continue
            if key in _RANGES:
                lo, hi = _RANGES[key]
                if not (lo <= float(value) <= hi):
                    errors.setdefault(key, []).append(
                        f"Value {value} out of range [{lo}, {hi}]"
                    )
                    continue
            validated[key] = value

        # Cross-field check: default_warning_density < default_critical_density
        merged_warn = float(validated.get("default_warning_density", current["default_warning_density"]))
        merged_crit = float(validated.get("default_critical_density", current["default_critical_density"]))
        if merged_warn >= merged_crit:
            errors.setdefault("default_warning_density", []).append(
                "default_warning_density must be less than default_critical_density"
            )

        if errors:
            raise ValidationAppError("Settings validation failed.", details=errors)

        if validated:
            self._repo.set_many(validated)
            self._audit.log(actor, "SETTINGS_UPDATED", "settings", None, validated)
            db.session.commit()
            if self._on_change is not None:
                self._on_change()
        return self.get_settings()

    def get_config(self) -> dict[str, Any]:
        """Return public RuntimeConfig per contract §5."""
        all_settings = self.get_settings()
        return {
            "target_fps": int(all_settings["target_fps"]),
            "frame_width": int(all_settings["frame_width"]),
            "jpeg_quality": float(all_settings["jpeg_quality"]),
            "stale_after_s": float(all_settings["stale_after_s"]),
            "vapid_public_key": None,  # B6 will fill VAPID key
            "app_version": app_config.app_version,
            "contract_version": CONTRACT_VERSION,
        }

    def get_help_info(self) -> dict[str, Any]:
        """Return public HelpInfo per contract §5."""
        db_val = self._repo.get("help_info")
        if isinstance(db_val, dict):
            return db_val
        default = _DEFAULTS["help_info"]
        assert isinstance(default, dict)
        return default

    def get_defaults(self) -> tuple[float, float]:
        """Return (default_warning_density, default_critical_density) from settings."""
        all_settings = self.get_settings()
        return (
            float(all_settings.get("default_warning_density", 3.0)),
            float(all_settings.get("default_critical_density", 4.0)),
        )
