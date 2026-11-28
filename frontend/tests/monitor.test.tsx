import { StrictMode, type ReactNode } from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, renderHook, act, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { axe } from 'vitest-axe';
import type { FrameResult, RuntimeConfig } from '@contract/types';
import configFixture from '../../contract/examples/config.json';
import frameResultFixture from '../../contract/examples/frame_result.json';
import { computeContainRect, mapBoxes } from '@/features/monitor/overlay';

const mockEmit = vi.fn();
const mockOn = vi.fn();
const mockOff = vi.fn();

vi.mock('@/lib/socket', () => ({
  socket: {
    emit: (...args: unknown[]) => mockEmit(...args),
    on: (...args: unknown[]) => mockOn(...args),
    off: (...args: unknown[]) => mockOff(...args),
  },
}));

import { useFrameStreamer } from '@/features/monitor/useFrameStreamer';
import { useWebcam } from '@/features/monitor/useWebcam';
import { useVideoFile } from '@/features/monitor/useVideoFile';
import { DetectionOverlay } from '@/features/monitor/DetectionOverlay';
import { MonitorHud } from '@/features/monitor/MonitorHud';

/* ------------------------------------------------------------------ */
/*  Pure overlay math tests                                            */
/* ------------------------------------------------------------------ */

describe('computeContainRect', () => {
  it('16:9 video in a 4:3 container -> letterboxed (bars top/bottom)', () => {
    const r = computeContainRect(1920, 1080, 800, 600);
    expect(r.displayWidth).toBe(800);
    expect(r.displayHeight).toBeCloseTo(450, 0);
    expect(r.offsetX).toBe(0);
    expect(r.offsetY).toBeCloseTo(75, 0);
  });

  it('4:3 video in a 16:9 container -> pillarboxed (bars left/right)', () => {
    const r = computeContainRect(640, 480, 1280, 720);
    expect(r.displayHeight).toBe(720);
    expect(r.displayWidth).toBeCloseTo(960, 0);
    expect(r.offsetX).toBeCloseTo(160, 0);
    expect(r.offsetY).toBe(0);
  });

  it('zero dimensions -> zero rect', () => {
    const r = computeContainRect(0, 0, 100, 100);
    expect(r.displayWidth).toBe(0);
    expect(r.displayHeight).toBe(0);
  });
});

describe('mapBoxes', () => {
  it('maps normalised boxes at dpr=1', () => {
    const display = {
      offsetX: 10,
      offsetY: 20,
      displayWidth: 200,
      displayHeight: 100,
    };
    const boxes: [number, number, number, number, number][] = [
      [0.1, 0.2, 0.5, 0.8, 0.95],
    ];
    const result = mapBoxes(boxes, display, 1);
    expect(result).toHaveLength(1);
    const b = result[0]!;
    expect(b.x).toBeCloseTo(30);
    expect(b.y).toBeCloseTo(40);
    expect(b.w).toBeCloseTo(80);
    expect(b.h).toBeCloseTo(60);
    expect(b.conf).toBe(0.95);
  });

  it('accounts for devicePixelRatio = 2', () => {
    const display = {
      offsetX: 10,
      offsetY: 20,
      displayWidth: 200,
      displayHeight: 100,
    };
    const boxes: [number, number, number, number, number][] = [
      [0.0, 0.0, 1.0, 1.0, 0.9],
    ];
    const result = mapBoxes(boxes, display, 2);
    const b = result[0]!;
    expect(b.x).toBeCloseTo(20);
    expect(b.y).toBeCloseTo(40);
    expect(b.w).toBeCloseTo(400);
    expect(b.h).toBeCloseTo(200);
  });

  it('letterboxed 16:9 video in 4:3 container at dpr=2', () => {
    const display = computeContainRect(1920, 1080, 800, 600);
    const boxes: [number, number, number, number, number][] = [
      [0.5, 0.5, 0.6, 0.6, 0.85],
    ];
    const result = mapBoxes(boxes, display, 2);
    const b = result[0]!;
    expect(b.x).toBeCloseTo(800);
    expect(b.y).toBeCloseTo(600);
    expect(b.w).toBeCloseTo(160);
    expect(b.h).toBeCloseTo(90);
  });
});

