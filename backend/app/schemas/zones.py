"""app/schemas/zones.py — Pydantic v2 request schemas for Zones.

Validation rules (contract §6.2):
- geometry: closed GeoJSON Polygon, [lng, lat] coords, >= 3 distinct vertices, shapely-valid.
- 1 <= area_m2 <= 10_000_000 (checked server-side in ZoneService).
- warning < critical (density; counts when provided).
- COUNT mode requires both warning_count and critical_count.
- area_m2 (client hint) validated server-side; mismatch > 10% -> 422.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


def _validate_geometry(geom: Any) -> Any:
    """Validate that geom is a closed GeoJSON Polygon with >= 3 distinct vertices."""
    if not isinstance(geom, dict):
        raise ValueError("geometry must be a GeoJSON object (dict)")
    if geom.get("type") != "Polygon":
        raise ValueError("geometry.type must be 'Polygon'")
    coords = geom.get("coordinates")
    if not isinstance(coords, list) or len(coords) == 0:
        raise ValueError("geometry.coordinates must be a non-empty list of rings")

    coords_outer = coords[0]
    if not isinstance(coords_outer, list) or len(coords_outer) < 4:
        raise ValueError("Polygon outer ring must have at least 4 coordinate pairs (closed)")

    for pt in coords_outer:
        if (
            not isinstance(pt, (list, tuple))
            or len(pt) < 2
            or not isinstance(pt[0], (int, float))
            or not isinstance(pt[1], (int, float))
            or isinstance(pt[0], bool)
            or isinstance(pt[1], bool)
        ):
            raise ValueError("Each coordinate must be a numeric [lng, lat] pair")
        lng, lat = float(pt[0]), float(pt[1])
        if not (-180.0 <= lng <= 180.0 and -90.0 <= lat <= 90.0):
            raise ValueError("Coordinates out of range: lng in [-180, 180], lat in [-90, 90]")

    if coords_outer[0][:2] != coords_outer[-1][:2]:
        raise ValueError("Polygon outer ring must be closed (first == last coordinate)")

    distinct = {(float(c[0]), float(c[1])) for c in coords_outer[:-1]}
    if len(distinct) < 3:
        raise ValueError("Polygon must have at least 3 distinct vertices")

    from shapely.geometry import shape as shapely_shape

    shp = shapely_shape(geom)
    if shp.is_empty or shp.geom_type != "Polygon" or not shp.is_valid or not shp.exterior.is_simple:
        raise ValueError("Polygon geometry is not valid/simple")
    return geom


class ZoneCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="")
    geometry: dict[str, Any]
    mode: Literal["DENSITY", "COUNT"] = "DENSITY"
    warning_density: float | None = Field(default=None, gt=0)
    critical_density: float | None = Field(default=None, gt=0)
    warning_count: int | None = Field(default=None, ge=1)
    critical_count: int | None = Field(default=None, ge=1)
    # Client area hint; server always recomputes
    area_m2: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _validate_all(self) -> "ZoneCreateRequest":
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("name cannot be blank")
        _validate_geometry(self.geometry)
        if self.warning_density is not None and self.critical_density is not None:
            if self.warning_density >= self.critical_density:
                raise ValueError("warning_density must be less than critical_density")
        if self.mode == "COUNT":
            if self.warning_count is None or self.critical_count is None:
                raise ValueError("COUNT mode requires both warning_count and critical_count")
            if self.warning_count >= self.critical_count:
                raise ValueError("warning_count must be less than critical_count")
        elif self.warning_count is not None and self.critical_count is not None:
            if self.warning_count >= self.critical_count:
                raise ValueError("warning_count must be less than critical_count")
        return self


class ZonePatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    geometry: dict[str, Any] | None = None
    mode: Literal["DENSITY", "COUNT"] | None = None
    warning_density: float | None = Field(default=None, gt=0)
    critical_density: float | None = Field(default=None, gt=0)
    warning_count: int | None = Field(default=None, ge=1)
    critical_count: int | None = Field(default=None, ge=1)
    area_m2: float | None = Field(default=None, gt=0)
    is_active: bool | None = None

    @model_validator(mode="after")
    def _validate_patch(self) -> "ZonePatchRequest":
        if self.name is not None:
            self.name = self.name.strip()
            if not self.name:
                raise ValueError("name cannot be blank")
        if self.geometry is not None:
            _validate_geometry(self.geometry)
        if self.warning_density is not None and self.critical_density is not None:
            if self.warning_density >= self.critical_density:
                raise ValueError("warning_density must be less than critical_density")
        if self.warning_count is not None and self.critical_count is not None:
            if self.warning_count >= self.critical_count:
                raise ValueError("warning_count must be less than critical_count")
        return self
