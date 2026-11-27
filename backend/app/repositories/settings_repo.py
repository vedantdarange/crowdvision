"""app/repositories/settings_repo.py — Data-access layer for Settings (key-value store)."""
from __future__ import annotations

import json
from typing import Any

from app.extensions import db
from app.models.models import Settings


class SettingsRepository:
    def get(self, key: str) -> Any | None:
        """Return the parsed value for *key*, or None if not in DB."""
        row = db.session.get(Settings, key)
        if row is None:
            return None
        try:
            return json.loads(row.value_json)
        except (json.JSONDecodeError, TypeError):
            return None

    def get_all(self) -> dict[str, Any]:
        """Return all settings as a parsed dict."""
        rows = db.session.query(Settings).all()
        result: dict[str, Any] = {}
        for row in rows:
            try:
                result[row.key] = json.loads(row.value_json)
            except (json.JSONDecodeError, TypeError):
                result[row.key] = None
        return result

    def set_many(self, updates: dict[str, Any]) -> None:
        """Upsert multiple settings and flush within the active transaction."""
        for key, value in updates.items():
            row = db.session.get(Settings, key)
            if row is None:
                row = Settings(key=key, value_json=json.dumps(value))  # pyrefly: ignore[unexpected-keyword]
                db.session.add(row)
            else:
                row.value_json = json.dumps(value)
        db.session.flush()