/* ------------------------------------------------------------------ */
/*  Test helpers for frame streamer                                    */
/* ------------------------------------------------------------------ */

function createMockVideo(width = 640, height = 480, readyState = 1) {
  const listeners = new Map<string, Set<EventListener>>();
  return {
    videoWidth: width,
    videoHeight: height,
    readyState,
    addEventListener: vi.fn((type: string, fn: EventListener) => {
      let set = listeners.get(type);
      if (!set) {
        set = new Set();
        listeners.set(type, set);
      }
      set.add(fn);
    }),
    removeEventListener: vi.fn((type: string, fn: EventListener) => {
      listeners.get(type)?.delete(fn);
    }),
    dispatch(type: string) {
      for (const fn of [...(listeners.get(type) ?? [])]) {
        fn(new Event(type));
      }
    },
  } as unknown as HTMLVideoElement & { dispatch: (type: string) => void };
}

function setupCanvasMock({ deferToBlob = false } = {}) {
  const drawImage = vi.fn();
  const mockCtx = { drawImage };
  const toBlobCalls: {
    cb: BlobCallback;
    type?: string;
    quality?: number;
  }[] = [];
  const origCreateElement = document.createElement.bind(document);
  vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
    if (tag === 'canvas') {
      const canvas = origCreateElement('canvas') as HTMLCanvasElement;
      vi.spyOn(canvas, 'getContext').mockReturnValue(
        mockCtx as unknown as CanvasRenderingContext2D,
      );
      vi.spyOn(canvas, 'toBlob').mockImplementation(
        (cb: BlobCallback, type?: string, quality?: number) => {
          expect(type).toBe('image/jpeg');
          toBlobCalls.push({ cb, type, quality });
          if (!deferToBlob) {
            const jpegHeader = new Uint8Array([
              0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10,
            ]);
            cb(new Blob([jpegHeader], { type: 'image/jpeg' }));
          }
        },
      );
      return canvas;
    }
    return origCreateElement(tag);
  });
  return {
    drawImage,
    toBlobCalls,
    flushToBlob() {
      const item = toBlobCalls.shift();
      if (!item) return;
      const jpegHeader = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10]);
      item.cb(new Blob([jpegHeader], { type: 'image/jpeg' }));
    },
  };
}

function getResultHandler(): (result: FrameResult) => void {
  const call = mockOn.mock.calls.find((c) => c[0] === 'frame:result');
  if (!call) throw new Error('frame:result handler not registered');
  return call[1] as (result: FrameResult) => void;
}

function makeOkResult(seq: number, sourceId = 1): FrameResult {
  return {
    ...(frameResultFixture as FrameResult),
    source_id: sourceId,
    seq,
    count: seq + 1,
    smoothed_count: seq + 1,
  };
}

const defaultConfig = { target_fps: 3, frame_width: 640, jpeg_quality: 0.7 };

/* ------------------------------------------------------------------ */
/*  useFrameStreamer tests (fake timers + mock socket)                 */
/* ------------------------------------------------------------------ */

