import { memo, useCallback, useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import {
  Camera,
  Film,
  Pause,
  Play,
  RefreshCw,
  Repeat,
  Square,
  TriangleAlert,
} from 'lucide-react';
import type { SourceInfo, ZoneState } from '@contract/types';
import { useConfig } from '@/features/zones/api';
import { useZones } from '@/features/police/data';
import { Age } from '@/features/police/Alerts';
import { useConnection } from '@/features/realtime/RealtimeProvider';
import { LevelBadge } from '@/components/status/LevelBadge';
import { TrendIcon } from '@/components/status/TrendIcon';
import { DensityValue } from '@/components/status/DensityValue';
import { EmptyState } from '@/components/EmptyState';
import { Button } from '@/components/ui/button';
import { useWebcam } from './useWebcam';
import { useVideoFile } from './useVideoFile';
import { useFrameStreamer } from './useFrameStreamer';
import { DetectionOverlay } from './DetectionOverlay';
import { MonitorHud } from './MonitorHud';
import { SourcePicker } from './SourcePicker';
import {
  clearStreamErrors,
  resetStreamSnapshot,
  useMonitorStore,
  type FrameStreamError,
} from './streamStore';

type CaptureMode = 'webcam' | 'video';

const STREAM_ERROR_MESSAGES: Record<
  Exclude<FrameStreamError, 'DETECTOR_BUSY'>,
  string
> = {
  SOURCE_IN_USE:
    'This source is already being streamed from another tab or device',
  FORBIDDEN: 'Permission denied while streaming frames to this source',
  UNKNOWN_SOURCE: 'Selected source was not found or is inactive',
  BAD_IMAGE: 'Captured frame could not be processed as JPEG',
  DETECTOR_UNAVAILABLE:
    'Crowd detector is currently unavailable. Check backend worker status.',
};

/** Selector-scoped wrapper so 3 FPS frame updates only re-render the overlay. */
const ConnectedDetectionOverlay = memo(function ConnectedDetectionOverlay({
  videoRef,
}: {
  videoRef: React.RefObject<HTMLVideoElement | null>;
}) {
  const lastResult = useMonitorStore((s) => s.lastResult);
  const lastResultAt = useMonitorStore((s) => s.lastResultAt);
  return (
    <DetectionOverlay
      videoRef={videoRef}
      lastResult={lastResult}
      resultTimestamp={lastResultAt}
    />
  );
});

/** Selector-scoped wrapper so 3 FPS frame updates only re-render the HUD. */
const ConnectedMonitorHud = memo(function ConnectedMonitorHud() {
  const lastResult = useMonitorStore((s) => s.lastResult);
  const fps = useMonitorStore((s) => s.fps);
  const latencyMs = useMonitorStore((s) => s.latencyMs);
  const drops = useMonitorStore((s) => s.drops);
  return (
    <MonitorHud
      lastResult={lastResult}
      fps={fps}
      latencyMs={latencyMs}
      drops={drops}
    />
  );
});

/** Subscribes only to error/in-use transitions, never to normal 3 FPS frames. */
const StreamErrorBanner = memo(function StreamErrorBanner({
  selectedSourceId,
}: {
  selectedSourceId: number | null;
}) {
  const lastError = useMonitorStore((s) => s.lastError);
  const inUseSourceId = useMonitorStore((s) => s.inUseSourceId);

  if (selectedSourceId !== null && inUseSourceId === selectedSourceId) {
    return (
      <p
        role="alert"
        className="rounded-lg border border-critical/40 bg-critical-bg px-3 py-2 text-sm font-medium text-critical"
      >
        {STREAM_ERROR_MESSAGES.SOURCE_IN_USE}
      </p>
    );
  }

  if (lastError && lastError !== 'DETECTOR_BUSY') {
    return (
      <p
        role="alert"
        className="rounded-lg border border-critical/40 bg-critical-bg px-3 py-2 text-sm font-medium text-critical"
      >
        {STREAM_ERROR_MESSAGES[lastError]}
      </p>
    );
  }

  return null;
});

/** Zone live status panel driven by zone:detail (never by 3 FPS frames). */
const ZoneStatusCard = memo(function ZoneStatusCard({
  zone,
}: {
  zone: ZoneState | undefined;
}) {
  if (!zone) return null;
  return (
    <section
      aria-label="Zone live status"
      className="glass flex flex-col justify-between gap-3"
    >
      <div className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="m-0">Zone status · {zone.name}</h2>
          <Link to={`/police/zones/${zone.id}`} className="text-sm underline">
            Open zone live view
          </Link>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <LevelBadge level={zone.level} />
          <TrendIcon trend={zone.trend} />
        </div>
        <div className="grid grid-cols-2 gap-3 text-sm">
          <div>
            <span className="text-muted-foreground">Zone density</span>
            <p className="text-base font-semibold">
              <DensityValue value={zone.density} />
            </p>
          </div>
          <div>
            <span className="text-muted-foreground">Zone count</span>
            <p className="tabular-nums text-base font-semibold">
              {zone.count ?? '—'}
            </p>
          </div>
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        {zone.live_updated_at ? 'Updated ' : ''}
        <Age ts={zone.live_updated_at} />
      </p>
    </section>
  );
});

export function MonitorPage() {
  const [searchParams] = useSearchParams();
  const { data: zones } = useZones();
  const { data: config } = useConfig();
  const connectionStatus = useConnection((s) => s.status);

  const requestedZoneId = Number(searchParams.get('zone_id') ?? '');
  const initialZone =
    zones.find((z) => z.id === requestedZoneId) ?? zones[0] ?? null;

  const [selectedZoneId, setSelectedZoneId] = useState<number>(
    initialZone?.id ?? 0,
  );
  const [selectedSource, setSelectedSource] = useState<SourceInfo | null>(
    () => initialZone?.sources.find((s) => s.is_active) ?? null,
  );
  const [mode, setMode] = useState<CaptureMode>(() =>
    selectedSource?.kind === 'VIDEO_FILE' ? 'video' : 'webcam',
  );
  const [facing, setFacing] = useState<'user' | 'environment'>('user');
  const [streaming, setStreaming] = useState(false);
  const [videoEl, setVideoEl] = useState<HTMLVideoElement | null>(null);

  const pendingFacingRestartRef = useRef(false);
  const {
    videoRef: webcamVideoRef,
    active: webcamActive,
    error: webcamError,
    errorMessage: webcamErrorMessage,
    start: startWebcam,
    stop: stopWebcam,
  } = useWebcam(facing);
  const {
    videoRef: videoFileRef,
    loaded: videoLoaded,
    playing: videoPlaying,
    loop: videoLoop,
    loopRestarted,
    clearLoopRestart,
    loadFile,
    play: playVideo,
    pause: pauseVideo,
    toggleLoop,
    unload: unloadVideo,
  } = useVideoFile();

  // Keep selectedZoneId valid if zones list changes.
  useEffect(() => {
    if (zones.length === 0) {
      if (selectedZoneId !== 0) setSelectedZoneId(0);
      return;
    }
    if (!zones.some((z) => z.id === selectedZoneId)) {
      const fallback = zones[0]!;
      setSelectedZoneId(fallback.id);
      const firstSource = fallback.sources.find((s) => s.is_active) ?? null;
      setSelectedSource(firstSource);
    }
  }, [zones, selectedZoneId]);

  const activeZone = zones.find((z) => z.id === selectedZoneId);
  const selectedSourceId = selectedSource?.id ?? null;

  const attachVideoRef = useCallback(
    (node: HTMLVideoElement | null) => {
      if (mode === 'webcam') {
        webcamVideoRef.current = node;
      } else {
        videoFileRef.current = node;
      }
      setVideoEl(node);
    },
    [mode, webcamVideoRef, videoFileRef],
  );

  const handleExternalStop = useCallback(
    (reason: FrameStreamError | 'PREEMPTED') => {
      setStreaming(false);
      if (reason === 'SOURCE_IN_USE' || reason === 'PREEMPTED') {
        stopWebcam();
        pauseVideo();
      }
    },
    [stopWebcam, pauseVideo],
  );

  const streamer = useFrameStreamer({
    video: videoEl,
    sourceId: selectedSourceId ?? 0,
    enabled: streaming && selectedSourceId !== null,
    isWebcam: mode === 'webcam',
    config,
    resetRequested: loopRestarted,
    onResetConsumed: clearLoopRestart,
    syncState: false,
    onExternalStop: handleExternalStop,
  });
  const stopStreamer = streamer.stop;

  // If webcam fails (e.g. NotAllowedError or insecure context), cancel streaming intent.
  useEffect(() => {
    if (webcamError && streaming) {
      setStreaming(false);
    }
  }, [webcamError, streaming]);

  // Restart webcam cleanly after camera facing toggles while active.
  useEffect(() => {
    if (pendingFacingRestartRef.current) {
      pendingFacingRestartRef.current = false;
      startWebcam();
    }
  }, [facing, startWebcam]);

  // Reset stream store snapshot when leaving the monitor page.
  useEffect(() => {
    return () => {
      resetStreamSnapshot();
    };
  }, []);

  const stopStreamAndMedia = useCallback(() => {
    setStreaming(false);
    stopStreamer();
    stopWebcam();
    pauseVideo();
  }, [stopStreamer, stopWebcam, pauseVideo]);

  const handleSelectZone = useCallback(
    (nextZoneId: number) => {
      if (nextZoneId === selectedZoneId) return;
      stopStreamAndMedia();
      unloadVideo();
      resetStreamSnapshot();
      setSelectedZoneId(nextZoneId);
      const nextZone = zones.find((z) => z.id === nextZoneId);
      const firstSource = nextZone?.sources.find((s) => s.is_active) ?? null;
      setSelectedSource(firstSource);
      if (firstSource) {
        setMode(firstSource.kind === 'VIDEO_FILE' ? 'video' : 'webcam');
      }
    },
    [selectedZoneId, stopStreamAndMedia, unloadVideo, zones],
  );

  const handleSelectSource = useCallback(
    (nextSource: SourceInfo | null) => {
      const prevId = selectedSource?.id ?? null;
      const nextId = nextSource?.id ?? null;
      if (prevId !== nextId) {
        stopStreamAndMedia();
        resetStreamSnapshot();
      }
      setSelectedSource(nextSource);
      if (nextSource && prevId !== nextId) {
        setMode(nextSource.kind === 'VIDEO_FILE' ? 'video' : 'webcam');
      }
    },
    [selectedSource?.id, stopStreamAndMedia],
  );

  const handleSwitchMode = useCallback(
    (nextMode: CaptureMode) => {
      if (nextMode === mode) return;
      setStreaming(false);
      stopStreamer();
      clearStreamErrors();
      if (nextMode === 'video') {
        stopWebcam();
      } else {
        unloadVideo();
      }
      setMode(nextMode);
    },
    [mode, stopStreamer, stopWebcam, unloadVideo],
  );

  const handleToggleFacing = useCallback(() => {
    if (webcamActive || streaming) {
      stopWebcam();
      pendingFacingRestartRef.current = true;
    }
    setFacing((prev) => (prev === 'user' ? 'environment' : 'user'));
  }, [webcamActive, streaming, stopWebcam]);

  const handleStart = useCallback(() => {
    if (!selectedSourceId) return;
    if (mode === 'video' && !videoLoaded) return;

    clearStreamErrors();
    if (mode === 'webcam') {
      if (!webcamActive) {
        startWebcam();
      }
      setStreaming(true);
    } else {
      if (!videoPlaying) {
        playVideo();
      }
      setStreaming(true);
    }
  }, [
    selectedSourceId,
    mode,
    videoLoaded,
    webcamActive,
    startWebcam,
    videoPlaying,
    playVideo,
  ]);

  const handleStop = useCallback(() => {
    stopStreamAndMedia();
  }, [stopStreamAndMedia]);

  if (zones.length === 0) {
    return (
      <section className="police-page">
        <header>
          <h1>Camera control</h1>
        </header>
        <EmptyState
          title="No active zones"
          description="Create an active zone in Admin before streaming a camera or video feed."
          action={
            <Link to="/police" className="underline">
              Back to dashboard
            </Link>
          }
        />
      </section>
    );
  }

  const isSecureContext =
    typeof window === 'undefined' ? true : window.isSecureContext;
  const activeVideoRef = mode === 'webcam' ? webcamVideoRef : videoFileRef;

  return (
    <section className="police-page">
      <header>
        <div>
          <h1>Camera control</h1>
          <p className="text-sm text-muted-foreground">
            Stream one webcam or video feed per tab to score occupancy live.
          </p>
        </div>
      </header>

      <div className="police-grid">
        <section className="glass space-y-4">
          <h2>Source &amp; capture setup</h2>
          <SourcePicker
            zones={zones}
            selectedZoneId={selectedZoneId}
            selectedSourceId={selectedSourceId}
            onSelectZone={handleSelectZone}
            onSelectSource={handleSelectSource}
            defaultKind={mode === 'video' ? 'VIDEO_FILE' : 'WEBCAM'}
          />

          <div className="space-y-2">
            <span className="text-sm font-medium">Input mode</span>
            <div
              role="group"
              aria-label="Capture mode"
              className="flex flex-wrap gap-2"
            >
              <Button
                type="button"
                variant={mode === 'webcam' ? 'default' : 'outline'}
                aria-pressed={mode === 'webcam'}
                className="min-h-11"
                onClick={() => handleSwitchMode('webcam')}
              >
                <Camera aria-hidden="true" size={16} />
                Webcam
              </Button>
              <Button
                type="button"
                variant={mode === 'video' ? 'default' : 'outline'}
                aria-pressed={mode === 'video'}
                className="min-h-11"
                onClick={() => handleSwitchMode('video')}
              >
                <Film aria-hidden="true" size={16} />
                Video file
              </Button>
            </div>
          </div>

          {mode === 'webcam' && !isSecureContext && (
            <p
              role="status"
              className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning-bg px-3 py-2 text-sm text-warning"
            >
              <TriangleAlert
                aria-hidden="true"
                size={16}
                className="mt-0.5 shrink-0"
              />
              <span>
                Camera blocked on plain HTTP: use the HTTPS tunnel URL (or
                localhost) to access your webcam.
              </span>
            </p>
          )}

          {mode === 'webcam' &&
            webcamErrorMessage &&
            !(webcamError === 'not-secure' && !isSecureContext) && (
              <p
                role="alert"
                className="rounded-lg border border-critical/40 bg-critical-bg px-3 py-2 text-sm font-medium text-critical"
              >
                {webcamErrorMessage}
              </p>
            )}

          {mode === 'webcam' && (
            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                variant="outline"
                className="min-h-11"
                aria-pressed={facing === 'environment'}
                onClick={handleToggleFacing}
              >
                <RefreshCw aria-hidden="true" size={16} />
                {facing === 'user'
                  ? 'Camera: Front (switch to Back)'
                  : 'Camera: Back (switch to Front)'}
              </Button>
            </div>
          )}

          {mode === 'video' && (
            <div className="space-y-3 rounded-lg border bg-muted/30 p-3">
              <div className="space-y-1.5">
                <label
                  htmlFor="monitor-video-file"
                  className="text-sm font-medium"
                >
                  Select video file
                </label>
                <input
                  id="monitor-video-file"
                  type="file"
                  accept="video/*"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) {
                      setStreaming(false);
                      stopStreamer();
                      clearStreamErrors();
                      loadFile(file);
                    }
                  }}
                  className="block w-full text-sm file:mr-3 file:min-h-11 file:rounded-md file:border file:border-border file:bg-card file:px-3 file:py-2 file:text-sm file:font-medium"
                />
              </div>

              {videoLoaded && (
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    className="min-h-11"
                    onClick={videoPlaying ? pauseVideo : playVideo}
                  >
                    {videoPlaying ? (
                      <>
                        <Pause aria-hidden="true" size={16} />
                        Pause video
                      </>
                    ) : (
                      <>
                        <Play aria-hidden="true" size={16} />
                        Play video
                      </>
                    )}
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    className="min-h-11"
                    aria-pressed={videoLoop}
                    onClick={toggleLoop}
                  >
                    <Repeat aria-hidden="true" size={16} />
                    Loop: {videoLoop ? 'ON' : 'OFF'}
                  </Button>
                </div>
              )}
            </div>
          )}

          <StreamErrorBanner selectedSourceId={selectedSourceId} />

          {connectionStatus !== 'connected' && (
            <p role="status" className="text-xs text-warning">
              Socket is reconnecting — frames will resume once connected.
            </p>
          )}

          <div className="flex flex-wrap items-center gap-2 pt-1">
            <Button
              type="button"
              className="min-h-11"
              disabled={
                streaming ||
                !selectedSource ||
                (mode === 'video' && !videoLoaded)
              }
              onClick={handleStart}
            >
              <Play aria-hidden="true" size={16} />
              Start streaming
            </Button>
            <Button
              type="button"
              variant="destructive"
              className="min-h-11"
              disabled={!streaming && !webcamActive && !videoPlaying}
              onClick={handleStop}
            >
              <Square aria-hidden="true" size={16} />
              Stop streaming
            </Button>
          </div>
        </section>

        <div className="space-y-4">
          <section className="glass space-y-3" aria-label="Live video feed">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="m-0">Live preview</h2>
              <span className="text-xs text-muted-foreground">
                {streaming ? 'Streaming active' : 'Stream idle'}
              </span>
            </div>

            <div
              key={mode}
              className="relative mx-auto w-full overflow-hidden rounded-lg bg-black"
            >
              <video
                ref={attachVideoRef}
                autoPlay
                playsInline
                muted
                aria-label="Monitor camera preview"
                className="aspect-video w-full object-contain"
              />
              <ConnectedDetectionOverlay videoRef={activeVideoRef} />
            </div>
          </section>

          <ConnectedMonitorHud />
          <ZoneStatusCard zone={activeZone} />
        </div>
      </div>
    </section>
  );
}
