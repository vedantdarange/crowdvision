import { describe, expect, it } from 'vitest';
import type { PolygonGeometry } from '@contract/types';
import {
  computePolygonAreaM2,
  computePolygonCentroid,
  hasSelfIntersection,
  normalizePolygonGeometry,
  validateZonePolygon,
} from '@/lib/geo';

describe('geo helpers (area, centroid, polygon validation)', () => {
  it('computes area within 1% of hand-calculated 100 m x 50 m rectangle and accurate centroid', () => {
    const baseLat = 18.5195;
    const baseLng = 73.85;
    const earthRadius = 6378137;
    const mpdLat = (Math.PI * earthRadius) / 180;
    const mpdLng = mpdLat * Math.cos((baseLat * Math.PI) / 180);

    const dLat = 50 / mpdLat;
    const dLng = 100 / mpdLng;

    const rectangle: PolygonGeometry = {
      type: 'Polygon',
      coordinates: [
        [
          [baseLng, baseLat],
          [baseLng + dLng, baseLat],
          [baseLng + dLng, baseLat + dLat],
          [baseLng, baseLat + dLat],
          [baseLng, baseLat],
        ],
      ],
    };

    const computedArea = computePolygonAreaM2(rectangle);
    const expectedArea = 5000;
    expect(Math.abs(computedArea - expectedArea) / expectedArea).toBeLessThan(
      0.01,
    );

    const centroid = computePolygonCentroid(rectangle);
    expect(centroid.lat).toBeCloseTo(baseLat + dLat / 2, 6);
    expect(centroid.lng).toBeCloseTo(baseLng + dLng / 2, 6);
    expect(validateZonePolygon(rectangle)).toBeNull();
  });

  it('rejects polygons with < 3 distinct vertices, unclosed rings, or area out of bounds', () => {
    expect(validateZonePolygon(null)).toMatch(/Draw a zone polygon/i);

    expect(
      validateZonePolygon({
        type: 'Polygon',
        coordinates: [
          [
            [73.85, 18.51],
            [73.851, 18.51],
            [73.85, 18.51],
          ],
        ],
      }),
    ).toMatch(/at least 3 distinct vertices/i);

    expect(
      validateZonePolygon({
        type: 'Polygon',
        coordinates: [
          [
            [73.85, 18.51],
            [73.851, 18.51],
            [73.851, 18.511],
            [73.85, 18.512],
          ],
        ],
      }),
    ).toMatch(/closed/i);

    // Duplicate vertices forming degenerate triangle
    expect(
      validateZonePolygon({
        type: 'Polygon',
        coordinates: [
          [
            [73.85, 18.51],
            [73.851, 18.51],
            [73.85, 18.51],
            [73.85, 18.51],
          ],
        ],
      }),
    ).toMatch(/3 distinct vertices/i);

    // Tiny sub-1 m² polygon
    expect(
      validateZonePolygon({
        type: 'Polygon',
        coordinates: [
          [
            [73.85, 18.51],
            [73.850001, 18.51],
            [73.850001, 18.510001],
            [73.85, 18.51],
          ],
        ],
      }),
    ).toMatch(/1 m² and 10,000,000 m²/i);
  });

  it('detects self-intersecting bow-tie polygons cleanly', () => {
    const bowtie: PolygonGeometry = {
      type: 'Polygon',
      coordinates: [
        [
          [73.85, 18.51],
          [73.851, 18.511],
          [73.851, 18.51],
          [73.85, 18.511],
          [73.85, 18.51],
        ],
      ],
    };
    expect(hasSelfIntersection(bowtie.coordinates[0]!)).toBe(true);
    expect(validateZonePolygon(bowtie)).toMatch(/self-intersect/i);
  });

  it('normalizes an unclosed ring by appending the starting coordinate', () => {
    const normalized = normalizePolygonGeometry({
      type: 'Polygon',
      coordinates: [
        [
          [73.85, 18.51],
          [73.851, 18.51],
          [73.851, 18.511],
        ],
      ],
    });
    expect(normalized.coordinates[0]).toHaveLength(4);
    expect(normalized.coordinates[0]?.[3]).toEqual([73.85, 18.51]);
  });
});
