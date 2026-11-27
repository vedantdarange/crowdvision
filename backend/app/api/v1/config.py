"""app/api/v1/config.py — Config, Settings, and Help-info endpoints.

Route table (all under /api/v1):
  GET   /config      — public
  GET   /help-info   — public
  GET   /settings    — admin only
  PATCH /settings    — admin only
"""
from __future__ import annotations

from flask import Blueprint

from app.container import get_container
from app.core.auth import current_user, roles_required
from app.core.responses import ok
from app.core.validation import parse_json_body, validate
from app.schemas.config import SettingsPatchRequest

config_bp = Blueprint("config_settings", __name__)


@config_bp.get("/config")
def get_config():
    container = get_container()
    return ok(container.settings_service.get_config())


@config_bp.get("/help-info")
def get_help_info():
    container = get_container()
    return ok(container.settings_service.get_help_info())


@config_bp.get("/settings")
@roles_required("admin")
def get_settings():
    current_user()
    container = get_container()
    return ok(container.settings_service.get_settings())


@config_bp.patch("/settings")
@roles_required("admin")
def update_settings():
    actor = current_user()
    req = validate(SettingsPatchRequest, parse_json_body())
    updates = req.model_dump(exclude_none=True)
    container = get_container()
    return ok(container.settings_service.update_settings(updates, actor))
