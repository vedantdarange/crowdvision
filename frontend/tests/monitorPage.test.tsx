import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  act,
  render,
  renderHook,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { Suspense } from 'react';
import { axe } from 'vitest-axe';
import type {
  FrameResult,
  RuntimeConfig,
  SourceInfo,
  ZoneState,
} from '@contract/types';
import zonesFixture from '../../contract/examples/zones.json';
import sourcesFixture from '../../contract/examples/sources.json';
import configFixture from '../../contract/examples/config.json';
import frameResultFixture from '../../contract/examples/frame_result.json';
import { queryKeys as k } from '@/lib/queryKeys';
import { updatePoliceZone } from '@/features/police/data';
import { useFrameStreamer } from '@/features/monitor/useFrameStreamer';
import {
  claimActiveStream,
  resetStreamSnapshot,
  useMonitorStore,
} from '@/features/monitor/streamStore';

const socketState = vi.hoisted(() => ({
  handlers: new Map<string, Set<(...args: unknown[]) => void>>(),
  emit: vi.fn(),
}));

vi.mock('@/lib/socket', () => ({
  socket: {
    emit: (...args: unknown[]) => socketState.emit(...args),
    on: (event: string, fn: (...args: unknown[]) => void) => {
      let set = socketState.handlers.get(event);
      if (!set) {
        set = new Set();
        socketState.handlers.set(event, set);
      }
      set.add(fn);
    },
    off: (event: string, fn: (...args: unknown[]) => void) => {
      socketState.handlers.get(event)?.delete(fn);
    },
  },
}));

import { MonitorPage } from '@/features/monitor/MonitorPage';

const zones = zonesFixture.data as ZoneState[];
const sources = sourcesFixture.data as SourceInfo[];
const config = configFixture as RuntimeConfig;

function emitSocket(event: string, payload: unknown) {
  for (const fn of [...(socketState.handlers.get(event) ?? [])]) {
    fn(payload);
  }
}

function setupEnvironment({
  initialSources = sources,
  secureContext = true,
  createSourceHandler,
}: {
  initialSources?: SourceInfo[];
  secureContext?: boolean;
  createSourceHandler?: (body: Record<string, unknown>) => Response;
} = {}) {
  const storeSources = [...initialSources];
  const postCalls: Record<string, unknown>[] = [];

  const fetchMock = vi.fn(async (input: string | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method ?? 'GET').toUpperCase();

    if (url.includes('/config')) {
      return Response.json({ data: config });
    }
    if (url.includes('/zones') && method === 'GET') {
      return Response.json({ data: zones });
    }
    if (url.includes('/sources') && method === 'GET') {
      const parsed = new URL(url, 'http://localhost');
      const zid = parsed.searchParams.get('zone_id');
      const filtered = zid
        ? storeSources.filter((s) => s.zone_id === Number(zid))
        : storeSources;
      return Response.json({ data: filtered });
    }
    if (url.includes('/sources') && method === 'POST') {
      const body = JSON.parse(String(init?.body ?? '{}')) as Record<
        string,
        unknown
      >;
      postCalls.push(body);
      if (createSourceHandler) {
        return createSourceHandler(body);
      }
      const created: SourceInfo = {
        id: 200 + storeSources.length,
        zone_id: Number(body.zone_id),
        name: String(body.name),
        kind: body.kind as SourceInfo['kind'],
        coverage_area_m2: 40,
        is_active: true,
        status: 'OFFLINE',
        last_frame_at: null,
        created_at: new Date().toISOString(),
      };
      storeSources.push(created);
      return Response.json({ data: created }, { status: 201 });
    }
    return Response.json({ data: [] });
  });

  vi.stubGlobal('fetch', fetchMock);
  Object.defineProperty(window, 'isSecureContext', {
    value: secureContext,
    writable: true,
    configurable: true,
  });

  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  client.setQueryData(k.zones.list, zones);
  client.setQueryData(k.config, config);

  return { client, fetchMock, postCalls };
}

