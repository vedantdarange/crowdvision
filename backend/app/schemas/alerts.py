"""app/schemas/alerts.py — Pydantic v2 schemas for Alert endpoints."""
from __future__ import annotations

from pydantic import BaseModel, Field


class AlertActionNoteRequest(BaseModel):
    note: str | None = Field(default=None, max_length=1000)
