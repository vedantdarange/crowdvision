import { useMemo, useState, useEffect, useRef } from 'react';
import Map, {
  Source,
  Layer,
  AttributionControl,
  type MapRef,
} from '@vis.gl/react-maplibre';
import { LngLatBounds, setWorkerUrl } from 'maplibre-gl';
import worker from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import 'maplibre-gl/dist/maplibre-gl.css';
import { mapStyle } from '@/lib/mapStyle';
import type { PublicZoneState } from '@contract/types';
setWorkerUrl(worker);
function useZoneLayers(zones: PublicZoneState[]) {
  return useMemo(
    () => ({
      type: 'FeatureCollection' as const,
      features: zones.map((z) => ({
        type: 'Feature' as const,
        id: z.zone_id,
        geometry: z.geometry,
        properties: {
          level: z.level,
          label:
            z.name +
            (z.density === null ? '' : ' · ' + z.density.toFixed(1) + '/m²'),
        },
      })),
    }),
    [zones],
  );
}
export default function ZoneMap({
  zones,
  selected,
  select,
}: {
  zones: PublicZoneState[];
  selected: number | null;
  select: (id: number) => void;
}) {
  const ref = useRef<MapRef>(null),
    fitted = useRef(false);
  const [loaded, setLoaded] = useState(false),
    [failed, setFailed] = useState(false);
  const data = useZoneLayers(zones);
  useEffect(() => {
    if (!loaded || fitted.current || !zones.length) return;
    const bounds = new LngLatBounds();
    for (const z of zones)
      for (const point of z.geometry.coordinates.flat())
        bounds.extend([point[0]!, point[1]!]);
    ref.current?.fitBounds(bounds, {
      padding: { top: 52, right: 28, bottom: 100, left: 28 },
      duration: 0,
      maxZoom: 19,
    });
    fitted.current = true;
  }, [loaded, zones]);
  if (failed) return <p>Map unavailable. Browse the zone list.</p>;
  return (
    <Map
      ref={ref}
      mapStyle={mapStyle}
      attributionControl={false}
      onLoad={() => setLoaded(true)}
      onError={() => setFailed(true)}
      interactiveLayerIds={['zone-fill']}
      onClick={(event) => {
        const id = event.features?.[0]?.id;
        if (typeof id === 'number') select(id);
      }}
    >
      <AttributionControl position="top-right" compact={false} />
      <Source id="zones" type="geojson" data={data}>
        <Layer
          id="zone-fill"
          type="fill"
          paint={{
            'fill-color': [
              'match',
              ['get', 'level'],
              'SAFE',
              '#15803d',
              'WARNING',
              '#e29413',
              'CRITICAL',
              '#b91c1c',
              '#64748b',
            ],
            'fill-opacity': 0.62,
          }}
        />
        <Layer
          id="zone-outline"
          type="line"
          paint={{
            'line-width': ['case', ['==', ['get', 'level'], 'CRITICAL'], 5, 2],
            'line-color': [
              'case',
              ['==', ['id'], selected ?? -1],
              '#005cba',
              '#252525',
            ],
          }}
        />
        <Layer
          id="zone-label"
          type="symbol"
          layout={{
            'text-field': ['get', 'label'],
            'text-size': 13,
            'text-font': ['Noto Sans Regular'],
          }}
          paint={{ 'text-halo-color': 'white', 'text-halo-width': 2 }}
        />
      </Source>
    </Map>
  );
}
