import { useCallback, useEffect, useRef, useState } from 'react';

export type GeolocationStatus =
  'idle' | 'locating' | 'ready' | 'denied' | 'timeout' | 'unavailable';

export interface GeoCoordinates {
  lat: number;
  lng: number;
  accuracy: number;
}

export interface GeolocationState {
  status: GeolocationStatus;
  coords: GeoCoordinates | null;
  error: string | null;
  retry: () => void;
}

export interface UseGeolocationOptions {
  autoRequest?: boolean;
  timeoutMs?: number;
}

/** Captures high-accuracy GPS coordinates with a 10 s timeout in RAM only. */
export function useGeolocation({
  autoRequest = true,
  timeoutMs = 10000,
}: UseGeolocationOptions = {}): GeolocationState {
  const [status, setStatus] = useState<GeolocationStatus>('idle');
  const [coords, setCoords] = useState<GeoCoordinates | null>(null);
  const [error, setError] = useState<string | null>(null);
  const requestIdRef = useRef(0);
  const mountedRef = useRef(true);

  const requestLocation = useCallback(() => {
    const currentId = ++requestIdRef.current;
    if (
      typeof navigator === 'undefined' ||
      !('geolocation' in navigator) ||
      typeof navigator.geolocation?.getCurrentPosition !== 'function'
    ) {
      setStatus('unavailable');
      setError(
        'Location services are unavailable in this browser. Open on a phone over HTTPS to attach GPS coordinates.',
      );
      return;
    }

    setStatus('locating');
    setError(null);

    navigator.geolocation.getCurrentPosition(
      (position) => {
        if (!mountedRef.current || requestIdRef.current !== currentId) return;
        setCoords({
          lat: position.coords.latitude,
          lng: position.coords.longitude,
          accuracy: Math.max(0, Math.round(position.coords.accuracy)),
        });
        setStatus('ready');
        setError(null);
      },
      (geoError) => {
        if (!mountedRef.current || requestIdRef.current !== currentId) return;
        if (geoError.code === 1) {
          setStatus('denied');
          setError(
            'Location permission was denied. We need your GPS coordinates so responders know which venue zone needs attention. Enable Location access in your browser site settings and tap Retry location.',
          );
        } else if (geoError.code === 3) {
          setStatus('timeout');
          setError(
            'Location request timed out after 10 seconds. Step into an open area if indoors and tap Retry location.',
          );
        } else {
          setStatus('unavailable');
          setError(
            'Your current location could not be determined. Check that GPS is enabled and tap Retry location.',
          );
        }
      },
      {
        enableHighAccuracy: true,
        timeout: timeoutMs,
        maximumAge: 0,
      },
    );
  }, [timeoutMs]);

  useEffect(() => {
    mountedRef.current = true;
    if (autoRequest) {
      requestLocation();
    }
    return () => {
      mountedRef.current = false;
      requestIdRef.current += 1;
    };
  }, [autoRequest, requestLocation]);

  return { status, coords, error, retry: requestLocation };
}