describe('useFrameStreamer', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: false });
    mockEmit.mockClear();
    mockOn.mockClear();
    mockOff.mockClear();
  });

  afterEach(() => {
    Object.defineProperty(document, 'hidden', {
      value: false,
      writable: true,
      configurable: true,
    });
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('sends the first frame with reset: true and seq: 1', async () => {
    setupCanvasMock();
    const video = createMockVideo();

    const { unmount } = renderHook(() =>
      useFrameStreamer({
        video,
        sourceId: 1,
        enabled: true,
        config: defaultConfig,
      }),
    );

    await vi.advanceTimersByTimeAsync(10);

    expect(mockEmit).toHaveBeenCalledTimes(1);
    const payload = mockEmit.mock.calls[0]![1] as Record<string, unknown>;
    expect(payload.source_id).toBe(1);
    expect(payload.seq).toBe(1);
    expect(payload.reset).toBe(true);
    expect(payload.width).toBe(640);
    expect(payload.height).toBe(480);
    expect(payload.image).toBeInstanceOf(ArrayBuffer);
    unmount();
  });

  it('waits for loadedmetadata before reading video dimensions', async () => {
    setupCanvasMock();
    const video = createMockVideo(0, 0, 0);

    const { unmount } = renderHook(() =>
      useFrameStreamer({
        video,
        sourceId: 1,
        enabled: true,
        config: defaultConfig,
      }),
    );

    await vi.advanceTimersByTimeAsync(1000);
    expect(mockEmit).toHaveBeenCalledTimes(0);

    // Metadata arrives with 16:9 video
    act(() => {
      Object.assign(video, {
        videoWidth: 1280,
        videoHeight: 720,
        readyState: 1,
      });
      video.dispatch('loadedmetadata');
    });

    await vi.advanceTimersByTimeAsync(10);
    expect(mockEmit).toHaveBeenCalledTimes(1);
    const payload = mockEmit.mock.calls[0]![1] as Record<string, unknown>;
    expect(payload.width).toBe(640);
    expect(payload.height).toBe(360);
    unmount();
  });

  it('reads /config via QueryClient when config prop is omitted', async () => {
    const { toBlobCalls } = setupCanvasMock();
    const video = createMockVideo(1280, 720);
    const customConfig: RuntimeConfig = {
      ...(configFixture as RuntimeConfig),
      target_fps: 2,
      frame_width: 480,
      jpeg_quality: 0.65,
    };
    const fetchSpy = vi
      .fn()
      .mockResolvedValue(Response.json({ data: customConfig }));
    vi.stubGlobal('fetch', fetchSpy);

    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );

    const { unmount } = renderHook(
      () => useFrameStreamer({ video, sourceId: 1, enabled: true }),
      { wrapper },
    );

    await vi.advanceTimersByTimeAsync(50);
    expect(fetchSpy).toHaveBeenCalled();
    expect(mockEmit).toHaveBeenCalled();
    const lastCall = mockEmit.mock.calls.at(-1)![1] as Record<string, unknown>;
    expect(lastCall.width).toBe(480);
    expect(lastCall.height).toBe(270);
    expect(toBlobCalls.at(-1)?.quality).toBe(0.65);
    unmount();
  });

  it('keeps at most one frame in flight (including while toBlob is pending)', async () => {
    const canvas = setupCanvasMock({ deferToBlob: true });
    const video = createMockVideo();

    const { unmount } = renderHook(() =>
      useFrameStreamer({
        video,
        sourceId: 1,
        enabled: true,
        config: { ...defaultConfig, target_fps: 10 },
      }),
    );

    // Trigger first frame capture (toBlob has not resolved yet)
    await vi.advanceTimersByTimeAsync(500);
    expect(canvas.toBlobCalls).toHaveLength(1);
    expect(mockEmit).toHaveBeenCalledTimes(0);

    // Flush encoding -> 1 frame emitted, still awaiting frame:result
    await act(async () => {
      canvas.flushToBlob();
      await Promise.resolve();
    });
    expect(mockEmit).toHaveBeenCalledTimes(1);

    // Even after 1000 ms with no result, no second capture or emit occurs
    await vi.advanceTimersByTimeAsync(1000);
    expect(canvas.toBlobCalls).toHaveLength(0);
    expect(mockEmit).toHaveBeenCalledTimes(1);
    unmount();
  });

  it('sends next frame only after matching frame:result', async () => {
    setupCanvasMock();
    const video = createMockVideo();

    renderHook(() =>
      useFrameStreamer({
        video,
        sourceId: 1,
        enabled: true,
        config: { ...defaultConfig, target_fps: 10 },
      }),
    );

    await vi.advanceTimersByTimeAsync(10);
    expect(mockEmit).toHaveBeenCalledTimes(1);

    const handler = getResultHandler();
    // Wrong source_id or wrong seq should be ignored
    act(() => handler(makeOkResult(1, 999)));
    act(() => handler(makeOkResult(99, 1)));
    await vi.advanceTimersByTimeAsync(300);
    expect(mockEmit).toHaveBeenCalledTimes(1);

    // Matching result unlocks the next frame after the interval
    act(() => handler(makeOkResult(1, 1)));
    await vi.advanceTimersByTimeAsync(150);
    expect(mockEmit).toHaveBeenCalledTimes(2);
    expect((mockEmit.mock.calls[1]![1] as Record<string, unknown>).seq).toBe(2);
    expect(
      (mockEmit.mock.calls[1]![1] as Record<string, unknown>).reset,
    ).toBeUndefined();
  });

  it('clears in-flight after 2s timeout and counts a drop', async () => {
    setupCanvasMock();
    const video = createMockVideo();

    const { result } = renderHook(() =>
      useFrameStreamer({
        video,
        sourceId: 1,
        enabled: true,
        config: { ...defaultConfig, target_fps: 10 },
      }),
    );

    await vi.advanceTimersByTimeAsync(10);
    expect(mockEmit).toHaveBeenCalledTimes(1);

    // Before 2 s timeout: still 0 drops and 1 frame
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1980);
    });
    expect(result.current.drops).toBe(0);
    expect(mockEmit).toHaveBeenCalledTimes(1);

    // Cross 2 s timeout -> drop counted and second frame allowed
    await act(async () => {
      await vi.advanceTimersByTimeAsync(50);
    });
    expect(result.current.drops).toBe(1);
    expect(mockEmit).toHaveBeenCalledTimes(2);
  });

  it('respects target_fps interval strictly', async () => {
    setupCanvasMock();
    const video = createMockVideo();

    renderHook(() =>
      useFrameStreamer({
        video,
        sourceId: 1,
        enabled: true,
        config: { ...defaultConfig, target_fps: 2 },
      }),
    );

    await vi.advanceTimersByTimeAsync(10);
    expect(mockEmit).toHaveBeenCalledTimes(1);

    const handler = getResultHandler();
    act(() => handler(makeOkResult(1)));

    // 489ms total elapsed (< 500ms interval) -> no second frame yet
    await vi.advanceTimersByTimeAsync(479);
    expect(mockEmit).toHaveBeenCalledTimes(1);

    // Cross 500ms -> second frame sent
    await vi.advanceTimersByTimeAsync(30);
    expect(mockEmit).toHaveBeenCalledTimes(2);
  });

  it('seq increments across frames', async () => {
    setupCanvasMock();
    const video = createMockVideo();

    renderHook(() =>
      useFrameStreamer({
        video,
        sourceId: 1,
        enabled: true,
        config: { ...defaultConfig, target_fps: 10 },
      }),
    );

    const handler = getResultHandler();

    for (let i = 1; i <= 4; i++) {
      await vi.advanceTimersByTimeAsync(120);
      expect(
        (mockEmit.mock.calls[i - 1]![1] as Record<string, unknown>).seq,
      ).toBe(i);
      act(() => handler(makeOkResult(i)));
    }
  });

  it('sends reset: true after video loop restart', async () => {
    setupCanvasMock();
    const video = createMockVideo();
    const onResetConsumed = vi.fn();

    const { rerender } = renderHook(
      ({ resetRequested }: { resetRequested: boolean }) =>
        useFrameStreamer({
          video,
          sourceId: 1,
          enabled: true,
          config: { ...defaultConfig, target_fps: 10 },
          resetRequested,
          onResetConsumed,
        }),
      { initialProps: { resetRequested: false } },
    );

    const handler = getResultHandler();

    // Frame 1: initial reset = true
    await vi.advanceTimersByTimeAsync(10);
    expect((mockEmit.mock.calls[0]![1] as Record<string, unknown>).reset).toBe(
      true,
    );
    act(() => handler(makeOkResult(1)));

    // Frame 2: reset = undefined
    await vi.advanceTimersByTimeAsync(150);
    expect(
      (mockEmit.mock.calls[1]![1] as Record<string, unknown>).reset,
    ).toBeUndefined();
    act(() => handler(makeOkResult(2)));

    // Loop restart detected -> resetRequested flips to true
    rerender({ resetRequested: true });
    expect(onResetConsumed).toHaveBeenCalledTimes(1);
    rerender({ resetRequested: false });

    // Frame 3: reset = true
    await vi.advanceTimersByTimeAsync(150);
    const frame3 = mockEmit.mock.calls[2]![1] as Record<string, unknown>;
    expect(frame3.seq).toBe(3);
    expect(frame3.reset).toBe(true);
    act(() => handler(makeOkResult(3)));

    // Frame 4: back to undefined
    await vi.advanceTimersByTimeAsync(150);
    const frame4 = mockEmit.mock.calls[3]![1] as Record<string, unknown>;
    expect(frame4.seq).toBe(4);
    expect(frame4.reset).toBeUndefined();
  });

  it('SOURCE_IN_USE stops the streamer and does not retry', async () => {
    setupCanvasMock();
    const video = createMockVideo();

    const { result } = renderHook(() =>
      useFrameStreamer({
        video,
        sourceId: 1,
        enabled: true,
        config: { ...defaultConfig, target_fps: 10 },
      }),
    );

    await vi.advanceTimersByTimeAsync(10);
    expect(mockEmit).toHaveBeenCalledTimes(1);

    const handler = getResultHandler();
    act(() =>
      handler({
        source_id: 1,
        seq: 1,
        ok: false,
        error: 'SOURCE_IN_USE',
        count: 0,
        boxes: [],
        infer_ms: 0,
        smoothed_count: null,
        density: null,
        level: null,
      }),
    );

    expect(result.current.state).toBe('in-use');

    await vi.advanceTimersByTimeAsync(10000);
    expect(mockEmit).toHaveBeenCalledTimes(1);
  });

  it('pauses webcam streaming when document is hidden and resumes on visibilitychange', async () => {
    setupCanvasMock();
    const video = createMockVideo();

    renderHook(() =>
      useFrameStreamer({
        video,
        sourceId: 1,
        enabled: true,
        isWebcam: true,
        config: { ...defaultConfig, target_fps: 10 },
      }),
    );

    await vi.advanceTimersByTimeAsync(10);
    expect(mockEmit).toHaveBeenCalledTimes(1);

    const handler = getResultHandler();
    act(() => handler(makeOkResult(1)));

    // Hide tab
    Object.defineProperty(document, 'hidden', {
      value: true,
      writable: true,
      configurable: true,
    });
    const countBefore = mockEmit.mock.calls.length;
    await vi.advanceTimersByTimeAsync(1000);
    expect(mockEmit.mock.calls.length).toBe(countBefore);

    // Show tab and fire visibilitychange
    Object.defineProperty(document, 'hidden', {
      value: false,
      writable: true,
      configurable: true,
    });
    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'));
      await vi.advanceTimersByTimeAsync(20);
    });
    expect(mockEmit.mock.calls.length).toBeGreaterThan(countBefore);
  });

  it('keeps streaming video file source even when document is hidden', async () => {
    setupCanvasMock();
    const video = createMockVideo();

    renderHook(() =>
      useFrameStreamer({
        video,
        sourceId: 2,
        enabled: true,
        isWebcam: false,
        config: { ...defaultConfig, target_fps: 10 },
      }),
    );

    await vi.advanceTimersByTimeAsync(10);
    expect(mockEmit).toHaveBeenCalledTimes(1);

    Object.defineProperty(document, 'hidden', {
      value: true,
      writable: true,
      configurable: true,
    });

    const handler = getResultHandler();
    act(() => handler(makeOkResult(1, 2)));

    await vi.advanceTimersByTimeAsync(200);
    expect(mockEmit).toHaveBeenCalledTimes(2);
  });

  it('cleanup removes socket listener and clears all timers (including 2s timeout)', async () => {
    setupCanvasMock();
    const video = createMockVideo();

    const { unmount } = renderHook(() =>
      useFrameStreamer({
        video,
        sourceId: 1,
        enabled: true,
        config: defaultConfig,
      }),
    );

    await vi.advanceTimersByTimeAsync(10);
    expect(mockEmit).toHaveBeenCalledTimes(1);

    unmount();
    expect(mockOff).toHaveBeenCalledWith('frame:result', expect.any(Function));

    // Advance past 2s timeout and normal interval -> nothing happens
    await vi.advanceTimersByTimeAsync(5000);
    expect(mockEmit).toHaveBeenCalledTimes(1);
  });

  it('uses JPEG mime type with configured quality, never PNG or WebP', async () => {
    const { drawImage, toBlobCalls } = setupCanvasMock();
    const video = createMockVideo();

    const { unmount } = renderHook(() =>
      useFrameStreamer({
        video,
        sourceId: 1,
        enabled: true,
        config: { target_fps: 3, frame_width: 640, jpeg_quality: 0.72 },
      }),
    );

    await vi.advanceTimersByTimeAsync(10);
    expect(drawImage).toHaveBeenCalled();
    expect(toBlobCalls[0]?.type).toBe('image/jpeg');
    expect(toBlobCalls[0]?.quality).toBe(0.72);
    unmount();
  });
});

