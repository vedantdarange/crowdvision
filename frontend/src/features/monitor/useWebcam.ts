import { useCallback, useEffect, useRef, useState } from 'react';

export type WebcamError =
  'not-secure' | 'not-allowed' | 'not-found' | 'in-use' | 'unknown';

const errorMessages: Record<WebcamError, string> = {
  'not-secure': 'Camera needs HTTPS (use the tunnel URL)',
  'not-allowed': 'Allow camera access in your browser settings',
  'not-found': 'No camera found on this device',
  'in-use': 'Camera is in use by another application',
  unknown: 'Could not access the camera',
};

function mapError(err: unknown): WebcamError {
  if (err instanceof DOMException) {
    if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError')
      return 'not-allowed';
    if (err.name === 'NotFoundError' || err.name === 'DevicesNotFoundError')
      return 'not-found';
    if (
      err.name === 'NotReadableError' ||
      err.name === 'TrackStartError' ||
      err.name === 'AbortError'
    )
      return 'in-use';
  }
  return 'unknown';
}

function stopStreamTracks(stream: MediaStream | null) {
  if (!stream) return;
  for (const track of stream.getTracks()) track.stop();
}

export interface WebcamState {
  /** Ref to attach to a <video> element. */
  videoRef: React.RefObject<HTMLVideoElement | null>;
  /** Whether the stream is active. */
  active: boolean;
  /** Human-readable error message, or null. */
  errorMessage: string | null;
  /** Error key for programmatic use. */
  error: WebcamError | null;
  /** Start the webcam. */
  start: () => void;
  /** Stop the webcam (releases all tracks). */
  stop: () => void;
}

export function useWebcam(
  facing: 'user' | 'environment' = 'user',
): WebcamState {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const mountedRef = useRef(true);
  const requestIdRef = useRef(0);
  const [active, setActive] = useState(false);
  const [error, setError] = useState<WebcamError | null>(null);

  const stopTracks = useCallback(() => {
    stopStreamTracks(streamRef.current);
    streamRef.current = null;
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
  }, []);

  const stop = useCallback(() => {
    requestIdRef.current += 1;
    stopTracks();
    setActive(false);
  }, [stopTracks]);

  const start = useCallback(() => {
    if (typeof window !== 'undefined' && !window.isSecureContext) {
      requestIdRef.current += 1;
      stopTracks();
      setActive(false);
      setError('not-secure');
      return;
    }

    if (
      typeof navigator === 'undefined' ||
      !navigator.mediaDevices?.getUserMedia
    ) {
      requestIdRef.current += 1;
      stopTracks();
      setActive(false);
      setError('not-found');
      return;
    }

    setError(null);
    // Stop any existing stream first and invalidate pending requests (idempotent).
    const requestId = ++requestIdRef.current;
    stopTracks();

    navigator.mediaDevices
      .getUserMedia({
        video: { facingMode: facing, width: { ideal: 1280 } },
        audio: false,
      })
      .then((stream) => {
        // If stopped, restarted, or unmounted while getUserMedia was pending, release immediately.
        if (!mountedRef.current || requestIdRef.current !== requestId) {
          stopStreamTracks(stream);
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
        }
        setActive(true);
        setError(null);
      })
      .catch((err: unknown) => {
        if (!mountedRef.current || requestIdRef.current !== requestId) return;
        setError(mapError(err));
        setActive(false);
      });
  }, [facing, stopTracks]);

  // Attach stream if the <video> mounts after getUserMedia resolves.
  useEffect(() => {
    if (
      active &&
      videoRef.current &&
      streamRef.current &&
      videoRef.current.srcObject !== streamRef.current
    ) {
      videoRef.current.srcObject = streamRef.current;
    }
  }, [active]);

  // Cleanup on unmount — StrictMode-safe: re-arms mountedRef on mount/remount.
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      requestIdRef.current += 1;
      stopTracks();
    };
  }, [stopTracks]);

  return {
    videoRef,
    active,
    errorMessage: error ? errorMessages[error] : null,
    error,
    start,
    stop,
  };
}
