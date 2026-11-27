"""app/schemas/advisories.py — Pydantic v2 schemas for Advisory endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class AdvisoryCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    body: str = Field(..., min_length=1, max_length=4000)
    severity: Literal["INFO", "WARNING", "URGENT"]
    zone_id: int | None = Field(default=None, ge=1)
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def _strip_strings(self) -> "AdvisoryCreateRequest":
        self.title = self.title.strip()
        self.body = self.body.strip()
        if not self.title:
            raise ValueError("title cannot be blank")
        if not self.body:
            raise ValueError("body cannot be blank")
        return self