/* ------------------------------------------------------------------ */
/*  useWebcam tests                                                    */
/* ------------------------------------------------------------------ */

describe('useWebcam', () => {
  afterEach(() => {
    Object.defineProperty(window, 'isSecureContext', {
      value: true,
      writable: true,
      configurable: true,
    });
    vi.restoreAllMocks();
  });

  it('reports not-secure error when not in secure context', () => {
    Object.defineProperty(window, 'isSecureContext', {
      value: false,
      writable: true,
      configurable: true,
    });

    const { result } = renderHook(() => useWebcam('user'));
    act(() => result.current.start());

    expect(result.current.error).toBe('not-secure');
    expect(result.current.errorMessage).toBe(
      'Camera needs HTTPS (use the tunnel URL)',
    );
    expect(result.current.active).toBe(false);
  });

  it('maps NotAllowedError, NotFoundError, and NotReadableError', async () => {
    Object.defineProperty(window, 'isSecureContext', {
      value: true,
      writable: true,
      configurable: true,
    });

    for (const [domName, expectedError] of [
      ['NotAllowedError', 'not-allowed'],
      ['NotFoundError', 'not-found'],
      ['NotReadableError', 'in-use'],
    ] as const) {
      Object.defineProperty(navigator, 'mediaDevices', {
        value: {
          getUserMedia: vi
            .fn()
            .mockRejectedValue(new DOMException('fail', domName)),
        },
        writable: true,
        configurable: true,
      });

      const { result, unmount } = renderHook(() => useWebcam('user'));
      await act(async () => {
        result.current.start();
      });

      expect(result.current.error).toBe(expectedError);
      expect(result.current.errorMessage).toBeTruthy();
      unmount();
    }
  });

  it('stop and unmount always release tracks (even under StrictMode)', async () => {
    Object.defineProperty(window, 'isSecureContext', {
      value: true,
      writable: true,
      configurable: true,
    });
    const mockTrack = { stop: vi.fn(), kind: 'video' };
    const mockStream = {
      getTracks: () => [mockTrack],
    } as unknown as MediaStream;
    const getUserMedia = vi.fn().mockResolvedValue(mockStream);
    Object.defineProperty(navigator, 'mediaDevices', {
      value: { getUserMedia },
      writable: true,
      configurable: true,
    });

    const wrapper = ({ children }: { children: ReactNode }) => (
      <StrictMode>{children}</StrictMode>
    );
    const { result, unmount } = renderHook(() => useWebcam('environment'), {
      wrapper,
    });

    await act(async () => {
      result.current.start();
    });
    expect(getUserMedia).toHaveBeenCalledWith({
      video: { facingMode: 'environment', width: { ideal: 1280 } },
      audio: false,
    });
    expect(result.current.active).toBe(true);

    act(() => result.current.stop());
    expect(mockTrack.stop).toHaveBeenCalledTimes(1);
    expect(result.current.active).toBe(false);

    // Start again and unmount without calling stop() -> unmount stops tracks
    await act(async () => {
      result.current.start();
    });
    unmount();
    expect(mockTrack.stop).toHaveBeenCalledTimes(2);
  });

  it('stops tracks immediately if getUserMedia resolves after unmount', async () => {
    Object.defineProperty(window, 'isSecureContext', {
      value: true,
      writable: true,
      configurable: true,
    });
    const mockTrack = { stop: vi.fn(), kind: 'video' };
    const mockStream = {
      getTracks: () => [mockTrack],
    } as unknown as MediaStream;

    let resolveStream!: (s: MediaStream) => void;
    Object.defineProperty(navigator, 'mediaDevices', {
      value: {
        getUserMedia: vi.fn(
          () =>
            new Promise<MediaStream>((resolve) => {
              resolveStream = resolve;
            }),
        ),
      },
      writable: true,
      configurable: true,
    });

    const { result, unmount } = renderHook(() => useWebcam('user'));
    act(() => result.current.start());

    unmount();
    await act(async () => {
      resolveStream(mockStream);
    });

    expect(mockTrack.stop).toHaveBeenCalledTimes(1);
  });
});

