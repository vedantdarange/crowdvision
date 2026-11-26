"""app/core/time.py — UTC datetime utilities.

All timestamps are stored and transmitted in UTC.
Serialise with to_iso_z() to get the contract format: "2026-11-24T10:15:30Z".
"""
from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(timezone.utc)


def to_iso_z(dt: datetime | None) -> str | None:
    """Format a datetime as an ISO-8601 UTC string with a trailing 'Z'.

    Returns None when *dt* is None so callers can pass nullable timestamps
    straight through without wrapping in an if.

    The contract requires 'Z' (not '+00:00').
    """
    if dt is None:
        return None
    # Make sure we always emit UTC.
    if dt.tzinfo is None:
        # Assume naive datetimes are already UTC (from the DB).
        dt = dt.replace(tzinfo=timezone.utc)
    utc = dt.astimezone(timezone.utc)
    # isoformat() gives "+00:00"; replace with "Z".
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")
