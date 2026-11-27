"""app/schemas/sources.py — Pydantic v2 request schemas for Sources (contract §6.2)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class SourceCreateRequest(BaseModel):
    zone_id: int = Field(..., ge=1)
    name: str = Field(..., min_length=1, max_length=255)
    kind: Literal["WEBCAM", "VIDEO_FILE"]
    # Only admin may send this; police gets 403 (enforced in service layer)
    coverage_area_m2: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _strip_name(self) -> "SourceCreateRequest":
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("name cannot be blank")
        return self


class SourcePatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    coverage_area_m2: float | None = Field(default=None, gt=0)
    is_active: bool | None = None

    @model_validator(mode="after")
    def _strip_name(self) -> "SourcePatchRequest":
        if self.name is not None:
            self.name = self.name.strip()
            if not self.name:
                raise ValueError("name cannot be blank")
        return self
