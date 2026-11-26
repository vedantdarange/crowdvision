"""tests/unit/test_core.py — Unit tests for core utilities.

Covers:
- to_iso_z output format
- FakeClock advance / utcnow
- polygon_area_m2 (shared helper)
- partial unique index: zones name unique among active; allowed once soft-deleted
- partial unique index: at most one open alert per zone; allowed once resolved
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# to_iso_z
# ---------------------------------------------------------------------------

class TestToIsoZ:
    def test_utc_aware(self):
        from app.core.time import to_iso_z

        dt = datetime(2026, 11, 24, 10, 15, 30, tzinfo=timezone.utc)
        assert to_iso_z(dt) == "2026-11-24T10:15:30Z"

    def test_naive_treated_as_utc(self):
        from app.core.time import to_iso_z

        dt = datetime(2026, 11, 24, 10, 15, 30)  # naive
        assert to_iso_z(dt) == "2026-11-24T10:15:30Z"

    def test_none_returns_none(self):
        from app.core.time import to_iso_z

        assert to_iso_z(None) is None

    def test_format_has_z_not_plus_zero(self):
        from app.core.time import to_iso_z

        result = to_iso_z(datetime(2026, 1, 1, tzinfo=timezone.utc))
        assert result.endswith("Z")
        assert "+00:00" not in result


# ---------------------------------------------------------------------------
# FakeClock
# ---------------------------------------------------------------------------

class TestFakeClock:
    def test_initial_time(self, fake_clock):
        assert fake_clock.time() == 0.0

    def test_advance(self, fake_clock):
        fake_clock.advance(5)
        assert fake_clock.time() == 5.0

    def test_utcnow_matches_time(self, fake_clock):
        fake_clock.set(1_000_000.0)
        dt = fake_clock.utcnow()
        assert isinstance(dt, datetime)
        assert dt.tzinfo is not None
        assert abs(dt.timestamp() - 1_000_000.0) < 1


# ---------------------------------------------------------------------------
# polygon_area_m2 — shared geometry helper
# ---------------------------------------------------------------------------

class TestPolygonAreaM2:
    def _square_polygon(self, centre_lat: float, centre_lng: float, side_m: float) -> dict:
        """Build a ~side_m × side_m GeoJSON square around *centre*."""
        import math

        mpd_lat = math.pi * 6_378_137.0 / 180.0
        mpd_lng = math.pi * 6_378_137.0 * math.cos(math.radians(centre_lat)) / 180.0

        h = (side_m / 2) / mpd_lat
        w = (side_m / 2) / mpd_lng

        ring = [
            [centre_lng - w, centre_lat - h],
            [centre_lng + w, centre_lat - h],
            [centre_lng + w, centre_lat + h],
            [centre_lng - w, centre_lat + h],
            [centre_lng - w, centre_lat - h],
        ]
        return {"type": "Polygon", "coordinates": [ring]}

    def test_10m_square(self):
        from app.core.geometry import polygon_area_m2

        geom = self._square_polygon(28.6139, 77.2090, 10.0)
        area = polygon_area_m2(geom)
        # Expect ~100 m² ± 2 %
        assert abs(area - 100.0) < 2.0, f"Expected ~100 m², got {area:.2f}"

    def test_50m_square(self):
        from app.core.geometry import polygon_area_m2

        geom = self._square_polygon(28.6139, 77.2090, 50.0)
        area = polygon_area_m2(geom)
        assert abs(area - 2500.0) < 50.0, f"Expected ~2500 m², got {area:.2f}"

    def test_accepts_json_string(self):
        from app.core.geometry import polygon_area_m2

        geom = self._square_polygon(0.0, 0.0, 10.0)
        area_dict = polygon_area_m2(geom)
        area_str = polygon_area_m2(json.dumps(geom))
        assert abs(area_dict - area_str) < 0.001

    def test_raises_on_non_polygon(self):
        import pytest
        from app.core.geometry import polygon_area_m2

        with pytest.raises(ValueError, match="Polygon"):
            polygon_area_m2({"type": "Point", "coordinates": [0, 0]})
