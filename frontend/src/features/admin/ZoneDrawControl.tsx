import { useEffect, useRef } from 'react';
import { useMap } from '@vis.gl/react-maplibre';
import { MaplibreTerradrawControl } from '@watergis/maplibre-gl-terradraw';
import '@watergis/maplibre-gl-terradraw/dist/maplibre-gl-terradraw.css';
import type { GeoJSONStoreFeatures, TerraDrawExtend } from 'terra-draw';
import type { PolygonGeometry } from '@contract/types';
import { normalizePolygonGeometry } from '@/lib/geo';

export interface ZoneDrawControlProps {
  initialPolygon?: PolygonGeometry | null;
  onChange: (polygon: PolygonGeometry | null) => void;
  position?: 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right';
}

function userPolygons(
  features: GeoJSONStoreFeatures[],
): GeoJSONStoreFeatures[] {
  return features.filter(
    (feature) =>
      feature.geometry.type === 'Polygon' &&
      feature.properties?.currentlyDrawing !== true &&
      feature.properties?.selectionPoint !== true &&
      feature.properties?.midPoint !== true &&
      feature.properties?.closingPoint !== true &&
      feature.properties?.coordinatePoint !== true &&
      feature.properties?.snappingPoint !== true,
  );
}

function toPolygonGeometry(
  feature: GeoJSONStoreFeatures,
): PolygonGeometry | null {
  if (feature.geometry.type !== 'Polygon') return null;
  return normalizePolygonGeometry({
    type: 'Polygon',
    coordinates: feature.geometry.coordinates.map((ring) =>
      ring.map(([lng = 0, lat = 0]) => [lng, lat]),
    ),
  });
}

/** Isolates Terra Draw inside MapLibre, allowing one editable zone polygon. */
export function ZoneDrawControl({
  initialPolygon = null,
  onChange,
  position = 'top-right',
}: ZoneDrawControlProps) {
  const { current: mapRef } = useMap();
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  const initialPolygonRef = useRef<PolygonGeometry | null>(initialPolygon);
  initialPolygonRef.current = initialPolygon;

  useEffect(() => {
    const map = mapRef?.getMap();
    if (!map) return;

    const control = new MaplibreTerradrawControl({
      modes: ['polygon', 'select', 'delete'],
      open: true,
      showDeleteConfirmation: false,
    });

    let active = true;
    let attachedListeners = false;
    let tdInstance: ReturnType<
      MaplibreTerradrawControl['getTerraDrawInstance']
    >;

    const handleFinish = (finishedId: TerraDrawExtend.FeatureId) => {
      if (!active || !tdInstance) return;
      const polygons = userPolygons(tdInstance.getSnapshot());
      if (polygons.length === 0) {
        onChangeRef.current(null);
        return;
      }
      const keep =
        polygons.find((f) => f.id === finishedId) ??
        polygons[polygons.length - 1]!;
      const staleIds = polygons
        .filter((f) => f.id !== keep.id && f.id !== undefined)
        .map((f) => f.id!);
      if (staleIds.length > 0) {
        tdInstance.removeFeatures(staleIds);
      }
      tdInstance.setMode('select');
      onChangeRef.current(toPolygonGeometry(keep));
    };

    const handleChange = (_ids: TerraDrawExtend.FeatureId[], type: string) => {
      if (!active || !tdInstance) return;
      const polygons = userPolygons(tdInstance.getSnapshot());
      if (type === 'delete') {
        if (polygons.length === 0) {
          onChangeRef.current(null);
        } else if (polygons.length === 1) {
          onChangeRef.current(toPolygonGeometry(polygons[0]!));
        }
        return;
      }
      if (type === 'update' && polygons.length === 1) {
        onChangeRef.current(toPolygonGeometry(polygons[0]!));
      }
    };

    const handleFeatureDeleted = () => {
      if (!active || !tdInstance) return;
      const polygons = userPolygons(tdInstance.getSnapshot());
      onChangeRef.current(polygons[0] ? toPolygonGeometry(polygons[0]) : null);
    };

    const handleReady = () => {
      if (!active || !tdInstance) return;
      const seed = initialPolygonRef.current;
      if (!seed) return;
      if (userPolygons(tdInstance.getSnapshot()).length > 0) return;

      const featureId = tdInstance.getFeatureId();
      tdInstance.addFeatures([
        {
          id: featureId,
          type: 'Feature',
          geometry: seed,
          properties: { mode: 'polygon' },
        },
      ]);
      tdInstance.setMode('select');
    };

    const attach = () => {
      if (!active) return;
      map.addControl(control, position);
      tdInstance = control.getTerraDrawInstance();
      control.on('feature-deleted', handleFeatureDeleted);
      if (tdInstance) {
        attachedListeners = true;
        tdInstance.on('finish', handleFinish);
        tdInstance.on('change', handleChange);
        if (tdInstance.enabled) {
          handleReady();
        } else {
          tdInstance.on('ready', handleReady);
        }
      }
    };

    attach();

    return () => {
      active = false;
      control.off('feature-deleted', handleFeatureDeleted);
      if (
        tdInstance &&
        attachedListeners &&
        typeof tdInstance.off === 'function'
      ) {
        tdInstance.off('finish', handleFinish);
        tdInstance.off('change', handleChange);
        tdInstance.off('ready', handleReady);
      }
      try {
        const hasCtrl =
          typeof map.hasControl === 'function' ? map.hasControl(control) : true;
        if (hasCtrl) {
          map.removeControl(control);
        }
      } catch {
        // Ignore cleanup errors if the map instance has already torn down.
      }
    };
  }, [mapRef, position]);

  return null;
}
