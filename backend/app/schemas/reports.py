"""app/schemas/reports.py — Pydantic v2 request schemas for Citizen Reports (B7)."""
from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _check_finite_range(val: float, lo: float, hi: float, name: str) -> float:
    if not math.isfinite(val) or val < lo or val > hi:
        raise ValueError(f"{name} must be between {lo} and {hi}.")
    return float(val)


class CrowdReportFormSchema(BaseModel):
    model_config = ConfigDict(extra="ignore")

    lat: float
    lng: float
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("lat")
    @classmethod
    def _val_lat(cls, v: float) -> float:
        return _check_finite_range(v, -90.0, 90.0, "lat")

    @field_validator("lng")
    @classmethod
    def _val_lng(cls, v: float) -> float:
        return _check_finite_range(v, -180.0, 180.0, "lng")

    @field_validator("note")
    @classmethod
    def _clean_note(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip()
        return s or None


class SosReportCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sos_type: Literal["MEDICAL", "CRUSH_RISK", "FIRE", "LOST_CHILD", "OTHER"]
    lat: float
    lng: float
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("lat")
    @classmethod
    def _val_lat(cls, v: float) -> float:
        return _check_finite_range(v, -90.0, 90.0, "lat")

    @field_validator("lng")
    @classmethod
    def _val_lng(cls, v: float) -> float:
        return _check_finite_range(v, -180.0, 180.0, "lng")

    @field_validator("note")
    @classmethod
    def _clean_note(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip()
        return s or None


class ReportReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["VERIFIED", "DISMISSED"]
    review_note: str | None = Field(default=None, max_length=1000)

    @field_validator("review_note")
    @classmethod
    def _clean_note(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip()
        return s or None