/* ------------------------------------------------------------------ */
/*  useVideoFile tests                                                 */
/* ------------------------------------------------------------------ */

describe('useVideoFile', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('revokes object URL on unload and on unmount', () => {
    const revokeUrl = vi
      .spyOn(URL, 'revokeObjectURL')
      .mockImplementation(() => {});
    const createUrl = vi
      .spyOn(URL, 'createObjectURL')
      .mockReturnValueOnce('blob:first')
      .mockReturnValueOnce('blob:second');

    const { result, unmount } = renderHook(() => useVideoFile());

    const file1 = new File(['a'], 'a.mp4', { type: 'video/mp4' });
    act(() => result.current.loadFile(file1));
    expect(createUrl).toHaveBeenCalledTimes(1);

    act(() => result.current.unload());
    expect(revokeUrl).toHaveBeenCalledWith('blob:first');

    const file2 = new File(['b'], 'b.mp4', { type: 'video/mp4' });
    act(() => result.current.loadFile(file2));
    unmount();
    expect(revokeUrl).toHaveBeenCalledWith('blob:second');
  });

  it('detects loop restart when currentTime decreases and clears on consume', () => {
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:loop');
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});

    const videoEl = document.createElement('video');
    let time = 0;
    Object.defineProperty(videoEl, 'currentTime', {
      get: () => time,
      configurable: true,
    });

    const { result, rerender } = renderHook(() => useVideoFile());
    result.current.videoRef.current = videoEl;

    act(() => {
      result.current.loadFile(new File(['v'], 'v.mp4', { type: 'video/mp4' }));
    });
    rerender();

    act(() => {
      time = 1.2;
      videoEl.dispatchEvent(new Event('timeupdate'));
      time = 4.8;
      videoEl.dispatchEvent(new Event('timeupdate'));
    });
    expect(result.current.loopRestarted).toBe(false);

    // Video loops back to start
    act(() => {
      time = 0.05;
      videoEl.dispatchEvent(new Event('timeupdate'));
    });
    expect(result.current.loopRestarted).toBe(true);

    act(() => result.current.clearLoopRestart());
    expect(result.current.loopRestarted).toBe(false);
  });
});

