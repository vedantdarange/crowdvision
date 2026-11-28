import { useCallback, useContext, useEffect, useRef, useState } from 'react';
import {
  QueryClient,
  QueryClientContext,
  useQuery,
} from '@tanstack/react-query';
import type { ApiOne, FrameResult, RuntimeConfig } from '@contract/types';
import { apiClient } from '@/lib/apiClient';
import { queryKeys as k } from '@/lib/queryKeys';
import { socket } from '@/lib/socket';
import {
  claimActiveStream,
  releaseActiveStream,
  useMonitorStore,
  type FrameStreamError,
} from './streamStore';

export type StreamerState =
  'idle' | 'streaming' | 'in-use' | 'stopped' | 'error';

export interface LatencyStats {
  p50: number;
  p95: number;
}

export interface FrameStreamerResult {
  state: StreamerState;
  fps: number;
  latencyMs: LatencyStats;
  drops: number;
  lastResult: FrameResult | null;
  /** Timestamp (ms) when lastResult was received, or null. */
  lastResultAt: number | null;
  /** Stop the streamer (also called on SOURCE_IN_USE) */
  stop: () => void;
}

/** Fallback defaults used if /config has not loaded yet. */
const DEFAULTS: Pick<
  RuntimeConfig,
  'target_fps' | 'frame_width' | 'jpeg_quality'
> = {
  target_fps: 3,
  frame_width: 640,
  jpeg_quality: 0.7,
};

const TIMEOUT_MS = 2000;
const fallbackClient = new QueryClient();

function percentile(sorted: number[], p: number): number {
  if (sorted.length === 0) return 0;
  const index = (p / 100) * (sorted.length - 1);
  const lower = Math.floor(index);
  const upper = Math.ceil(index);
  if (lower === upper) return sorted[lower]!;
  return sorted[lower]! + (sorted[upper]! - sorted[lower]!) * (index - lower);
}

function hasVideoMetadata(video: HTMLVideoElement): boolean {
  const ready =
    video.readyState === undefined || Number.isNaN(video.readyState)
      ? true
      : video.readyState >= 1;
  return ready && video.videoWidth > 0 && video.videoHeight > 0;
}

export interface FrameStreamerOptions {
  video: HTMLVideoElement | null;
  sourceId: number;
  enabled: boolean;
  /** Whether this is a webcam source (pauses on hidden tab). */
  isWebcam?: boolean;
  /** Optional config override (defaults to GET /config via TanStack Query). */
  config?: Pick<
    RuntimeConfig,
    'target_fps' | 'frame_width' | 'jpeg_quality'
  > | null;
  /** Signal that the next frame should have reset: true (loop restart). */
  resetRequested?: boolean;
  /** Called after the reset flag is consumed. */
  onResetConsumed?: () => void;
  /**
   * When false, frame updates write only to the Zustand monitor store instead of
   * calling local React setState (prevents 3 FPS re-render storms in MonitorPage).
   */
  syncState?: boolean;
  /** Called when the server or another streamer stops this stream. */
  onExternalStop?: (reason: FrameStreamError | 'PREEMPTED') => void;
}

