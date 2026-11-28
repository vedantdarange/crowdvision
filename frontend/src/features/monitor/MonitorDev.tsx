/**
 * Dev-only test harness for the monitor hooks.
 * Route: /police/monitor-dev (hidden in production builds).
 * Exercises useWebcam, useVideoFile, useFrameStreamer, DetectionOverlay, and MonitorHud
 * against the mock server's synthetic frame:result.
 */
import { useCallback, useState } from 'react';
import { useConfig } from '@/features/zones/api';
import { useWebcam } from './useWebcam';
import { useVideoFile } from './useVideoFile';
import { useFrameStreamer } from './useFrameStreamer';
import { DetectionOverlay } from './DetectionOverlay';
import { MonitorHud } from './MonitorHud';

type Mode = 'webcam' | 'video' | null;

export function MonitorDev() {
  const [mode, setMode] = useState<Mode>(null);
  const [sourceId, setSourceId] = useState(1);
  const [streaming, setStreaming] = useState(false);
  const [videoEl, setVideoEl] = useState<HTMLVideoElement | null>(null);

  const { data: config } = useConfig();

  const webcam = useWebcam('user');
  const videoFile = useVideoFile();

  const attachVideoRef = useCallback(
    (node: HTMLVideoElement | null) => {
      if (mode === 'webcam') {
        webcam.videoRef.current = node;
      } else if (mode === 'video') {
        videoFile.videoRef.current = node;
      }
      setVideoEl(node);
    },
    [mode, webcam.videoRef, videoFile.videoRef],
  );

  const streamer = useFrameStreamer({
    video: videoEl,
    sourceId,
    enabled: streaming,
    isWebcam: mode === 'webcam',
    config,
    resetRequested: videoFile.loopRestarted,
    onResetConsumed: videoFile.clearLoopRestart,
  });

  const activeVideoRef =
    mode === 'webcam' ? webcam.videoRef : videoFile.videoRef;

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4">
      <h1 className="text-xl font-bold">Monitor Dev Harness</h1>
      <p className="text-sm text-muted-foreground">
        Dev-only page. Exercise camera and video hooks with the mock server.
      </p>

      <div className="flex items-center gap-2">
        <label htmlFor="source-id" className="text-sm font-medium">
          Source ID
        </label>
        <input
          id="source-id"
          type="number"
          min={1}
          value={sourceId}
          onChange={(e) => setSourceId(Math.max(1, Number(e.target.value)))}
          className="w-24 rounded border bg-background px-2 py-1 text-sm"
        />
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => {
            setStreaming(false);
            videoFile.unload();
            setMode('webcam');
            webcam.start();
          }}
          className="rounded bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground"
        >
          Webcam
        </button>
        <button
          type="button"
          onClick={() => {
            setStreaming(false);
            webcam.stop();
            setMode('video');
          }}
          className="rounded bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground"
        >
          Video File
        </button>
        {mode && (
          <button
            type="button"
            onClick={() => {
              setStreaming(false);
              streamer.stop();
              webcam.stop();
              videoFile.unload();
              setMode(null);
            }}
            className="rounded bg-secondary px-3 py-1.5 text-sm font-medium text-secondary-foreground"
          >
            Reset
          </button>
        )}
      </div>

      {webcam.errorMessage && (
        <p role="alert" className="text-sm font-medium text-critical">
          {webcam.errorMessage}
        </p>
      )}
      {streamer.state === 'in-use' && (
        <p role="alert" className="text-sm font-medium text-warning">
          This source is already being streamed elsewhere
        </p>
      )}

      {mode === 'video' && (
        <div className="flex flex-wrap items-center gap-2">
          <label className="text-sm font-medium" htmlFor="video-file-input">
            Select video
          </label>
          <input
            id="video-file-input"
            type="file"
            accept="video/*"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) videoFile.loadFile(file);
            }}
            className="text-sm"
          />
          {videoFile.loaded && (
            <>
              <button
                type="button"
                onClick={videoFile.playing ? videoFile.pause : videoFile.play}
                className="rounded bg-secondary px-3 py-1.5 text-xs font-medium text-secondary-foreground"
              >
                {videoFile.playing ? 'Pause' : 'Play'}
              </button>
              <button
                type="button"
                onClick={videoFile.toggleLoop}
                className="rounded bg-secondary px-3 py-1.5 text-xs font-medium text-secondary-foreground"
              >
                Loop: {videoFile.loop ? 'ON' : 'OFF'}
              </button>
            </>
          )}
        </div>
      )}

      {mode && (
        <div
          key={mode}
          className="relative mx-auto w-full max-w-[640px] overflow-hidden rounded-lg bg-black"
        >
          <video
            ref={attachVideoRef}
            autoPlay
            playsInline
            muted
            className="aspect-video w-full object-contain"
          />
          <DetectionOverlay
            videoRef={activeVideoRef}
            lastResult={streamer.lastResult}
            resultTimestamp={streamer.lastResultAt}
          />
        </div>
      )}

      {mode && (
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => setStreaming(true)}
            disabled={streaming || streamer.state === 'in-use'}
            className="rounded bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground disabled:opacity-50"
          >
            Start Streaming
          </button>
          <button
            type="button"
            onClick={() => {
              setStreaming(false);
              streamer.stop();
            }}
            disabled={!streaming}
            className="rounded bg-destructive px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
          >
            Stop Streaming
          </button>
        </div>
      )}

      <MonitorHud
        lastResult={streamer.lastResult}
        fps={streamer.fps}
        latencyMs={streamer.latencyMs}
        drops={streamer.drops}
      />

      <details className="text-xs">
        <summary>Debug state</summary>
        <pre className="mt-1 overflow-auto rounded bg-muted p-2">
          {JSON.stringify(
            {
              mode,
              sourceId,
              streaming,
              streamerState: streamer.state,
              webcamActive: webcam.active,
              videoLoaded: videoFile.loaded,
              videoPlaying: videoFile.playing,
              loop: videoFile.loop,
              loopRestarted: videoFile.loopRestarted,
            },
            null,
            2,
          )}
        </pre>
      </details>
    </div>
  );
}
