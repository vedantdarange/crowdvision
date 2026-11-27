"""app/schemas/config.py — Pydantic v2 request schemas for Settings PATCH.

Allowed ranges (chosen to match contract §5 / §6.2 and B2 spec):
  detect_conf:              0.1 – 0.9
  smoothing_window:         1   – 15
  debounce_s:               0   – 30
  clear_s:                  0   – 60
  reraise_after_s:          10  – 600
  cooldown_s:               0   – 600
  escalation_s:             10  – 600
  hysteresis_ratio:         0.5 – 0.99
  stale_after_s:            3   – 60
  target_fps:               1   – 10
  frame_width:              320 – 1280
  jpeg_quality:             0.3 – 0.95
  default_warning_density:  0.1 – 10.0
  default_critical_density: 0.1 – 10.0
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class EmergencyNumberSchema(BaseModel):
    label: str = Field(..., min_length=1, max_length=100)
    number: str = Field(..., min_length=1, max_length=50)


class PointNoteSchema(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    lat: float | None = Field(default=None, ge=-90.0, le=90.0)
    lng: float | None = Field(default=None, ge=-180.0, le=180.0)
    note: str | None = Field(default=None, max_length=500)


class HelpInfoSchema(BaseModel):
    emergency_numbers: list[EmergencyNumberSchema]
    medical_points: list[PointNoteSchema] = Field(default_factory=list)
    exits: list[PointNoteSchema] = Field(default_factory=list)


class SettingsPatchRequest(BaseModel):
    detect_conf: float | None = Field(default=None, ge=0.1, le=0.9)
    smoothing_window: int | None = Field(default=None, ge=1, le=15)
    debounce_s: float | None = Field(default=None, ge=0, le=30)
    clear_s: float | None = Field(default=None, ge=0, le=60)
    reraise_after_s: float | None = Field(default=None, ge=10, le=600)
    cooldown_s: float | None = Field(default=None, ge=0, le=600)
    escalation_s: float | None = Field(default=None, ge=10, le=600)
    hysteresis_ratio: float | None = Field(default=None, ge=0.5, le=0.99)
    stale_after_s: float | None = Field(default=None, ge=3, le=60)
    target_fps: int | None = Field(default=None, ge=1, le=10)
    frame_width: int | None = Field(default=None, ge=320, le=1280)
    jpeg_quality: float | None = Field(default=None, ge=0.3, le=0.95)
    default_warning_density: float | None = Field(default=None, ge=0.1, le=10.0)
    default_critical_density: float | None = Field(default=None, ge=0.1, le=10.0)
    help_info: HelpInfoSchema | None = None