/* ------------------------------------------------------------------ */
/*  MonitorHud & DetectionOverlay component tests                      */
/* ------------------------------------------------------------------ */

describe('MonitorHud', () => {
  it('shows NO_DATA and dashes when no result yet', async () => {
    const view = render(
      <MonitorHud
        lastResult={null}
        fps={0}
        latencyMs={{ p50: 0, p95: 0 }}
        drops={0}
      />,
    );
    expect(screen.getByText('No data')).toBeVisible();
    expect(screen.getByText('No data yet')).toBeVisible();
    expect(screen.getByText('Zone smoothed')).toBeVisible();
    expect(screen.getByText('Zone density')).toBeVisible();
    expect(screen.getByText('Zone level')).toBeVisible();
    expect(
      (
        await axe(view.container, {
          rules: { 'color-contrast': { enabled: false } },
        })
      ).violations,
    ).toEqual([]);
  });

  it('displays source count, zone metrics, and quiet warning chip on DETECTOR_BUSY', () => {
    const { rerender } = render(
      <MonitorHud
        lastResult={frameResultFixture as FrameResult}
        fps={2.9}
        latencyMs={{ p50: 42, p95: 80 }}
        drops={1}
      />,
    );
    expect(screen.getByText('Safe')).toBeVisible();
    expect(screen.getByText('2.9')).toBeVisible();
    expect(screen.getByText(/p50: 42 ms · p95: 80 ms/)).toBeVisible();

    rerender(
      <MonitorHud
        lastResult={{
          source_id: 1,
          seq: 2,
          ok: false,
          error: 'DETECTOR_BUSY',
          count: 0,
          boxes: [],
          infer_ms: 0,
          smoothed_count: null,
          density: null,
          level: null,
        }}
        fps={2.5}
        latencyMs={{ p50: 50, p95: 90 }}
        drops={2}
      />,
    );
    expect(screen.getByText('Detector busy')).toBeVisible();
  });
});

