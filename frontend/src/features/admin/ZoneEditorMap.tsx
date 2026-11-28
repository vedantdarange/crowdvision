import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Map, {
  AttributionControl,
  Layer,
  NavigationControl,
  Source,
  type MapRef,
} from '@vis.gl/react-maplibre';
import { Crosshair, Loader2, LocateFixed } from 'lucide-react';
import { LngLatBounds, setWorkerUrl } from 'maplibre-gl';
import worker from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import 'maplibre-gl/dist/maplibre-gl.css';
import type { PolygonGeometry, ZoneState } from '@contract/types';
import { Button } from '@/components/ui/button';
import { mapStyle } from '@/lib/mapStyle';
import { ZoneDrawControl } from './ZoneDrawControl';

setWorkerUrl(worker);

export function ZoneEditorMap({
  zones,
  editingZoneId,
  initialPolygon,
  onPolygonChange,
}: {
  zones: ZoneState[];
  editingZoneId?: number;
  initialPolygon: PolygonGeometry | null;
  onPolygonChange: (polygon: PolygonGeometry | null) => void;
}) {
  const mapRef = useRef<MapRef>(null);
  const initialFitDone = useRef(false);
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const [locating, setLocating] = useState(false);
  const [locationNote, setLocationNote] = useState<string | null>(null);

  const otherActiveZones = useMemo(
    () => zones.filter((zone) => zone.is_active && zone.id !== editingZoneId),
    [zones, editingZoneId],
  );

  const backgroundGeoJson = useMemo(
    () => ({
      type: 'FeatureCollection' as const,
      features: otherActiveZones.map((zone) => ({
        type: 'Feature' as const,
        id: zone.id,
        geometry: zone.geometry,
        properties: { name: zone.name },
      })),
    }),
    [otherActiveZones],
  );

  const centreOnZones = useCallback(() => {
    const map = mapRef.current;
    if (!map) return;

    const bounds = new LngLatBounds();
    let hasPoints = false;

    if (initialPolygon) {
      for (const ring of initialPolygon.coordinates) {
        for (const pt of ring) {
          bounds.extend([pt[0]!, pt[1]!]);
          hasPoints = true;
        }
      }
    }
    for (const zone of otherActiveZones) {
      for (const ring of zone.geometry.coordinates) {
        for (const pt of ring) {
          bounds.extend([pt[0]!, pt[1]!]);
          hasPoints = true;
        }
      }
    }

    if (!hasPoints) return;
    map.fitBounds(bounds, {
      padding: { top: 64, right: 64, bottom: 64, left: 64 },
      duration: 0,
      maxZoom: 20,
    });
  }, [initialPolygon, otherActiveZones]);

  useEffect(() => {
    if (!loaded || initialFitDone.current) return;
    centreOnZones();
    initialFitDone.current = true;
  }, [loaded, centreOnZones]);

  function handleCentreOnMe() {
    setLocationNote(null);
    if (
      typeof navigator === 'undefined' ||
      !('geolocation' in navigator) ||
      typeof navigator.geolocation?.getCurrentPosition !== 'function'
    ) {
      setLocationNote('Geolocation is unavailable in this browser.');
      return;
    }

    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setLocating(false);
        mapRef.current?.flyTo({
          center: [position.coords.longitude, position.coords.latitude],
          zoom: 19,
          duration: 400,
        });
      },
      () => {
        setLocating(false);
        setLocationNote(
          'Could not get your location. Allow browser location permission or pan/zoom manually.',
        );
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 },
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="police-actions">
          <Button
            type="button"
            variant="outline"
            className="min-h-11 gap-1.5"
            onClick={centreOnZones}
          >
            <Crosshair size={16} aria-hidden />
            Centre on zones
          </Button>
          <Button
            type="button"
            variant="outline"
            className="min-h-11 gap-1.5"
            onClick={handleCentreOnMe}
            disabled={locating}
          >
            {locating ? (
              <Loader2 size={16} className="animate-spin" aria-hidden />
            ) : (
              <LocateFixed size={16} aria-hidden />
            )}
            Centre on my location
          </Button>
        </div>
        <span className="text-muted-foreground text-xs">
          Zoom in closely (up to ~1 m scale) or out for large venue zones.
        </span>
      </div>

      {locationNote && (
        <p role="status" className="text-muted-foreground text-xs">
          {locationNote}
        </p>
      )}

      <div className="relative isolate h-[52vh] min-h-[340px] w-full overflow-hidden rounded-xl border">
        {failed ? (
          <p className="text-muted-foreground p-6 text-sm">
            Interactive map tiles could not load in this environment.
          </p>
        ) : (
          <Map
            ref={mapRef}
            initialViewState={{
              longitude: initialPolygon?.coordinates[0]?.[0]?.[0] ?? 73.8553,
              latitude: initialPolygon?.coordinates[0]?.[0]?.[1] ?? 18.5195,
              zoom: 18,
            }}
            minZoom={10}
            maxZoom={23}
            mapStyle={mapStyle}
            attributionControl={false}
            onLoad={() => setLoaded(true)}
            onError={() => setFailed(true)}
          >
            <NavigationControl position="top-left" showCompass={false} />
            <AttributionControl position="bottom-right" compact={false} />
            <Source
              id="existing-readonly-zones"
              type="geojson"
              data={backgroundGeoJson}
            >
              <Layer
                id="existing-zones-fill"
                type="fill"
                paint={{
                  'fill-color': '#64748b',
                  'fill-opacity': 0.22,
                }}
              />
              <Layer
                id="existing-zones-line"
                type="line"
                paint={{
                  'line-color': '#475569',
                  'line-width': 2,
                  'line-dasharray': [2, 2],
                }}
              />
              <Layer
                id="existing-zones-label"
                type="symbol"
                layout={{
                  'text-field': ['get', 'name'],
                  'text-size': 12,
                  'text-font': ['Noto Sans Regular'],
                }}
                paint={{ 'text-halo-color': '#ffffff', 'text-halo-width': 2 }}
              />
            </Source>
            <ZoneDrawControl
              initialPolygon={initialPolygon}
              onChange={onPolygonChange}
            />
          </Map>
        )}
      </div>
    </div>
  );
}
