import { useEffect, useMemo, useRef, useState } from 'react';
import Map, {
  AttributionControl,
  Layer,
  Source,
  type MapRef,
} from '@vis.gl/react-maplibre';
import { setWorkerUrl } from 'maplibre-gl';
import worker from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import 'maplibre-gl/dist/maplibre-gl.css';
import type { Report, ZoneState } from '@contract/types';
import { mapStyle } from '@/lib/mapStyle';

setWorkerUrl(worker);

export default function ReportPinMap({
  zones,
  report,
}: {
  zones: ZoneState[];
  report: Report;
}) {
  const ref = useRef<MapRef>(null);
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);

  const zonesGeoJson = useMemo(
    () => ({
      type: 'FeatureCollection' as const,
      features: zones.map((zone) => ({
        type: 'Feature' as const,
        id: zone.id,
        geometry: zone.geometry,
        properties: { name: zone.name },
      })),
    }),
    [zones],
  );

  const pinGeoJson = useMemo(
    () => ({
      type: 'FeatureCollection' as const,
      features: [
        {
          type: 'Feature' as const,
          id: report.id,
          geometry: {
            type: 'Point' as const,
            coordinates: [report.lng, report.lat],
          },
          properties: {
            kind: report.kind,
            label: `#${report.id} · ${report.kind}`,
          },
        },
      ],
    }),
    [report.id, report.kind, report.lat, report.lng],
  );

  useEffect(() => {
    if (!loaded) return;
    ref.current?.flyTo({
      center: [report.lng, report.lat],
      zoom: 17,
      duration: 0,
    });
  }, [loaded, report.lat, report.lng]);

  if (failed) {
    return (
      <p className="text-muted-foreground p-4 text-sm">
        Map unavailable. Location: {report.lat.toFixed(5)},{' '}
        {report.lng.toFixed(5)}
      </p>
    );
  }

  return (
    <Map
      ref={ref}
      initialViewState={{
        longitude: report.lng,
        latitude: report.lat,
        zoom: 17,
      }}
      mapStyle={mapStyle}
      attributionControl={false}
      onLoad={() => setLoaded(true)}
      onError={() => setFailed(true)}
    >
      <AttributionControl position="top-right" compact={false} />
      <Source id="report-zones" type="geojson" data={zonesGeoJson}>
        <Layer
          id="report-zone-fill"
          type="fill"
          paint={{ 'fill-color': '#0f766e', 'fill-opacity': 0.18 }}
        />
        <Layer
          id="report-zone-line"
          type="line"
          paint={{ 'line-color': '#0f766e', 'line-width': 2 }}
        />
      </Source>
      <Source id="report-pin" type="geojson" data={pinGeoJson}>
        <Layer
          id="report-pin-circle"
          type="circle"
          paint={{
            'circle-radius': 9,
            'circle-color': [
              'match',
              ['get', 'kind'],
              'SOS',
              '#dc2626',
              '#0284c7',
            ],
            'circle-stroke-color': '#ffffff',
            'circle-stroke-width': 3,
          }}
        />
        <Layer
          id="report-pin-label"
          type="symbol"
          layout={{
            'text-field': ['get', 'label'],
            'text-size': 12,
            'text-font': ['Noto Sans Regular'],
            'text-offset': [0, 1.5],
          }}
          paint={{ 'text-halo-color': '#ffffff', 'text-halo-width': 2 }}
        />
      </Source>
    </Map>
  );
}