describe('DetectionOverlay', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('toggles confidence display and clears canvas after 1s without new results', async () => {
    const clearRect = vi.fn();
    const strokeRect = vi.fn();
    const fillRect = vi.fn();
    const fillText = vi.fn();
    const measureText = vi.fn(() => ({ width: 24 }));
    const mockCtx = {
      clearRect,
      strokeRect,
      fillRect,
      fillText,
      measureText,
      strokeStyle: '',
      fillStyle: '',
      lineWidth: 1,
      font: '',
    };

    const origGetContext = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = vi
      .fn()
      .mockReturnValue(mockCtx) as unknown as typeof origGetContext;

    try {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      const video = document.createElement('video');
      Object.defineProperty(video, 'videoWidth', { value: 640 });
      Object.defineProperty(video, 'videoHeight', { value: 480 });
      vi.spyOn(video, 'getBoundingClientRect').mockReturnValue({
        width: 640,
        height: 480,
        top: 0,
        left: 0,
        right: 640,
        bottom: 480,
        x: 0,
        y: 0,
        toJSON: () => ({}),
      });
      const videoRef = { current: video };

      render(
        <DetectionOverlay
          videoRef={videoRef}
          lastResult={frameResultFixture as FrameResult}
          resultTimestamp={Date.now()}
        />,
      );

      // Confidence hidden by default
      const toggle = screen.getByRole('button', { name: 'Show conf' });
      expect(toggle).toHaveAttribute('aria-pressed', 'false');
      expect(strokeRect).toHaveBeenCalledTimes(2);
      expect(fillText).not.toHaveBeenCalled();

      // Toggle confidence on -> draws confidence labels
      await user.click(toggle);
      expect(toggle).toHaveAttribute('aria-pressed', 'true');
      expect(fillText).toHaveBeenCalled();

      // Advance 1s -> stale overlay clears
      const clearsBefore = clearRect.mock.calls.length;
      await vi.advanceTimersByTimeAsync(1050);
      expect(clearRect.mock.calls.length).toBeGreaterThan(clearsBefore);
    } finally {
      HTMLCanvasElement.prototype.getContext = origGetContext;
    }
  });
});