function setupFakeCanvas() {
  const origCreateElement = document.createElement.bind(document);
  const mockCtx = {
    drawImage: vi.fn(),
    clearRect: vi.fn(),
    strokeRect: vi.fn(),
    fillRect: vi.fn(),
    fillText: vi.fn(),
    measureText: vi.fn(() => ({ width: 24 })),
    strokeStyle: '',
    fillStyle: '',
    lineWidth: 1,
    font: '',
  };
  vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
    if (tag === 'canvas') {
      const canvas = origCreateElement('canvas') as HTMLCanvasElement;
      vi.spyOn(canvas, 'getContext').mockReturnValue(
        mockCtx as unknown as CanvasRenderingContext2D,
      );
      vi.spyOn(canvas, 'toBlob').mockImplementation((cb) => {
        cb(
          new Blob([new Uint8Array([0xff, 0xd8, 0xff, 0xe0])], {
            type: 'image/jpeg',
          }),
        );
      });
      return canvas;
    }
    return origCreateElement(tag);
  });
}

function mockVideoDimensions() {
  Object.defineProperty(HTMLVideoElement.prototype, 'videoWidth', {
    value: 640,
    configurable: true,
  });
  Object.defineProperty(HTMLVideoElement.prototype, 'videoHeight', {
    value: 480,
    configurable: true,
  });
  Object.defineProperty(HTMLVideoElement.prototype, 'readyState', {
    value: 4,
    configurable: true,
  });
}

