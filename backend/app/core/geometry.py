"""app/core/geometry.py — Shared polygon area helper.

This is THE single implementation used by:
  - flask seed-demo (to compute zone areas when creating seed zones), and
  - ZoneService (B2) to recompute and validate the client-supplied area_m2.

Algorithm: local equirectangular projection.
  lat/lng → metres using metres-per-degree at the polygon's latitude.
  Then apply the shoelace formula on the projected ring.

No extra dependencies beyond the standard library.
"""
from __future__ import annotations

import json
import math


def _metres_per_degree(lat_deg: float) -> tuple[float, float]:
    """Return (metres_per_degree_lat, metres_per_degree_lng) at *lat_deg*."""
    lat_rad = math.radians(lat_deg)
    # WGS-84 semi-major axis
    R = 6_378_137.0
    mpd_lat = math.pi * R / 180.0
    mpd_lng = math.pi * R * math.cos(lat_rad) / 180.0
    return mpd_lat, mpd_lng


def polygon_area_m2(geometry_json: str | dict) -> float:
    """Compute the area of a GeoJSON Polygon in square metres.

    Uses a local equirectangular projection (metres per degree at the
    polygon centroid latitude) followed by the shoelace formula on the
    outer ring.  Accurate to <1 % for zones up to a few km across.

    Args:
        geometry_json: a GeoJSON Polygon as a JSON string or a dict.

    Returns:
        Area in m² (always positive).

    Raises:
        ValueError: if the geometry is not a valid Polygon.
    """
    if isinstance(geometry_json, str):
        geom = json.loads(geometry_json)
    else:
        geom = geometry_json

    if geom.get("type") != "Polygon":
        raise ValueError(f"Expected GeoJSON Polygon, got {geom.get('type')!r}")

    coords: list[list[float]] = geom["coordinates"][0]  # outer ring
    if len(coords) < 4:
        raise ValueError("Polygon outer ring must have at least 4 coordinate pairs (closed)")

    # Compute centroid latitude for projection
    lats = [c[1] for c in coords]
    centre_lat = sum(lats) / len(lats)
    mpd_lat, mpd_lng = _metres_per_degree(centre_lat)

    # Project to metres
    pts = [(c[0] * mpd_lng, c[1] * mpd_lat) for c in coords]

    # Shoelace formula
    n = len(pts)
    area = 0.0
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        area += x0 * y1 - x1 * y0
    return abs(area) / 2.0


def polygon_centroid(geometry_json: str | dict) -> tuple[float, float]:
    """Return (lat, lng) centroid of a GeoJSON Polygon outer ring.

    Simple average of vertices (not weighted by edge length) which is
    good enough for a small zone polygon.
    """
    if isinstance(geometry_json, str):
        geom = json.loads(geometry_json)
    else:
        geom = geometry_json

    coords: list[list[float]] = geom["coordinates"][0]
    lngs = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    return sum(lats) / len(lats), sum(lngs) / len(lngs)
