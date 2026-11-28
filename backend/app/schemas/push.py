"""app/schemas/push.py — Pydantic v2 schemas for Web Push subscriptions."""
from __future__ import annotations

from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PushKeysSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    p256dh: str = Field(min_length=1, max_length=512)
    auth: str = Field(min_length=1, max_length=256)

    @field_validator("p256dh", "auth")
    @classmethod
    def _strip_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Key value must not be blank.")
        return stripped


class PushSubscribeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoint: str = Field(min_length=1, max_length=2048)
    keys: PushKeysSchema

    @field_validator("endpoint")
    @classmethod
    def _validate_endpoint_url(cls, value: str) -> str:
        stripped = value.strip()
        parsed = urlparse(stripped)
        if parsed.scheme not in ("https", "http") or not parsed.netloc:
            raise ValueError("Endpoint must be a valid http(s) push URL.")
        return stripped