function renderMonitor(client: QueryClient, path = '/police/monitor') {
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <main id="main" tabIndex={-1}>
          <Suspense fallback="Loading">
            <MonitorPage />
          </Suspense>
        </main>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('MonitorPage & SourcePicker (F4b)', () => {
  beforeEach(() => {
    socketState.handlers.clear();
    socketState.emit.mockClear();
    resetStreamSnapshot();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    Object.defineProperty(window, 'isSecureContext', {
      value: true,
      writable: true,
      configurable: true,
    });
  });

  it('shows read-only coverage note and creates a source without coverage_area_m2', async () => {
    const user = userEvent.setup();
    const { client, postCalls } = setupEnvironment();
    renderMonitor(client);

    await screen.findByRole('heading', { name: 'Camera control' });
    expect(await screen.findByText(/25 m²/)).toBeVisible();
    expect(
      screen.getByText(/set by an admin in \/admin\/sources/i),
    ).toBeVisible();

    await user.click(screen.getByRole('button', { name: /New source/i }));
    await user.type(screen.getByLabelText('Source name'), 'East Gate Cam');
    await user.selectOptions(screen.getByLabelText('Kind'), 'VIDEO_FILE');
    await user.click(screen.getByRole('button', { name: 'Create source' }));

    await waitFor(() => expect(postCalls).toHaveLength(1));
    expect(postCalls[0]).toEqual({
      zone_id: 1,
      name: 'East Gate Cam',
      kind: 'VIDEO_FILE',
    });
    expect(postCalls[0]).not.toHaveProperty('coverage_area_m2');

    expect(
      await screen.findByRole('option', {
        name: /East Gate Cam \(Video file\)/i,
      }),
    ).toBeInTheDocument();
  });

  it('maps 422 validation details onto the create source form', async () => {
    const user = userEvent.setup();
    const { client } = setupEnvironment({
      initialSources: [],
      createSourceHandler: () =>
        Response.json(
          {
            error: {
              code: 'VALIDATION_ERROR',
              message: 'Validation failed',
              details: { name: ['Source name already exists in this zone'] },
            },
          },
          { status: 422 },
        ),
    });
    renderMonitor(client);

    await screen.findByLabelText('Source name');
    await user.type(screen.getByLabelText('Source name'), 'Duplicate Cam');
    await user.click(screen.getByRole('button', { name: 'Create source' }));

    expect(
      await screen.findByText('Source name already exists in this zone'),
    ).toBeVisible();
  });

  it('starts/stops webcam streaming, releases tracks on Stop, and enforces one active stream per tab', async () => {
    const user = userEvent.setup();
    const stopTrack1 = vi.fn();
    const stopTrack2 = vi.fn();
    const getUserMedia = vi
      .fn()
      .mockResolvedValueOnce({
        getTracks: () => [{ stop: stopTrack1, kind: 'video' }],
      })
      .mockResolvedValueOnce({
        getTracks: () => [{ stop: stopTrack2, kind: 'video' }],
      });
    Object.defineProperty(navigator, 'mediaDevices', {
      value: { getUserMedia },
      writable: true,
      configurable: true,
    });

    const otherStop = vi.fn();
    claimActiveStream(Symbol('other-tab-stream'), otherStop);

    const { client } = setupEnvironment();
    setupFakeCanvas();
    mockVideoDimensions();
    renderMonitor(client);

    await screen.findByRole('option', { name: /Main Gate camera/i });
    await user.click(screen.getByRole('button', { name: /Start streaming/i }));

    // Starting MonitorPage preempts any previously active streamer in the tab.
    expect(otherStop).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(getUserMedia).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(socketState.emit).toHaveBeenCalledWith(
        'frame:submit',
        expect.objectContaining({ source_id: 1, seq: 1, reset: true }),
      ),
    );

    // Stop releases all webcam tracks (camera LED off).
    await user.click(screen.getByRole('button', { name: /Stop streaming/i }));
    expect(stopTrack1).toHaveBeenCalledTimes(1);

    // Start again, then switch zone -> previous stream stops, tracks released, and mode syncs to Zone 2's VIDEO_FILE source.
    await user.click(screen.getByRole('button', { name: /Start streaming/i }));
    await waitFor(() => expect(getUserMedia).toHaveBeenCalledTimes(2));

    await user.selectOptions(screen.getByLabelText('Zone'), '2');
    expect(stopTrack2).toHaveBeenCalledTimes(1);
    expect(
      await screen.findByRole('button', { name: /Video file/i }),
    ).toHaveAttribute('aria-pressed', 'true');
    // Switching back to Webcam mode immediately enables Start streaming without needing a file.
    await user.click(screen.getByRole('button', { name: /Webcam/i }));
    expect(
      screen.getByRole('button', { name: /Start streaming/i }),
    ).toBeEnabled();
  });

  it('streams video file mode with loop toggle and stops cleanly', async () => {
    const user = userEvent.setup();
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:demo-video');
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});

    const { client } = setupEnvironment();
    setupFakeCanvas();
    mockVideoDimensions();
    renderMonitor(client);

    await screen.findByRole('option', { name: /Main Gate camera/i });
    await user.click(screen.getByRole('button', { name: /Video file/i }));

    const fileInput = screen.getByLabelText('Select video file');
    await user.upload(
      fileInput,
      new File(['video'], 'crowd.mp4', { type: 'video/mp4' }),
    );

    const loopBtn = await screen.findByRole('button', { name: /Loop: ON/i });
    await user.click(loopBtn);
    expect(screen.getByRole('button', { name: /Loop: OFF/i })).toBeVisible();

    await user.click(screen.getByRole('button', { name: /Start streaming/i }));
    await waitFor(() =>
      expect(socketState.emit).toHaveBeenCalledWith(
        'frame:submit',
        expect.objectContaining({ source_id: 1, seq: 1, reset: true }),
      ),
    );

    await user.click(screen.getByRole('button', { name: /Stop streaming/i }));
    expect(
      screen.getByRole('button', { name: /Start streaming/i }),
    ).toBeEnabled();
  });

  it('shows SOURCE_IN_USE message and stops retrying when server rejects with SOURCE_IN_USE', async () => {
    const user = userEvent.setup();
    const stopTrack = vi.fn();
    Object.defineProperty(navigator, 'mediaDevices', {
      value: {
        getUserMedia: vi.fn().mockResolvedValue({
          getTracks: () => [{ stop: stopTrack, kind: 'video' }],
        }),
      },
      writable: true,
      configurable: true,
    });

    const { client } = setupEnvironment();
    setupFakeCanvas();
    mockVideoDimensions();
    renderMonitor(client);

    await screen.findByRole('option', { name: /Main Gate camera/i });
    await user.click(screen.getByRole('button', { name: /Start streaming/i }));

    await waitFor(() => expect(socketState.emit).toHaveBeenCalledTimes(1));
    const submitted = socketState.emit.mock.calls[0]![1] as { seq: number };

    act(() => {
      emitSocket('frame:result', {
        source_id: 1,
        seq: submitted.seq,
        ok: false,
        error: 'SOURCE_IN_USE',
        count: 0,
        boxes: [],
        infer_ms: 0,
        smoothed_count: null,
        density: null,
        level: null,
      } satisfies FrameResult);
    });

    expect(
      await screen.findByText(
        'This source is already being streamed from another tab or device',
      ),
    ).toBeVisible();
    expect(stopTrack).toHaveBeenCalledTimes(1);
    expect(
      screen.getByRole('button', { name: /Start streaming/i }),
    ).toBeEnabled();
  });

  it('shows plain HTTP warning note in webcam mode when not in a secure context', async () => {
    const { client } = setupEnvironment({ secureContext: false });
    renderMonitor(client);

    expect(
      await screen.findByText(/Camera blocked on plain HTTP/i),
    ).toBeVisible();
  });

  it('keeps parent hook free of 3 FPS re-renders with syncState=false and updates HUD + Zone status card', async () => {
    setupFakeCanvas();
    const video = document.createElement('video');
    Object.defineProperty(video, 'videoWidth', { value: 640 });
    Object.defineProperty(video, 'videoHeight', { value: 480 });
    Object.defineProperty(video, 'readyState', { value: 4 });

    let hookRenders = 0;
    const { unmount } = renderHook(() => {
      hookRenders += 1;
      return useFrameStreamer({
        video,
        sourceId: 1,
        enabled: true,
        config: { target_fps: 3, frame_width: 640, jpeg_quality: 0.7 },
        syncState: false,
      });
    });

    await waitFor(() => expect(socketState.emit).toHaveBeenCalledTimes(1));
    const rendersBeforeFrames = hookRenders;

    for (let seq = 1; seq <= 3; seq++) {
      await waitFor(() => expect(socketState.emit).toHaveBeenCalledTimes(seq));
      act(() => {
        emitSocket('frame:result', {
          ...(frameResultFixture as FrameResult),
          source_id: 1,
          seq,
          count: seq + 2,
          smoothed_count: seq + 2,
          density: 0.4,
          level: 'WARNING',
        });
      });
    }

    // Parent component calling useFrameStreamer(syncState=false) never re-rendered on 3 FPS results.
    expect(hookRenders).toBe(rendersBeforeFrames);
    expect(useMonitorStore.getState().lastResult?.count).toBe(5);
    unmount();

    // Now verify MonitorPage renders HUD from store and Zone status card from zone:detail.
    resetStreamSnapshot();
    const { client } = setupEnvironment();
    renderMonitor(client);

    await screen.findByRole('option', { name: /Main Gate camera/i });
    act(() => {
      useMonitorStore.setState({
        lastResult: {
          ...(frameResultFixture as FrameResult),
          count: 5,
          smoothed_count: 4,
          density: 0.4,
          level: 'WARNING',
        },
        fps: 3.0,
        latencyMs: { p50: 35, p95: 48 },
        drops: 0,
      });
      updatePoliceZone(client, {
        ...zones[0]!,
        level: 'CRITICAL',
        count: 6,
        density: 0.24,
        live_updated_at: new Date().toISOString(),
      });
    });

    const hud = screen.getByRole('region', { name: 'Monitor statistics' });
    expect(within(hud).getByText('5')).toBeVisible();
    expect(within(hud).getByText('4')).toBeVisible();
    expect(within(hud).getByText('Warning')).toBeVisible();

    const zoneStatus = screen.getByRole('region', { name: 'Zone live status' });
    expect(await within(zoneStatus).findByText('Critical')).toBeVisible();
  });

  it('supports camera facing toggle on mobile and passes axe accessibility checks', async () => {
    const user = userEvent.setup();
    const getUserMedia = vi.fn().mockResolvedValue({
      getTracks: () => [{ stop: vi.fn(), kind: 'video' }],
    });
    Object.defineProperty(navigator, 'mediaDevices', {
      value: { getUserMedia },
      writable: true,
      configurable: true,
    });

    const { client } = setupEnvironment();
    const view = renderMonitor(client);

    const facingBtn = await screen.findByRole('button', {
      name: /Camera: Front/i,
    });
    await user.click(facingBtn);
    expect(facingBtn).toHaveAttribute('aria-pressed', 'true');

    await user.click(screen.getByRole('button', { name: /Start streaming/i }));
    await waitFor(() =>
      expect(getUserMedia).toHaveBeenCalledWith({
        video: { facingMode: 'environment', width: { ideal: 1280 } },
        audio: false,
      }),
    );

    expect(
      (
        await axe(view.container, {
          rules: { 'color-contrast': { enabled: false } },
        })
      ).violations,
    ).toEqual([]);
  });
});