export function useFrameStreamer({
  video,
  sourceId,
  enabled,
  isWebcam = false,
  config: configOverride,
  resetRequested = false,
  onResetConsumed,
  syncState = true,
  onExternalStop,
}: FrameStreamerOptions): FrameStreamerResult {
  const queryClient = useContext(QueryClientContext);
  const configQuery = useQuery(
    {
      queryKey: k.config,
      queryFn: async () =>
        (await apiClient<ApiOne<RuntimeConfig>>('/config')).data,
      staleTime: Infinity,
      enabled: !configOverride && !!queryClient,
    },
    queryClient ?? fallbackClient,
  );

  const [state, setState] = useState<StreamerState>('idle');
  const [fps, setFps] = useState(0);
  const [latencyMs, setLatencyMs] = useState<LatencyStats>({ p50: 0, p95: 0 });
  const [drops, setDrops] = useState(0);
  const [lastResult, setLastResult] = useState<FrameResult | null>(null);
  const [lastResultAt, setLastResultAt] = useState<number | null>(null);

  const ownerId = useRef(Symbol('frame-streamer')).current;
  const runIdRef = useRef(0);
  const seqRef = useRef(0);
  const inFlightRef = useRef(false);
  const inFlightSeqRef = useRef(0);
  const sentAtRef = useRef(0);
  const lastSentRef = useRef(-Infinity);
  const needsResetRef = useRef(true);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const loopRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const latencySamplesRef = useRef<number[]>([]);
  const frameTimesRef = useRef<number[]>([]);
  const stoppedRef = useRef(false);
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;

  const syncStateRef = useRef(syncState);
  syncStateRef.current = syncState;

  const onResetConsumedRef = useRef(onResetConsumed);
  onResetConsumedRef.current = onResetConsumed;

  const onExternalStopRef = useRef(onExternalStop);
  onExternalStopRef.current = onExternalStop;

  const resolved = configOverride ?? configQuery.data ?? DEFAULTS;
  const targetFps = Math.max(0.1, resolved.target_fps);
  const frameWidth = resolved.frame_width;
  const jpegQuality = resolved.jpeg_quality;

  // Consume external reset request (e.g. video loop restart).
  useEffect(() => {
    if (resetRequested) {
      needsResetRef.current = true;
      onResetConsumedRef.current?.();
    }
  }, [resetRequested]);

  const clearTimers = useCallback(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
    if (loopRef.current) {
      clearTimeout(loopRef.current);
      loopRef.current = null;
    }
  }, []);

  const stop = useCallback(() => {
    runIdRef.current += 1;
    stoppedRef.current = true;
    inFlightRef.current = false;
    inFlightSeqRef.current = 0;
    clearTimers();
    releaseActiveStream(ownerId);
    if (syncStateRef.current) {
      setState((prev) => (prev === 'in-use' ? 'in-use' : 'stopped'));
    } else {
      useMonitorStore.setState((prev) => ({
        state: prev.state === 'in-use' ? 'in-use' : 'stopped',
        activeSourceId: null,
      }));
    }
  }, [clearTimers, ownerId]);

  const preemptStop = useCallback(() => {
    stop();
    onExternalStopRef.current?.('PREEMPTED');
  }, [stop]);

  useEffect(() => {
    if (!enabled || !video || sourceId <= 0) {
      runIdRef.current += 1;
      stoppedRef.current = true;
      inFlightRef.current = false;
      inFlightSeqRef.current = 0;
      clearTimers();
      releaseActiveStream(ownerId);
      if (syncStateRef.current) {
        setState('idle');
      } else {
        useMonitorStore.setState({ state: 'idle', activeSourceId: null });
      }
      return;
    }

    claimActiveStream(ownerId, preemptStop);

    if (!canvasRef.current) {
      canvasRef.current = document.createElement('canvas');
    }
    const canvas = canvasRef.current;
    const intervalMs = 1000 / targetFps;
    const runId = ++runIdRef.current;

    stoppedRef.current = false;
    seqRef.current = 0;
    needsResetRef.current = true;
    inFlightRef.current = false;
    inFlightSeqRef.current = 0;
    lastSentRef.current = -Infinity;
    latencySamplesRef.current = [];
    frameTimesRef.current = [];

    if (syncStateRef.current) {
      setDrops(0);
      setFps(0);
      setLatencyMs({ p50: 0, p95: 0 });
      setLastResult(null);
      setLastResultAt(null);
      setState('streaming');
    } else {
      useMonitorStore.setState({
        activeSourceId: sourceId,
        state: 'streaming',
        fps: 0,
        latencyMs: { p50: 0, p95: 0 },
        drops: 0,
        lastResult: null,
        lastResultAt: null,
        lastError: null,
        inUseSourceId: null,
      });
    }

    let metadataListenerAttached = false;

    function scheduleAttempt(delayMs: number) {
      if (
        runIdRef.current !== runId ||
        stoppedRef.current ||
        !enabledRef.current
      ) {
        return;
      }
      if (loopRef.current) clearTimeout(loopRef.current);
      loopRef.current = setTimeout(() => {
        loopRef.current = null;
        trySendNext();
      }, delayMs);
    }

    function onMetadataReady() {
      metadataListenerAttached = false;
      trySendNext();
    }

    function trySendNext() {
      if (
        runIdRef.current !== runId ||
        stoppedRef.current ||
        !enabledRef.current ||
        inFlightRef.current
      ) {
        return;
      }

      // Pause webcam sending while tab is hidden.
      if (isWebcam && typeof document !== 'undefined' && document.hidden) {
        scheduleAttempt(Math.max(intervalMs, 250));
        return;
      }

      // Never read videoWidth/videoHeight before loadedmetadata.
      if (!video || !hasVideoMetadata(video)) {
        if (video && !metadataListenerAttached) {
          metadataListenerAttached = true;
          video.addEventListener('loadedmetadata', onMetadataReady, {
            once: true,
          });
        }
        return;
      }

      const now = Date.now();
      const elapsed = now - lastSentRef.current;
      if (elapsed < intervalMs) {
        scheduleAttempt(intervalMs - elapsed);
        return;
      }

      const aspect = video.videoHeight / video.videoWidth;
      const w = frameWidth;
      const h = Math.max(1, Math.round(w * aspect));
      if (canvas.width !== w) canvas.width = w;
      if (canvas.height !== h) canvas.height = h;
      const ctx = canvas.getContext('2d');
      if (!ctx) {
        scheduleAttempt(intervalMs);
        return;
      }

      // Mark in-flight BEFORE async toBlob/arrayBuffer so concurrent captures never race.
      inFlightRef.current = true;
      ctx.drawImage(video, 0, 0, w, h);

      // Always JPEG — never PNG or WebP (Safari ignores WebP in canvas.toBlob).
      canvas.toBlob(
        (blob) => {
          if (
            !blob ||
            runIdRef.current !== runId ||
            stoppedRef.current ||
            !enabledRef.current
          ) {
            if (runIdRef.current === runId) inFlightRef.current = false;
            scheduleAttempt(intervalMs);
            return;
          }

          void blob.arrayBuffer().then((buffer) => {
            if (
              runIdRef.current !== runId ||
              stoppedRef.current ||
              !enabledRef.current
            ) {
              if (runIdRef.current === runId) inFlightRef.current = false;
              return;
            }

            const seq = ++seqRef.current;
            const reset = needsResetRef.current;
            if (reset) needsResetRef.current = false;

            const emitTime = Date.now();
            inFlightSeqRef.current = seq;
            sentAtRef.current = emitTime;
            lastSentRef.current = emitTime;

            socket.emit('frame:submit', {
              source_id: sourceId,
              seq,
              captured_at: new Date(emitTime).toISOString(),
              ...(reset ? { reset: true } : {}),
              width: w,
              height: h,
              image: buffer,
            });

            // Rolling 5 s FPS estimate based on emitted frames.
            const times = frameTimesRef.current;
            times.push(emitTime);
            const cutoff = emitTime - 5000;
            while (times.length > 0 && times[0]! < cutoff) times.shift();
            if (times.length >= 2) {
              const span = times[times.length - 1]! - times[0]!;
              const nextFps =
                span > 0
                  ? Math.round(((times.length - 1) / (span / 1000)) * 10) / 10
                  : 0;
              if (syncStateRef.current) {
                setFps(nextFps);
              } else {
                useMonitorStore.setState((prev) =>
                  prev.fps === nextFps ? prev : { fps: nextFps },
                );
              }
            }

            timeoutRef.current = setTimeout(() => {
              timeoutRef.current = null;
              if (runIdRef.current !== runId || stoppedRef.current) return;
              if (inFlightRef.current && inFlightSeqRef.current === seq) {
                inFlightRef.current = false;
                inFlightSeqRef.current = 0;
                if (syncStateRef.current) {
                  setDrops((d) => d + 1);
                } else {
                  useMonitorStore.setState((prev) => ({
                    drops: prev.drops + 1,
                  }));
                }
                trySendNext();
              }
            }, TIMEOUT_MS);
          });
        },
        'image/jpeg',
        jpegQuality,
      );
    }

    const handleResult = (result: FrameResult) => {
      if (runIdRef.current !== runId || stoppedRef.current) return;
      if (result.source_id !== sourceId) return;
      if (!inFlightRef.current || result.seq !== inFlightSeqRef.current) return;

      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
        timeoutRef.current = null;
      }
      inFlightRef.current = false;
      inFlightSeqRef.current = 0;

      const now = Date.now();

      if (result.error === 'SOURCE_IN_USE') {
        runIdRef.current += 1;
        stoppedRef.current = true;
        clearTimers();
        releaseActiveStream(ownerId);
        if (syncStateRef.current) {
          setLastResult(result);
          setLastResultAt(now);
          setState('in-use');
        } else {
          useMonitorStore.setState({
            state: 'in-use',
            activeSourceId: null,
            lastResult: result,
            lastResultAt: now,
            lastError: 'SOURCE_IN_USE',
            inUseSourceId: sourceId,
          });
        }
        onExternalStopRef.current?.('SOURCE_IN_USE');
        return;
      }

      let nextLatency: LatencyStats | null = null;
      if (sentAtRef.current > 0) {
        const latency = Math.max(0, now - sentAtRef.current);
        const samples = latencySamplesRef.current;
        samples.push(latency);
        if (samples.length > 100) samples.shift();
        const sorted = [...samples].sort((a, b) => a - b);
        nextLatency = {
          p50: Math.round(percentile(sorted, 50)),
          p95: Math.round(percentile(sorted, 95)),
        };
      }

      if (syncStateRef.current) {
        if (nextLatency) setLatencyMs(nextLatency);
        setLastResult(result);
        setLastResultAt(now);
      } else {
        const nextError =
          !result.ok && result.error && result.error !== 'DETECTOR_BUSY'
            ? result.error
            : null;
        useMonitorStore.setState((prev) => ({
          ...(nextLatency ? { latencyMs: nextLatency } : {}),
          lastResult: result,
          lastResultAt: now,
          lastError: nextError,
          inUseSourceId:
            prev.inUseSourceId === sourceId ? null : prev.inUseSourceId,
        }));
      }
      trySendNext();
    };

    const onVisibilityChange = () => {
      if (!document.hidden) trySendNext();
    };

    socket.on('frame:result', handleResult);
    if (isWebcam && typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', onVisibilityChange);
    }

    trySendNext();

    return () => {
      runIdRef.current += 1;
      stoppedRef.current = true;
      inFlightRef.current = false;
      inFlightSeqRef.current = 0;
      socket.off('frame:result', handleResult);
      if (isWebcam && typeof document !== 'undefined') {
        document.removeEventListener('visibilitychange', onVisibilityChange);
      }
      clearTimers();
      releaseActiveStream(ownerId);
      video.removeEventListener('loadedmetadata', onMetadataReady);
    };
  }, [
    enabled,
    video,
    sourceId,
    targetFps,
    frameWidth,
    jpegQuality,
    isWebcam,
    clearTimers,
    ownerId,
    preemptStop,
  ]);

  return {
    state: enabled ? state : 'idle',
    fps,
    latencyMs,
    drops,
    lastResult,
    lastResultAt,
    stop,
  };
}
