import { area as turfArea } from '@turf/area';
import { centroid as turfCentroid } from '@turf/centroid';
import type { LatLng, PolygonGeometry } from '@contract/types';

export const MIN_ZONE_AREA_M2 = 1;
export const MAX_ZONE_AREA_M2 = 10_000_000;

interface Point2D {
  x: number;
  y: number;
}

const EPS = 1e-12;

function orientation(a: Point2D, b: Point2D, c: Point2D): number {
  const val = (b.y - a.y) * (c.x - b.x) - (b.x - a.x) * (c.y - b.y);
  if (Math.abs(val) <= EPS) return 0;
  return val > 0 ? 1 : 2;
}

function onSegment(a: Point2D, b: Point2D, p: Point2D): boolean {
  return (
    p.x <= Math.max(a.x, b.x) + EPS &&
    p.x >= Math.min(a.x, b.x) - EPS &&
    p.y <= Math.max(a.y, b.y) + EPS &&
    p.y >= Math.min(a.y, b.y) - EPS
  );
}

function segmentsIntersect(
  p1: Point2D,
  q1: Point2D,
  p2: Point2D,
  q2: Point2D,
): boolean {
  const o1 = orientation(p1, q1, p2);
  const o2 = orientation(p1, q1, q2);
  const o3 = orientation(p2, q2, p1);
  const o4 = orientation(p2, q2, q1);

  if (o1 !== o2 && o3 !== o4) return true;
  if (o1 === 0 && onSegment(p1, q1, p2)) return true;
  if (o2 === 0 && onSegment(p1, q1, q2)) return true;
  if (o3 === 0 && onSegment(p2, q2, p1)) return true;
  if (o4 === 0 && onSegment(p2, q2, q1)) return true;
  return false;
}

/**
 * Checks whether a closed ring has any non-adjacent crossing edges or
 * adjacent zero-degree backtracking overlap. Avoids pulling in @turf/kinks
 * (unlisted in plan §4) by using an exact planar segment-intersection test.
 */
export function hasSelfIntersection(ring: number[][]): boolean {
  const edgeCount = ring.length - 1;
  if (edgeCount < 3) return false;

  const edges: Array<{ a: Point2D; b: Point2D }> = [];
  for (let i = 0; i < edgeCount; i += 1) {
    const p = ring[i]!;
    const q = ring[i + 1]!;
    edges.push({
      a: { x: p[0]!, y: p[1]! },
      b: { x: q[0]!, y: q[1]! },
    });
  }

  for (let i = 0; i < edgeCount; i += 1) {
    for (let j = i + 1; j < edgeCount; j += 1) {
      const adjacent = j === i + 1 || (i === 0 && j === edgeCount - 1);
      const e1 = edges[i]!;
      const e2 = edges[j]!;
      if (adjacent) {
        // Adjacent edges share exactly one endpoint; check for colinear backtrack overlap.
        const sharedAtEnd = j === i + 1;
        const other = sharedAtEnd ? e2.b : e2.a;
        const far = sharedAtEnd ? e1.a : e1.b;
        const pivot = sharedAtEnd ? e1.b : e1.a;
        if (
          orientation(far, pivot, other) === 0 &&
          (onSegment(far, pivot, other) || onSegment(pivot, other, far))
        ) {
          return true;
        }
        continue;
      }
      if (segmentsIntersect(e1.a, e1.b, e2.a, e2.b)) {
        return true;
      }
    }
  }
  return false;
}

/** Computes geodesic polygon area in square metres via @turf/area. */
export function computePolygonAreaM2(geometry: PolygonGeometry): number {
  return turfArea({ type: 'Feature', geometry, properties: {} });
}

/** Computes polygon centroid ({ lat, lng }) via @turf/centroid. */
export function computePolygonCentroid(geometry: PolygonGeometry): LatLng {
  const feature = turfCentroid({ type: 'Feature', geometry, properties: {} });
  const [lng, lat] = feature.geometry.coordinates;
  return {
    lat: lat ?? 0,
    lng: lng ?? 0,
  };
}

/** Validates a closed GeoJSON Polygon against backend and contract rules. */
export function validateZonePolygon(
  geometry: PolygonGeometry | null | undefined,
): string | null {
  if (!geometry || geometry.type !== 'Polygon') {
    return 'Draw a zone polygon on the map.';
  }
  const outer = geometry.coordinates?.[0];
  if (!Array.isArray(outer) || outer.length < 4) {
    return 'Polygon must have at least 3 distinct vertices and be closed.';
  }

  for (const pt of outer) {
    if (
      !Array.isArray(pt) ||
      pt.length < 2 ||
      typeof pt[0] !== 'number' ||
      typeof pt[1] !== 'number' ||
      !Number.isFinite(pt[0]) ||
      !Number.isFinite(pt[1]) ||
      pt[0] < -180 ||
      pt[0] > 180 ||
      pt[1] < -90 ||
      pt[1] > 90
    ) {
      return 'Polygon contains coordinates outside valid latitude/longitude bounds.';
    }
  }

  const first = outer[0]!;
  const last = outer[outer.length - 1]!;
  if (
    Math.abs(first[0]! - last[0]!) > 1e-9 ||
    Math.abs(first[1]! - last[1]!) > 1e-9
  ) {
    return 'Polygon ring must be closed (first vertex matches last vertex).';
  }

  const distinct = new Set(
    outer
      .slice(0, -1)
      .map(([lng, lat]) => `${lng!.toFixed(7)},${lat!.toFixed(7)}`),
  );
  if (distinct.size < 3) {
    return 'Polygon must have at least 3 distinct vertices.';
  }

  if (hasSelfIntersection(outer)) {
    return 'Polygon edges cannot cross or self-intersect.';
  }

  const area = computePolygonAreaM2(geometry);
  if (
    !Number.isFinite(area) ||
    area < MIN_ZONE_AREA_M2 ||
    area > MAX_ZONE_AREA_M2
  ) {
    return 'Zone area must be between 1 m² and 10,000,000 m².';
  }

  return null;
}

/** Ensures polygon outer ring is strictly closed by repeating first vertex if needed. */
export function normalizePolygonGeometry(
  geometry: PolygonGeometry,
): PolygonGeometry {
  const outer = geometry.coordinates[0] ?? [];
  if (outer.length === 0) return geometry;
  const first = outer[0]!;
  const last = outer[outer.length - 1]!;
  const closed =
    first[0] === last[0] && first[1] === last[1]
      ? outer
      : [...outer, [first[0]!, first[1]!]];
  return {
    type: 'Polygon',
    coordinates: [closed, ...geometry.coordinates.slice(1)],
  };
}
